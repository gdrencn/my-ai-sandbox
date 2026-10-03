"""Portable real-LXD test runner, using only Python's standard library."""

import base64
import contextlib
import errno
import fcntl
import hashlib
import importlib
from importlib.resources import files
import io
import json

import os
from pathlib import Path
import platform
import pty
import re
import select
import signal
import stat
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
import traceback
import unittest
from unittest.mock import patch
import uuid
import zipfile

from . import __version__, config
from .test_output import Output
from .core import Error, LXD, Manager, MANAGED, host_image, finish_client

from .i18n import t, Parser, catalog, progress_text
from .diagnostics import cleanup_scope, notify, warn


PRODUCT_UNDER_TEST = None


def python_command(source, *options):
    """Run a Python fixture against this tester, independent of cwd/user imports."""
    root = str(Path(__file__).resolve().parent.parent)
    preamble = f"import sys; sys.path.insert(0, {root!r})\n"
    return [sys.executable, '-I', *options, '-c', preamble + source]

def unit_modules():
    return [importlib.import_module('tests.' + item.name[:-3])
            for item in sorted(files('tests').iterdir(), key=lambda item: item.name)
            if item.name.startswith('test_') and item.name.endswith('.py')]


def test_ids(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from test_ids(test)
        else:
            yield test.id()


def unit_summary(result, modules, identifiers):
    return dict(tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                skipped=[dict(test=test.id(), reason=reason) for test, reason in result.skipped],
                expected_failures=[test.id() for test, _ in result.expectedFailures],
                unexpected_successes=[test.id() for test in result.unexpectedSuccesses],
                successful=result.wasSuccessful(), modules=[module.__name__ for module in modules],
                test_ids=identifiers)


def random_target():
    return "test-" + uuid.uuid4().hex


class Terminal:
    def __init__(self, command, timeout, transcript, on_wait=None, on_read=None):
        self.timeout = timeout
        self.on_wait = on_wait
        self.on_read = on_read
        self.started = self.last_update = time.monotonic()
        self.buffer = b""
        self.cursor = 0
        self.status = None
        self.eof = False
        self.transcript = transcript.open("wb")
        try:
            self.pid, self.fd = pty.fork()
        except BaseException:
            self.transcript.close()
            raise
        if self.pid == 0:
            try:
                os.environ["TERM"] = "xterm"
                os.execvpe(command[0], command, os.environ)
            except Exception:
                # A test runner may have redirected Python's sys.stderr to its
                # unit log. Child diagnostics belong to this PTY's descriptor.
                with os.fdopen(os.dup(2), 'w') as errors:
                    traceback.print_exc(file=errors)
                os._exit(127)
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 200, 0, 0))
        except BaseException:
            with cleanup_scope(self.close):
                raise

    def _receive(self, wait):
        if self.eof:
            if wait:
                time.sleep(wait)
            return False
        if select.select([self.fd], [], [], wait)[0]:
            try:
                chunk = os.read(self.fd, 65536)
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                chunk = b""
            if not chunk:
                self.eof = True
                return False
            self.buffer += chunk
            self.transcript.write(chunk)
            self.transcript.flush()
            return True
        return False

    def _reap(self):
        if self.status is None:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.status = os.waitstatus_to_exitcode(status)

    def _drain(self):
        # A descendant can retain the PTY after the child exits. Consume queued
        # bytes without waiting for its EOF, and bound continuous writers.
        deadline = time.monotonic() + self.timeout
        while self._receive(0):
            if time.monotonic() >= deadline:
                raise Error(t('pty_drain_timeout', timeout=self.timeout))

    def read(self):
        now = time.monotonic()
        if self.on_wait and now - self.last_update >= 1:
            self.on_wait(now - self.started)
            self.last_update = now
        try:
            self._receive(0.1)
        finally:
            self._reap()
        if self.status is not None:
            self._drain()
        if self.on_read:
            self.on_read()

    def send(self, value):
        os.write(self.fd, value.encode())

    def expect(self, text):
        self.expect_pattern(re.escape(text.encode()), text)

    def expect_menu(self, title):
        """Wait for an active menu title, not an earlier option/progress label."""
        self.expect_pattern(rb'\x1b\[\?25l' + re.escape(title.encode()) + rb'\r?\n', title)

    def expect_pattern(self, pattern, description):
        start = time.monotonic()
        while time.monotonic() - start < self.timeout:
            match = re.search(pattern, self.buffer[self.cursor:])
            if match is not None:
                self.cursor += match.end()
                return
            if self.status is not None:
                raise AssertionError(t("pty_exited", status=self.status, text=description, buffer=self.buffer[-2000:]))
            self.read()
        raise AssertionError(t("pty_timeout", timeout=self.timeout, text=description, buffer=self.buffer[-2000:]))

    def shell_ready(self):
        # Match the visible Ubuntu sandbox prompt, not OSC window/session titles.
        # Imported instances may retain a hostname different from their TARGET.
        self.expect_pattern(rb"(?:\A|[\r\n]|\x07|\x1b\\)sandbox@[^\r\n\x1b\x07]*:[^\r\n\x1b\x07]*\$ ",
                            "sandbox shell prompt")

    def finish(self, status=0):
        start = time.monotonic()
        while self.status is None and time.monotonic() - start < self.timeout:
            self.read()
        if self.status != status:
            raise AssertionError(t("pty_status", status=self.status, buffer=self.buffer[-2000:]))

    def close(self):
        if self.fd is None:
            return
        # Final event consumption is owned by Suite even if it fails. It must
        # not prevent process termination and descriptor release here.
        self.on_read = None
        self.on_wait = None
        errors = []
        def attempt(operation):
            try:
                operation()
                return True
            except Exception as exc:
                errors.append(exc)
                return False
        try:
            # Reaping/termination must not depend on PTY reads or log writes.
            attempt(self._reap)
            for sig in (signal.SIGTERM, signal.SIGKILL):
                if self.status is not None:
                    break
                def send_signal():
                    try:
                        os.killpg(self.pid, sig)
                    except ProcessLookupError:
                        # pty.fork's child may not have established its process
                        # group yet. Its unreaped PID is still our own child.
                        with contextlib.suppress(ProcessLookupError):
                            os.kill(self.pid, sig)
                attempt(send_signal)
                deadline = time.monotonic() + self.timeout
                while self.status is None and time.monotonic() < deadline:
                    if not attempt(self._reap):
                        break
                    if self.status is None:
                        time.sleep(0.1)
            if self.status is None:
                errors.append(Error(t('pty_cleanup_timeout', pid=self.pid, timeout=self.timeout)))
            else:
                attempt(self._drain)
        finally:
            attempt(lambda: os.close(self.fd))
            self.fd = None
            attempt(self.transcript.close)
        if errors:
            for error in errors[1:]:
                warn('cleanup_secondary', error)
            raise errors[0]


class Suite:
    CASE_CATEGORIES = {
        'unit': 'foundation',
        'new-default': 'management',
        'isolation-policy': 'configuration',
        'legacy-migration': 'management',
        'missing-image': 'management',
        'configuration-concurrency': 'configuration',
        'list-info': 'management',
        'invalid-inputs': 'management',
        'start-user-network': 'management',
        'gpu': 'resources',
        'dependency-install': 'environment',
        'lifecycle-repeat': 'management',
        'restart': 'management',
        'running-guards': 'management',
        'enter-running-default-exit': 'management',
        'enter-stopped-stop-exit': 'management',
        'export-import': 'management',
        'overwrite-confirmation': 'interaction',
        'ownership-and-stop-all': 'management',
        'unmarked-import': 'management',
        'filesystems': 'resources',
        'filesystem-recovery': 'resources',
        'filesystem-menu': 'interaction',
        'delete-confirmation': 'interaction',
        'language-config': 'interaction',
        'tui': 'interaction',
        'isolation-runtime': 'security',
    }
    CASES = list(CASE_CATEGORIES)

    def __init__(self, report_dir, timeout, product=None):
        self.output = Output()
        self.started = time.monotonic()
        self.language = config.language()
        self.directory = report_dir
        self.product = product.resolve() if product else None
        if self.product:
            result = subprocess.run([sys.executable, str(self.product), "--version"],
                                    text=True, capture_output=True, timeout=600)
            if result.returncode or result.stdout.strip() != __version__:
                raise Error(t('version_mismatch'))
        report_dir.mkdir(parents=True, exist_ok=False)
        self.workspace = tempfile.TemporaryDirectory(prefix="backups-", dir=report_dir)
        self.config_home = Path(self.workspace.name) / "config"
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config_home)}):
            config.set_value("language", self.language)
        self.timeout = timeout
        self.project = random_target()
        self.host = LXD(timeout=timeout, diagnostic=self.native_diagnostic)
        self.fs_root = self.directory / "mounts"
        self.fs_state = self.directory / "mount-state"
        self.manager = Manager(LXD(project=self.project, timeout=timeout, diagnostic=self.native_diagnostic), self.report, self.fs_root, self.fs_state)
        self.manager.gpu.keep_known_warnings = True
        self.created_project = False
        self.targets = []
        self.legacy_targets = []
        self.legacy_profiles = []
        self.events = []
        self.results = {case: {"status": "not_run", "category": self.CASE_CATEGORIES[case]} for case in self.CASES}
        self.cleanup_errors = []
        self.counter = 0
        self.event_offsets = {}
        self.unit_results = None
        self.gpu_results = {"status": "not_run"}
        self.isolation_results = {'status': 'not_run'}
        self.guest_reports = []

    def native_diagnostic(self, message):
        self.events.append(dict(action='diagnostic', status='warning', native_stderr=message,
                                case=getattr(self, 'current_case', None), source='direct'))
        with (self.directory / 'native-diagnostics.log').open('a', encoding='utf-8') as log:
            log.write(message + '\n')
        self.output.keep(message)

    def report(self, event):
        self.events.append(event)
        self.output.progress(progress_text(event))
        self.output.diagnostics(event.get("native_stdout", ""), event.get("native_stderr", ""))

    @contextlib.contextmanager
    def case(self, name):
        start = time.monotonic()
        self.current_case = name
        title = t("case_" + name)
        category = self.CASE_CATEGORIES[name]
        description = t("test_description_" + name)
        metadata = dict(category=category, description=description)
        self.output.section(t("test_category_" + category), title, description)
        self.output.progress(t("working", name=title, elapsed=0))
        try:
            yield
        except BaseException as exc:
            self.results[name] = {"status": "failed", "elapsed": time.monotonic() - start, "error": str(exc), **metadata}
            self.output.result(t("stage_failed", name=title, elapsed=time.monotonic()-start, error=exc), passed=False)
            raise
        else:
            self.results[name] = {"status": "passed", "elapsed": time.monotonic() - start, **metadata}
            self.output.result(t("test_pass", name=title, elapsed=self.results[name]["elapsed"]), passed=True)

    def target(self):
        name = random_target()
        self.targets.append(name)
        return name

    def command(self, args):
        # The injected Manager scopes the actual product to this test project.
        self.event_path = self.directory / f"events-{self.counter}.jsonl"
        source = ("import os,sys,json;os.environ['XDG_CONFIG_HOME']=" + repr(str(self.config_home)) + ";"
                  "sys.path.insert(0," + repr(str(self.product) if self.product else sys.path[0]) + ");"
                  "from mas.cli import main,Progress;from mas.core import Manager,LXD;"
                  "events=open(" + repr(str(self.event_path)) + ", 'a');"
                  "progress=Progress();report=lambda event:(events.write(json.dumps(event)+'\\n'),events.flush(),progress(event));"
                  "diagnostic=lambda message:(events.write(json.dumps(dict(action='diagnostic',status='warning',native_stderr=message))+'\\n'),events.flush(),progress.output.keep(message));"
                  "manager=Manager(LXD(project=" + repr(self.project) +
                  ",timeout=" + str(self.timeout) + ",diagnostic=diagnostic),report=report,fs_root=" + repr(str(self.fs_root)) + ",fs_state=" + repr(str(self.fs_state)) + ");manager.gpu.keep_known_warnings=True;raise SystemExit(main(manager=manager))")
        return [sys.executable, "-c", source, *args]

    def read_events(self, path, diagnostics=False):
        displayed = []
        if path.exists():
            offsets = self.__dict__.setdefault('event_offsets', {})
            with path.open('rb') as stream:
                stream.seek(offsets.get(str(path), 0))
                raw = stream.read()
            complete = raw.rfind(b'\n') + 1
            offsets[str(path)] = offsets.get(str(path), 0) + complete
            events = [json.loads(line) for line in raw[:complete].splitlines() if line]
            for event in events:
                event.setdefault('case', getattr(self, 'current_case', None))
                event.setdefault('source', path.name)
            self.events.extend(events)
            if diagnostics:
                for event in events:
                    # The failed command's final stderr contains its native
                    # failure text. Retain the event, display that text once.
                    if event.get('native_failure'):
                        continue
                    displayed.extend(self.output.diagnostics(event.get("native_stdout", ""), event.get("native_stderr", "")))
        return displayed

    def cli(self, *args, answer=None, code=0):
        start = time.monotonic()
        self.counter += 1
        arguments = list(args)
        if answer is not None and args[0] in ('delete', 'export', 'enter', 'migrate'):
            arguments.append('--yes' if answer.strip().lower() in ('y', 'yes') else '--no')
        command = self.command(arguments)
        event_path = self.event_path
        stdout_path = self.directory / f"cli-{self.counter}.stdout.log"
        stderr_path = self.directory / f"cli-{self.counter}.stderr.log"
        action = catalog(self.language).get("action_" + args[0], args[0])
        if code != 0:
            self.output.expected_error(" ".join(args))
        displayed = []
        out, err = '', ''
        with stdout_path.open("w+") as stdout, stderr_path.open("w+") as stderr:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, text=True)
            def collect_output():
                nonlocal out, err
                stdout.seek(0)
                stderr.seek(0)
                out, err = stdout.read(), stderr.read()
                self.output.diagnostics("" if "--help" in args and process.returncode == 0 else out,
                                        err, failed=process.returncode != 0, exclude=displayed)
            def collect_events():
                displayed.extend(self.read_events(event_path, diagnostics=True))
            def finish_command():
                self._finalize(lambda: finish_client(process, self.timeout), collect_events, collect_output)
            with cleanup_scope(finish_command, lambda exc: None):
                try:
                    process.stdin.write(answer or "")
                    process.stdin.close()
                except BrokenPipeError:
                    pass
                while process.poll() is None:
                    displayed.extend(self.read_events(event_path, diagnostics=True))
                    elapsed = time.monotonic() - start
                    if elapsed >= self.timeout * 3:
                        raise Error(t("wait_timeout", label=" ".join(args), timeout=self.timeout*3))
                    self.output.progress(t("working", name=action + " " + " ".join(args[1:]), elapsed=elapsed))
                    time.sleep(1)
        if process.returncode != code:
            raise AssertionError(t("cli_failed", args=args, expected=code, actual=process.returncode, stdout=out, stderr=err))
        return out

    def _finalize(self, *steps):
        """Try each independent cleanup step even if reporting itself fails."""
        errors = []
        for step in steps:
            try:
                step()
            except Exception as exc:
                errors.append(str(exc))
                self.cleanup_errors.append(str(exc))
                notify(lambda: self.output.keep(t('cleanup_secondary', error=exc)))
        if errors:
            raise Error('\n'.join(errors))

    @contextlib.contextmanager
    def terminal(self, args):
        self.counter += 1
        # English UI fixture expectations are isolated from user-facing output.
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config_home)}):
            previous = config.get("language")
            config.set_value("language", "en_us")
        terminal = None
        event_path = None
        def restore_language():
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config_home)}):
                config.set_value("language", previous)
        def finish_session():
            self._finalize(lambda: terminal.close() if terminal else None,
                           lambda: self.read_events(event_path, diagnostics=True) if event_path else None,
                           restore_language)
        with cleanup_scope(finish_session, lambda exc: None):
            command = self.command(args)
            event_path = self.event_path
            terminal = Terminal(command, self.timeout, self.directory / f"terminal-{self.counter}.log",
                                on_wait=lambda elapsed: self.output.progress(t("working", name=t("case_" + self.current_case), elapsed=elapsed)),
                                on_read=lambda: self.read_events(event_path, diagnostics=True))
            yield terminal

    def wait(self, label, probe, terminal=None):
        start = time.monotonic()
        while time.monotonic() - start < self.timeout:
            if terminal:
                terminal.read()
                if terminal.status is not None:
                    raise AssertionError(t("pty_unexpected", buffer=terminal.buffer[-2000:]))
            if probe():
                elapsed = time.monotonic() - start
                self.output.progress(t("test_wait", label=t("wait_" + label), elapsed=elapsed))
                self.events.append(dict(action="test-wait", target=label, status="ok", elapsed=elapsed))
                return
            self.output.progress(t("working", name=t("wait_" + label), elapsed=time.monotonic()-start))
            time.sleep(1)
        raise AssertionError(t("wait_timeout", label=label, timeout=self.timeout))

    def state(self, target, expected):
        instance = self.manager.find(target)
        return (instance["status"] if instance else "Absent") == expected

    def expected_native_refusal(self, args):
        self.output.expected_error('lxc ' + ' '.join(args))
        try:
            self.manager.lxd.command(args)
        except Error as exc:
            self.output.keep(str(exc))
            assert re.search(r'\b(?:forbidden|not allowed)\b', str(exc), re.IGNORECASE), \
                'Expected an explicit LXD policy refusal, not an unrelated error: ' + str(exc)
            self.events.append(dict(action='isolation-refusal', status='ok', command=args, error=str(exc)))
        else:
            raise AssertionError(t('policy_test_accepted', command=repr(args)))

    def isolation_policy(self, target):
        self.manager.isolation.check()
        for key, value in [('security.privileged','true'), ('raw.idmap','both 1000 1000'),
                           ('raw.lxc','lxc.apparmor.profile=unconfined'),
                           ('raw.apparmor','deny /etc/** r,'),
                           ('raw.seccomp','false'), ('linux.kernel_modules','dummy'),
                           ('security.delegate_bpf','true'), ('security.nesting','true'),
                           ('security.syscalls.intercept.mount','true')]:
            self.expected_native_refusal(['config','set','local:'+target,key+'='+value])
        self.expected_native_refusal(['config','device','add','local:'+target,'mas-test-block',
                                     'disk','source=/etc','path=/host-etc','readonly=true'])
        self.manager.lxd.command(['config','set','local:'+target,'security.syscalls.deny_default=false'])
        try:
            self.cli('start',target,code=1)
            assert self.state(target,'Stopped')
        finally:
            self.manager.lxd.command(['config','unset','local:'+target,'security.syscalls.deny_default'])
        gpu_record = self.manager.gpu.record(self.manager.info(target))
        if gpu_record and gpu_record['backend']=='wsl-nvidia' and gpu_record['enabled']:
            self.manager.lxd.command(['config','device','set','local:'+target,'mas-gpu-lib','readonly=false'])
            try:
                self.cli('start',target,code=1)
                assert self.state(target,'Stopped')
            finally:
                self.manager.lxd.command(['config','device','set','local:'+target,'mas-gpu-lib','readonly=true'])
            self.manager.lxd.command(['config','device','add','local:'+target,'mas-test-extra-char',
                                     'unix-char','source=/dev/null','path=/dev/mas-test-null'])
            try:
                self.cli('start',target,code=1)
                assert self.state(target,'Stopped')
            finally:
                self.manager.lxd.command(['config','device','remove','local:'+target,'mas-test-extra-char'])
        # Project allowlists do not constrain pool-backed extra volumes.
        record = self.manager.isolation.check()
        volume = random_target()
        self.manager.lxd.command(['storage','volume','create','local:'+record['pool'],volume])
        try:
            args = ['config','device','add','local:'+target,'mas-test-volume',
                    'disk','pool='+record['pool'],'source='+volume,'path=/extra-volume']
            if 'wsl-nvidia' not in record['backends']:
                self.expected_native_refusal(args)
            else:
                self.manager.lxd.command(args)
                try:
                    self.cli('start',target,code=1)
                    assert self.state(target,'Stopped')
                finally:
                    self.manager.lxd.command(['config','device','remove','local:'+target,'mas-test-volume'])
        finally:
            self.manager.lxd.command(['storage','volume','delete','local:'+record['pool'],volume])
        self.manager.isolation.audit(self.manager.info(target))
        # Preserve rejected native backup data in its stopped staging project.
        backup = Path(self.workspace.name) / 'unsafe-backup.tar.gz'
        self.manager.lxd.command(['config','set','local:'+target,'security.syscalls.deny_default=false'])
        try:
            self.cli('export',target,str(backup))
        finally:
            self.manager.lxd.command(['config','unset','local:'+target,'security.syscalls.deny_default'])
        rejected = self.target()
        before = len(self.events)
        self.cli('import',rejected,str(backup),code=1)
        assert self.manager.find(rejected) is None
        owners = [e['owner'] for e in self.events[before:] if e.get('phase') == 'staging-created']
        assert len(owners) == 1
        staging = Manager(LXD(project=owners[0]['project'],timeout=self.timeout))
        restored = staging.find(rejected)
        assert restored and restored['status']=='Stopped' and not self.manager.managed(restored), restored
        assert restored['config']['security.syscalls.deny_default']=='false'
        assert restored['config']['boot.autostart']=='false' and backup.is_file()
        self.cli('start',rejected,code=1)

    def isolation_runtime(self, target):
        report = self.guest_boundary(target)
        checks = {item['check']: item for item in report['checks'] + report.get('observations', [])}
        attribute = checks['apparmor']['evidence'].get('profile', '')
        self.isolation_results = dict(status='passed', project=self.project,
            policy=self.manager.isolation.check(),
            guest=dict(uid_map=checks['uid-map']['evidence']['mapping'],
                       gid_map=checks['gid-map']['evidence']['mapping'],
                       namespaces={name:checks['namespace:'+name]['evidence']['guest']
                                   for name in ('user','pid','mnt','net','ipc','uts')},
                       seccomp=checks['seccomp']['evidence']['mode'], apparmor_profile=attribute),
            host_namespaces={name:checks['namespace:'+name]['evidence']['host']
                             for name in ('user','pid','mnt','net','ipc','uts')},
            apparmor_enabled=checks['apparmor']['evidence'].get('enabled', 'unavailable'),
            apparmor_confinement_verified=bool(attribute and attribute.startswith('lxd-') and attribute.endswith(' (enforce)')))

    def guest_boundary(self, target, positive=True):
        """The complete challenge owns reference collection and guest execution."""
        from .security_testing import run_challenge
        path = self.directory / f'boundary-{len(self.guest_reports)+1}.json'
        code, evidence, primary = run_challenge(self.manager, target, path, self.output,
                                               project=self.project, positive=positive)
        self.guest_reports.append(evidence)
        if primary is not None:
            raise primary
        assert code == 0, evidence['report']
        return evidence['report']

    def legacy_fixture(self):
        record = self.manager.isolation.check()
        target = random_target()
        profile = random_target()
        body, _ = self.host.configuration.request('POST',self.host.configuration.endpoint('/1.0/profiles'),
            {'name':profile,'config':{'user.mas.test.run':self.project,'limits.memory':'2GiB',
                                     'user.mas.migration.inherited':'keep'},
             'devices':self.manager.isolation.devices(record)})
        self.manager.isolation.sync_result(body)
        self.legacy_profiles.append(profile)
        self.host.command(['init',host_image(),'local:'+target,'--profile',profile,
                           '-c',MANAGED+'=true','-c','user.mas.test.run='+self.project,
                           '-c','security.privileged=false','-c','security.nesting=false',
                           '-c','security.syscalls.deny_default=true'])
        self.legacy_targets.append(target)
        return target

    def legacy_migration(self):
        from .core import USER_SETUP
        target = self.legacy_fixture()
        self.manager.isolation.audit(self.manager.legacy.require(target),legacy=True)
        self.manager.legacy._run_lxd_until_state('start',target,['start','local:'+target],'Running')
        self.host.command(['exec','local:'+target,'--','/bin/sh','-c',USER_SETUP])
        self.host.command(['exec','local:'+target,'--','/bin/sh','-c',
                           "printf 'migration preserved' > /home/sandbox/mas-migration; chown sandbox:sandbox /home/sandbox/mas-migration"])
        self.manager.legacy._run_lxd_until_state('stop',target,['stop','local:'+target],'Stopped')
        original = self.manager.legacy.require(target)
        self.host.command(['config','set','local:'+target,'security.syscalls.deny_default=false'])
        try:
            self.cli('migrate',target,'--yes',code=1)
            assert self.manager.legacy.require(target)['config']['security.syscalls.deny_default']=='false'
            assert self.state(target,'Absent')
        finally:
            self.host.command(['config','set','local:'+target,'security.syscalls.deny_default=true'])
        # Exercise cancellation through a real menu, selecting only our fixture.
        with self.terminal([]) as terminal:
            terminal.expect('my-ai-sandbox');terminal.send('\x1b[B'*3+'\n')
            terminal.expect('Migrate legacy-version containers')
            terminal.expect('Containers must be stopped with no recorded mounts.')
            names=[i['name'] for i in self.manager.legacy_list()]
            terminal.send('\x1b[B'*names.index(target)+'\n')
            terminal.expect('Move stopped container '+target)
            terminal.send('\n');terminal.expect('Cancelled.')
            terminal.send('\n');terminal.expect('my-ai-sandbox');terminal.send('\x1b[D');terminal.finish()
        assert self.manager.legacy.require(target)['config']==original['config']
        self.targets.append(target)
        self.cli('migrate',target,'--yes')
        assert self.manager.legacy.find(target) is None
        migrated = self.manager.info(target)
        assert migrated['config']['limits.memory']=='2GiB'
        assert migrated['config']['user.mas.migration.inherited']=='keep'
        self.cli('start',target)
        assert self.exec(target,"cat /home/sandbox/mas-migration")=='migration preserved'
        assert self.exec(target,"su --login sandbox -c 'sudo -n id -u'").strip()=='0'
        self.cli('stop',target)
        self.cli('delete',target,'--yes')

    def exec(self, target, script):
        return self.manager.lxd.command(["exec", "local:" + target, "--", "/bin/sh", "-c", script])

    def check_shell(self, terminal):
        terminal.shell_ready()
        # Split literal strings so terminal input echo cannot satisfy the output match.
        terminal.send("printf 'MAS_%s\\n' SHELL; id -un; sudo -n id -u\n")
        terminal.expect("MAS_SHELL\r\n")
        terminal.expect("sandbox\r\n")
        terminal.expect("0\r\n")
        # sudo can print its result before restoring the terminal. Wait until
        # the shell has regained control before sending another command.
        terminal.shell_ready()

    def run(self):
        self.functional_tests()
        with self.case('isolation-runtime'):
            self.security_fixture()

    def functional_tests(self):
        target, imported, external = self.target(), self.target(), self.target()
        with self.case("unit"):
            modules = unit_modules()
            units = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module) for module in modules)
            identifiers = list(test_ids(units))
            with (self.directory / "unit.log").open("w+") as log:
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    result = unittest.TextTestRunner(stream=log, verbosity=2).run(units)
                self.unit_results = unit_summary(result, modules, identifiers)
                log.seek(0)
                details = log.read()
            if not result.wasSuccessful():
                self.output.keep(details)
            else:
                self.output.diagnostics(details, "")
            assert result.wasSuccessful(), t("unit_failed")
        with self.case("new-default"):
            try:
                self.manager.isolation.provision()
            finally:
                self.created_project = self.manager.isolation.created
            self.cli("new", target)
            assert self.state(target, "Stopped")
            assert self.manager.info(target)["config"]["image.version"] == host_image().split(":")[1]
            assert 'cloud-init.user-data' not in self.manager.info(target)['config']
            from .development import PACKAGES, RECORD
            prepared = json.loads(self.manager.lxd.command(['file','pull','local:'+target+RECORD,'-']))
            assert set(prepared['packages']) == set(PACKAGES)
            assert prepared['node'] == prepared['node_lts']['version']
            assert prepared['npm'] == prepared['node_lts']['npm']
            assert prepared['node_lts']['source'].startswith('https://nodejs.org/dist/')
            assert re.fullmatch('[0-9a-f]{64}', prepared['node_lts']['sha256'])
        self.results['new-default']['development'] = prepared
        with self.case('isolation-policy'):
            self.isolation_policy(target)
        with self.case('legacy-migration'):
            self.legacy_migration()
        with self.case("missing-image"):
            missing = self.target()
            self.cli("new", missing, "--image", "ubuntu:mas-missing-" + uuid.uuid4().hex, code=1)
            assert self.state(missing, "Absent"), t("image_unexpected")
        with self.case('configuration-concurrency'):
            configuration = self.manager.lxd.configuration
            snapshot, etag = configuration.read(target)
            self.manager.lxd.command(['config', 'set', 'local:' + target, 'user.mas.test.concurrent=native-change'])
            self.manager.lxd.command(['config', 'device', 'add', 'local:' + target, 'mas-test-concurrent', 'none'])
            snapshot['config']['user.mas.test.stale'] = 'must-not-publish'
            self.output.expected_error('PUT If-Match stale ETag')
            try:
                configuration.write(target, snapshot, etag)
            except Error as exc:
                assert str(exc) == t('lxd_config_changed'), str(exc)
                self.output.keep(str(exc))
            else:
                raise AssertionError('LXD accepted a stale ETag')
            current, fresh = configuration.read(target)
            assert current['config']['user.mas.test.concurrent'] == 'native-change'
            assert current['devices']['mas-test-concurrent'] == {'type': 'none'}
            assert 'user.mas.test.stale' not in current['config']
            current['config']['user.mas.test.conditional'] = 'published'
            configuration.write(target, current, fresh,
                on_wait=lambda elapsed: self.output.progress(t('working', name=t('case_configuration-concurrency'), elapsed=elapsed)))
            observed, _ = configuration.read(target)
            assert observed['config']['user.mas.test.conditional'] == 'published'
            assert observed['config']['user.mas.test.concurrent'] == 'native-change'
            assert observed['devices']['mas-test-concurrent'] == {'type': 'none'}
            self.events.append(dict(action='configuration-concurrency', target=target, status='ok',
                                    stale_rejected=True, concurrent_config_preserved=True,
                                    concurrent_device_preserved=True, conditional_update_observed=True))
        with self.case("list-info"):
            assert target in self.cli("list")
            assert json.loads(self.cli("info", target))["status"] == "Stopped"
            self.cli("new", target, code=1)
        with self.case("invalid-inputs"):
            missing = self.target()
            for action in ('start', 'stop', 'restart', 'info', 'delete', 'enter'):
                self.cli(action, missing, code=1)
            self.cli('export', missing, str(self.directory/'missing.tar.gz'), code=1)
            self.cli('import', missing, str(self.directory/'missing.tar.gz'), code=1)
            self.cli('new', 'remote:bad', code=1)
            self.cli('new', 'bad/snapshot', code=1)
            bad = Path(self.workspace.name)/'corrupt.tar.gz'
            bad.write_bytes(b'not an LXD backup')
            self.cli('import', missing, str(bad), code=1)
            assert self.state(missing, 'Absent')
            assert self.state(target, 'Stopped')
        with self.case("start-user-network"):
            self.cli("start", target)
            assert self.exec(target, "su --login sandbox -c 'id -un; sudo -n id -u'").splitlines() == ["sandbox", "0"]
            self.wait("outbound HTTPS", lambda: self.network(target))
            self.exec(target, "printf '%s' mas-roundtrip-data > /home/sandbox/mas-proof")
        with self.case("gpu"):
            self.gpu_test()
        with self.case("dependency-install"):
            self.dependencies(target)
        with self.case("lifecycle-repeat"):
            before = self.exec(target, 'sha256sum /var/lib/mas/development.json')
            self.exec(target, 'dpkg --remove zstd; ! command -v zstd')
            identity = self.exec(target, "id -u sandbox; getent passwd sandbox")
            self.exec(target, "printf preserve > /home/sandbox/mas-retain; usermod --shell /bin/sh sandbox")
            try:
                self.cli('start', target)
                assert self.exec(target, 'getent passwd sandbox').rstrip().endswith(':/bin/sh')
                assert self.exec(target, 'cat /home/sandbox/mas-retain') == 'preserve'
                assert self.exec(target, 'id -u sandbox') == identity.splitlines()[0]+'\n'
                self.cli('stop', target)
                self.cli('stop', target)
                self.cli('start', target)
                assert self.exec(target, 'cat /home/sandbox/mas-retain') == 'preserve'
                assert self.exec(target, "su --login sandbox -c 'sudo -n id -u'").strip() == '0'
                self.exec(target, '! command -v zstd')
                assert self.exec(target, 'sha256sum /var/lib/mas/development.json') == before
            finally:
                self.exec(target, 'usermod --shell /bin/bash sandbox')
        with self.case('restart'):
            boot = self.exec(target, 'cat /proc/sys/kernel/random/boot_id')
            self.cli('restart', target)
            assert self.state(target, 'Running')
            self.exec(target, '! command -v zstd')
            assert self.exec(target, 'cat /proc/sys/kernel/random/boot_id') != boot
            assert self.exec(target, 'cat /home/sandbox/mas-retain') == 'preserve'
            self.cli('stop', target)
            self.cli('restart', target)
            assert self.state(target, 'Running')
            with self.terminal(['restart', target, '-e']) as terminal:
                self.check_shell(terminal)
                terminal.send('exit\n')
                terminal.expect('Container terminal finished: ' + target)
                terminal.send('\n'); terminal.finish()
            assert self.state(target, 'Running')
            with self.terminal(['enter', target]) as terminal:
                self.check_shell(terminal)
                terminal.send('exit 7\n')
                terminal.expect('Container terminal finished: ' + target)
                terminal.send('\x1b[A\n')
                terminal.expect('Container terminal exited with status 7.')
                terminal.expect('Container: ' + target)
                terminal.send('\x1b[D'); terminal.expect('my-ai-sandbox')
                terminal.send('\x1b[A\n'); terminal.finish(status=1)
            assert self.state(target, 'Running')
        with self.case("running-guards"):
            self.cli("delete", target, answer="y\n", code=1)
            self.cli("export", target, str(self.directory / "forbidden.tar.gz"), code=1)
            assert self.state(target, "Running")
        with self.case("enter-running-default-exit"):
            with self.terminal(["enter", target]) as terminal:
                self.check_shell(terminal)
                terminal.send("exit\n")
                terminal.expect('Container terminal finished: ' + target)
                terminal.send("\n")
                terminal.finish()
            assert self.state(target, "Running")
        with self.case("enter-stopped-stop-exit"):
            self.cli("stop", target)
            with self.terminal(["enter", target]) as terminal:
                self.check_shell(terminal)
                terminal.send("exit\n")
                terminal.expect('Container terminal finished: ' + target)
                terminal.send("\x1b[B\n")
                terminal.finish()
            assert self.state(target, "Stopped")
        backup = Path(self.workspace.name) / "backup.tar.gz"
        with self.case("export-import"):
            self.cli("export", target, str(backup))
            self.cli("import", target, str(backup), code=1)
            self.cli("delete", target, answer="y\n")
            self.cli("import", imported, str(backup))
            assert self.state(imported, "Stopped")
            self.cli("start", imported)
            assert self.exec(imported, "cat /home/sandbox/mas-proof") == "mas-roundtrip-data"
            self.exec(imported, '! command -v zstd')
            self.cli("new", target, "--image", host_image())
        with self.case("overwrite-confirmation"):
            sentinel = Path(self.workspace.name) / "overwrite.tar.gz"
            sentinel.write_bytes(b"unchanged")
            with self.terminal(["export", target, str(sentinel)]) as terminal:
                terminal.expect("Overwrite ")
                terminal.send("\n")
                terminal.finish()
            assert sentinel.read_bytes() == b"unchanged"
            with self.terminal(["export", target, str(sentinel)]) as terminal:
                terminal.expect("Overwrite ")
                terminal.send("\x1bOB\n")
                terminal.finish()
            assert sentinel.stat().st_size > 9
        with self.case("ownership-and-stop-all"):
            self.manager.lxd.command(["init", host_image(), "local:" + external])
            self.manager.lxd.command(["start", "local:" + external])
            self.wait("external running", lambda: self.state(external, "Running"))
            for action in ("start", "stop", "restart", "delete", "info", "enter"):
                self.cli(action, external, answer="y\n", code=1)
            self.cli("export", external, str(self.directory / "external.tar.gz"), code=1)
            self.cli("import", external, str(backup), code=1)
            assert external not in self.cli("list")
            self.cli("stop", "--all")
            assert self.state(target, "Stopped") and self.state(imported, "Stopped")
            assert self.state(external, "Running"), t("ownership_failed")
        with self.case("unmarked-import"):
            native_backup = Path(self.workspace.name)/'native-unmarked.tar.gz'
            self.manager.lxd.command(['config', 'unset', 'local:'+target, 'user.mas.managed'])
            assert not self.manager.managed(self.manager.find(target))
            self.manager._run_lxd_until_state('export', target, ['export', 'local:'+target, str(native_backup)], 'Stopped', require_marker=False)
            self.manager._run_lxd_until_state('delete', target, ['delete', 'local:'+target], 'Absent', require_marker=False)
            self.cli('import', target, str(native_backup))
            restored = self.manager.info(target)
            assert restored['config']['user.mas.managed'] == 'true' and restored['status'] == 'Stopped'
        with self.case("filesystems"):
            self.filesystems(target)
        with self.case("filesystem-recovery"):
            self.filesystem_recovery(target)
        with self.case("filesystem-menu"):
            self.filesystem_menu(target)
        with self.case("delete-confirmation"):
            with self.terminal(["delete", imported]) as terminal:
                terminal.expect("Delete container " + imported)
                terminal.send("\n")
                terminal.finish()
            assert self.state(imported, "Stopped")
            with self.terminal(["delete", imported]) as terminal:
                terminal.expect("Delete container " + imported)
                terminal.send("\x1b[B\n")
                terminal.finish()
            assert self.state(imported, "Absent")
            self.cli("delete", target, answer="y\n")
        with self.case("language-config"):
            assert self.cli("config", "get", "language").strip() == self.language
            self.cli("config", "set", "language", "zh_cn")
            assert "管理" in self.cli("--help")
            assert self.cli("config", "get", "language").strip() == "zh_cn"
            self.cli("config", "set", "language", "en_us")
            assert "Manage your" in self.cli("--help")
            self.cli("config", "set", "language", self.language)
        with self.case("tui"):
            self.tui()

    def security_fixture(self):
        target = self.target()
        self.cli('new', target)
        assert self.state(target, 'Stopped')
        self.cli('start', target)
        assert self.state(target, 'Running')
        self.isolation_runtime(target)

    def filesystems(self, target):
        self.cli('start', target)
        self.exec(target, "printf 'container secret' > /home/sandbox/mas-secret; chown sandbox:sandbox /home/sandbox/mas-secret; chmod 600 /home/sandbox/mas-secret")
        before = self.exec(target, "stat -c '%u:%g:%a' /home/sandbox/mas-secret")
        home = self.fs_root/target/'home/sandbox'
        self.cli('mountfs', target)
        with self.manager.filesystems.locked() as data:
            entry=self.manager.filesystems._entries(data,target)[0]
            assert (self.fs_state/entry['id']/'known_hosts').read_text().strip()
        assert home.joinpath('mas-secret').read_text() == 'container secret'
        self.windows_filesystem(home)
        home.joinpath('host-created').write_text('from host')
        assert self.exec(target, 'cat /home/sandbox/host-created') == 'from host'
        self.events.append(dict(action='filesystem-native-metadata', target=target, status='ok', existing=before.strip(), created=self.exec(target, "stat -c '%u:%g:%a' /home/sandbox/host-created").strip()))
        home.joinpath('host-created').unlink()
        assert self.exec(target, "stat -c '%u:%g:%a' /home/sandbox/mas-secret") == before
        self.cli('mountfs',target,'/var/log')
        paths_before = {e['path'] for e in self.manager.mountedfs(target)}
        self.cli('stop',target)
        assert self.state(target,'Stopped')
        assert {e['path'] for e in self.manager.mountedfs(target)} == paths_before
        assert home.joinpath('mas-secret').read_text() == 'container secret'
        self.cli('start',target)
        assert self.state(target,'Running')
        assert all(e['status'] == 'mounted' for e in self.manager.mountedfs(target))
        self.cli('restart', target)
        assert self.state(target, 'Running')
        entries = self.manager.mountedfs(target)
        assert {e['path'] for e in entries} == paths_before
        assert all(e['status'] == 'mounted' for e in entries)
        assert home.joinpath('mas-secret').read_text() == 'container secret'
        self.cli('unmountfs',target,'/var/log')
        self.cli('mountfs',target,code=1)
        self.cli('mountfs',target,'/home',code=1)
        self.cli('mountfs',target,'/var/log')
        listing=self.cli('mountedfs',target)
        assert '/home/sandbox' in listing and '/var/log' in listing
        self.cli('unmountfs',target,'/home/sandbox/child',code=1)
        assert home.is_mount()
        self.cli('unmountfs',target,'/var/log')
        self.cli('unmountfs',target)
        assert not self.fs_root.exists()
        self.cli('stop',target)
        self.cli('mountfs',target,'/')
        self.cli('start',target)
        assert self.state(target,'Running')
        self.cli('stop',target)
        assert self.state(target,'Stopped')
        self.cli('delete',target,answer='y',code=1)
        self.cli('unmountfs',target,'/var/log',code=1)
        assert self.fs_root.joinpath(target).is_mount()
        assert self.fs_root.joinpath(target,'etc/passwd').read_text()
        self.cli('unmountfs',target,'/')
        assert not self.fs_root.exists()
        # A pre-existing empty destination must survive refusal.
        home.mkdir(parents=True)
        self.cli('mountfs',target,code=1)
        assert home.is_dir() and not home.is_mount()
        home.rmdir();home.parent.rmdir();home.parent.parent.rmdir();self.fs_root.rmdir()
        for invalid in ('relative','/home/../etc','/var/run'):
            self.cli('mountfs',target,invalid,code=1)
        assert self.state(target,'Stopped')

    def gpu_menu(self, target):
        with self.terminal([]) as terminal:
            down, back = '\x1b[B', '\x1b[D'
            terminal.expect('my-ai-sandbox'); terminal.send('\n')
            terminal.expect_menu('Containers')
            names = [item['name'] for item in self.manager.list()]
            terminal.send(down * names.index(target) + '\n')
            terminal.expect('Container: ' + target); terminal.send(down * 8 + '\n')
            terminal.expect('GPU: Enabled'); terminal.send('\n')
            terminal.expect('Choose GPU access'); terminal.send(down + '\n')
            self.menu_result(terminal, 'Hardware options: ' + target)
            terminal.expect('GPU: Disabled'); terminal.send(back)
            terminal.expect('Container: ' + target); terminal.send(back)
            terminal.expect_menu('Containers'); terminal.send(back)
            terminal.expect('my-ai-sandbox'); terminal.send('\x1b[A\n'); terminal.finish()
        record = self.manager.gpu.record(self.manager.info(target))
        assert record is not None and not record['enabled']

    def gpu_test(self):
        from .gpu import KEY, CONF, PROFILE
        capability = self.manager.gpu.detect()
        self.gpu_results = {'capability': capability, 'compute': 'not_run'}
        if not capability['available']:
            self.gpu_results['reason'] = 'No supported discrete GPU on host'
            self.output.keep(t('gpu_test_unavailable'))
            return
        target = self.target()
        self.cli('new', target)
        initial = json.loads(self.cli('hardware', target))
        assert initial['enabled'] and initial['configured']
        assert initial['resources']['driver_paths'] == capability['driver_paths']
        self.gpu_results['resources'] = initial['resources']
        before = self.manager.info(target)
        assert before.get('expanded_config', before['config']).get('security.privileged', 'false') == 'false'
        self.cli('start', target)
        self.cli('hardware', target, 'gpu', 'off', code=1)
        script = files('tests').joinpath('gpu_compute.py').read_text()
        def compute():
            result = self.manager.lxd.command(['exec', 'local:' + target, '--',
                'runuser', '-u', 'sandbox', '--', 'python3', '-c', script])
            parsed = json.loads(result)
            assert parsed['computed'] == 42 and parsed['devices'] > 0
            return parsed
        self.gpu_results['first_compute'] = compute()
        if capability['backend'] == 'wsl-nvidia':
            # Observe real host driver loading independently of CTK/product discovery.
            host_probe = """import ctypes,json,pathlib
lib=ctypes.CDLL('/usr/lib/wsl/lib/libcuda.so.1')
assert lib.cuInit(0)==0, 'host CUDA initialization failed'
paths=set()
for line in pathlib.Path('/proc/self/maps').read_text().splitlines():
    fields=line.split(maxsplit=5)
    if len(fields)==6:
        path=pathlib.Path(fields[5])
        if str(path).startswith('/usr/lib/wsl/drivers/') and path.name=='libcuda.so.1.1':
            paths.add(str(path.parent))
assert paths, 'active host CUDA path unavailable'
print(json.dumps(sorted(paths)))
"""
            loaded = json.loads(subprocess.check_output([sys.executable, '-I', '-c', host_probe], text=True, timeout=self.timeout))
            assert loaded == initial['resources']['driver_paths'], ('host runtime differs from container mappings', loaded, initial['resources'])
            self.gpu_results['host_loaded_driver_paths'] = loaded
            self.exec(target, 'test -c /dev/dxg; test -r /usr/lib/wsl/lib/libcuda.so.1')
            self.manager.lxd.command(['exec', 'local:' + target, '--', 'runuser', '-l', 'sandbox', '-c',
                'test "$(command -v nvidia-smi)" = /usr/lib/wsl/lib/nvidia-smi && nvidia-smi -L'])
            self.manager.lxd.command(["exec", "local:" + target, "--", "python3", "-c", "import os; assert os.statvfs('/usr/lib/wsl/lib').f_flag & os.ST_RDONLY"])
            for path in initial['resources']['driver_paths']:
                self.manager.lxd.command(['exec', 'local:' + target, '--', 'python3', '-c', 'import os; assert os.statvfs(' + repr(path) + ').f_flag & os.ST_RDONLY'])
            # Test-only inventory demonstrates that inactive historical driver
            # directories are absent. Production discovery never scans them.
            candidates = {str(p.parent) for p in Path('/usr/lib/wsl/drivers').glob('*/libcuda.so.1.1')}
            excluded = sorted(candidates - set(capability['driver_paths']))
            for path in excluded:
                self.manager.lxd.command(['exec', 'local:' + target, '--', 'python3', '-c',
                    'import os; assert not os.path.exists(' + repr(path + '/libcuda.so.1.1') + ')'])
            self.gpu_results['driver_selection'] = dict(selected=capability['driver_paths'],
                                                        excluded=excluded)
        self.cli('stop', target)
        self.gpu_menu(target)
        for _ in range(2):
            disabled = json.loads(self.cli('hardware', target, 'gpu', 'off'))
            assert not disabled['enabled'] and not disabled['devices']
        assert self.manager.gpu.record(self.manager.info(target)) == disabled
        self.cli('start', target)
        self.gpu_off_access(target, initial, disabled)
        self.manager.lxd.command(["exec", "local:" + target, "--", "python3", "-c", 'import ctypes\ntry: lib=ctypes.CDLL("libcuda.so.1")\nexcept OSError: pass\nelse: assert lib.cuInit(0) != 0'])
        self.cli('stop', target)
        self.cli('hardware', target, 'gpu', 'on')
        self.cli('start', target)
        self.gpu_results['second_compute'] = compute()
        self.gpu_results['compute'] = 'passed'
        self.cli('stop', target)
        after = self.manager.info(target)
        assert {k:v for k,v in before.get('expanded_devices', before['devices']).items() if not k.startswith('mas-gpu')} == {k:v for k,v in after.get('expanded_devices', after['devices']).items() if not k.startswith('mas-gpu')}
        assert after['devices']['mas-gpu' if capability['backend'] == 'nvidia-cdi' else 'mas-gpu-dxg'] == before['devices']['mas-gpu' if capability['backend'] == 'nvidia-cdi' else 'mas-gpu-dxg']
        self.cli('delete', target, answer='y')

    def gpu_off_access(self, target, initial, disabled):
        """Verify only access changed by the GPU toggle; no full challenge."""
        info = self.manager.info(target)
        expanded = info.get('expanded_devices', info['devices'])
        assert all(name not in expanded for name in initial['resources']['devices']), expanded
        assert self.manager.gpu.record(info) == disabled
        from .gpu import CONF, PROFILE
        paths = [CONF, PROFILE, '/dev/dxg']
        paths += [path+'/libcuda.so.1.1' for path in initial['resources']['driver_paths']]
        mapped = [device['path'] for device in initial['resources']['devices'].values() if device.get('type') == 'disk']
        if initial['backend'] == 'wsl-nvidia':
            paths.append('/usr/lib/wsl/lib/libcuda.so.1')
        source = ('import os, glob; paths=' + repr(paths) +
                  '; assert not any(os.path.lexists(p) for p in paths), paths; '
                  'assert not glob.glob("/dev/nvidia[0-9]*"); '
                  'mapped=' + repr(mapped) + '; mounts={line.split()[4] for line in open("/proc/self/mountinfo")}; '
                  'assert not (set(mapped) & mounts), mapped')
        self.manager.lxd.command(['exec', 'local:'+target, '--', 'python3', '-c', source])

    def windows_filesystem(self, home):
        """Exercise the actual Windows UNC access route when WSL interop exists."""
        powershell = shutil.which('powershell.exe')
        if not os.environ.get('WSL_DISTRO_NAME') or not powershell or not shutil.which('wslpath'):
            self.events.append(dict(action='filesystem-windows-unc', status='not_run',
                                    reason='Windows interop is unavailable on this host'))
            return
        windows = subprocess.check_output(['wslpath', '-w', str(home)], text=True, timeout=self.timeout).strip()
        # Encoding is explicit: native Windows console defaults need not be UTF-8.
        script = """[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$ErrorActionPreference='Stop'
$path=WINDOWS_PATH
$step='list'
function Check-Content($file, $expected, $operation) {
    $actual=[IO.File]::ReadAllText($file)
    $bytes=[IO.File]::ReadAllBytes($file)
    @{step=$operation;path=$file;expected=$expected;observed=$actual;
      expected_length=$expected.Length;observed_length=$actual.Length;
      byte_length=$bytes.Length;bytes_base64=[Convert]::ToBase64String($bytes)} | ConvertTo-Json -Compress
    if ($actual -ne $expected) { throw ($operation+' mismatch') }
}
try {
    $entries=[IO.Directory]::GetFileSystemEntries($path)
    @{step=$step;entries=$entries} | ConvertTo-Json -Compress
    $step='read'
    Check-Content (Join-Path $path 'mas-secret') 'container secret' $step
    $file=Join-Path $path 'windows-created'
    $step='write'
    [IO.File]::WriteAllText($file,'from Windows')
    Check-Content $file 'from Windows' $step
    $step='edit'
    [IO.File]::AppendAllText($file,' edited')
    Check-Content $file 'from Windows edited' $step
    $step='delete'
    [IO.File]::Delete($file)
    $dir=Join-Path $path 'windows-directory'
    $step='mkdir'
    [IO.Directory]::CreateDirectory($dir) | Out-Null
    $step='rmdir'
    [IO.Directory]::Delete($dir)
    Write-Output 'WINDOWS_UNC_OK'
} catch {
    @{step=$step;error=$_.Exception.Message;exception=$_.Exception.GetType().FullName} | ConvertTo-Json -Compress
    exit 1
}
""".replace('WINDOWS_PATH', "'" + windows.replace("'", "''") + "'")
        try:
            result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-EncodedCommand',
                                     base64.b64encode(script.encode('utf-16le')).decode()],
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=self.timeout)
            stdout, stderr, code = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as exc:
            def decoded(value):
                return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
            stdout, stderr, code = decoded(exc.stdout), decoded(exc.stderr), None
        (self.directory/'windows-unc.stdout.log').write_text(stdout)
        (self.directory/'windows-unc.stderr.log').write_text(stderr)
        evidence = dict(action='filesystem-windows-unc', status='error', path=windows,
                        returncode=code, native_stdout=stdout, native_stderr=stderr,
                        operations=['list', 'read', 'create', 'edit', 'delete', 'mkdir', 'rmdir'], steps=[])
        for line in stdout.splitlines():
            if line.startswith('{'):
                evidence['steps'].append(json.loads(line))
        self.events.append(evidence)
        success = code == 0 and 'WINDOWS_UNC_OK' in stdout and not (home/'windows-created').exists() and not (home/'windows-directory').exists()
        if not success:
            evidence['linux'] = {}
            for name in ('mas-secret', 'windows-created', 'windows-directory'):
                try:
                    path = home/name
                    info = path.lstat()
                    item = dict(uid=info.st_uid, gid=info.st_gid, mode=oct(info.st_mode), size=info.st_size,
                                inode=info.st_ino, mtime_ns=info.st_mtime_ns)
                    if path.is_file():
                        item['bytes_hex'] = path.read_bytes()[:4096].hex()
                    evidence['linux'][name] = item
                except OSError as exc:
                    evidence['linux'][name] = {'error': str(exc)}
            raise AssertionError(t('windows_unc_failed', code=code, details=stdout + stderr))
        evidence['status'] = 'ok'

    def filesystem_recovery(self, target):
        self.cli('mountfs',target,'/var/log')
        fs=self.manager.filesystems
        with fs.locked() as data:
            entry=fs._entries(data,target)[0]
            os.kill(entry['sshfs']['pid'],signal.SIGTERM)
        self.wait('filesystem-disconnect',lambda: self.manager.mountedfs(target)[0]['status'] != 'mounted')
        self.cli('mountedfs',target)
        self.cli('unmountfs',target,'/var/log')
        assert not self.fs_root.exists()
        self.cli('mountfs',target,'/var/log')
        # Simulate CLI death between native helper spawn and PID publication.
        with fs.locked() as data:
            entry=fs._entries(data,target)[0]
            identities=[entry.pop(kind) for kind in ('listener','sshfs')]
            fs._save(data)
        self.cli('unmountfs',target,'/var/log')
        from .filesystems import alive
        assert not any(alive(identity) for identity in identities)
        assert not self.manager.mountedfs(target)
        # The original default mount survives a later account-home change.
        self.cli('start',target)
        self.cli('mountfs',target)
        try:
            self.exec(target, "mkdir -p /home/changed; sed -i '/^sandbox:/s|:/home/sandbox:|:/home/changed:|' /etc/passwd")
            self.cli('unmountfs',target)
        finally:
            self.exec(target, "sed -i '/^sandbox:/s|:/home/changed:|:/home/sandbox:|' /etc/passwd")
        assert not self.fs_root.exists()
        self.cli('stop',target)
        # External ownership changes must not prevent cleanup of our host mount.
        self.cli('mountfs',target,'/var/log')
        self.manager.lxd.command(['config','unset','local:'+target,MANAGED])
        try:
            assert '/var/log' in self.cli('mountedfs',target)
            self.cli('unmountfs',target,'/var/log')
            assert not self.manager.managed(self.manager.find(target))
        finally:
            self.manager.lxd.command(['config','set','local:'+target,MANAGED+'=true'])
        assert not self.fs_root.exists()

    def menu_result(self, terminal, parent, chinese=False):
        terminal.expect('操作结果' if chinese else 'Operation result')
        terminal.expect('返回' if chinese else 'Back')
        terminal.read()
        # The parent must not appear before the user explicitly returns.
        assert parent.encode() not in terminal.buffer[terminal.cursor:]
        terminal.send('\x1b[D')
        if parent == 'Containers':
            terminal.expect_menu(parent)
        else:
            terminal.expect(parent)

    def filesystem_menu(self, target):
        with self.terminal([]) as terminal:
            down='\x1b[B';back='\x1b[D';parent='Filesystem: '+target
            terminal.expect('my-ai-sandbox');terminal.send('\n')
            terminal.expect_menu('Containers')
            names=[item['name'] for item in self.manager.list()]
            terminal.send(down*names.index(target)+'\n')
            terminal.expect('Container: '+target)
            terminal.send(down*7+'\n');terminal.expect(parent)
            terminal.send(down+'\n')
            terminal.expect('Enter an absolute directory path inside the container (leave empty and press Enter to use the sandbox home directory):');terminal.send('/var/log\n')
            terminal.expect('Mounted at ')
            self.menu_result(terminal,parent)
            terminal.send('\x1b[A\n')
            terminal.expect(str(self.fs_root/target/'var/log'))
            self.menu_result(terminal,parent)
            terminal.send(down*2+'\n')
            terminal.expect('Select the container directory to unmount:');terminal.send('\x1b[A\n')
            terminal.expect('Completed.')
            self.menu_result(terminal,parent)
            terminal.send(back);terminal.expect('Container: '+target)
            terminal.send(back);terminal.expect_menu('Containers')
            terminal.send(back);terminal.expect('my-ai-sandbox')
            terminal.send('\x1b[A\n');terminal.finish()
        assert not self.manager.mountedfs(target) and not self.fs_root.exists()

    def dependencies(self, target):
        """Real privileged package installation, confined to this test container."""
        from .install import dependency_script
        script = dependency_script() + '\nmas_run_apt update && mas_run_apt install -y sshfs\n'
        path = Path(self.workspace.name)/'dependency-probe.sh'
        path.write_text(script)
        remote = '/tmp/mas-dependency-probe.sh'
        self.manager.lxd.command(['file', 'push', str(path), 'local:'+target+remote])
        # sandbox already has the ordinary mas passwordless-sudo setup.
        command = self.manager.lxd.prefix + ['exec', 'local:'+target, '--', 'su', '--login', 'sandbox', '-c', 'bash '+remote]
        terminal = Terminal(command, self.timeout, self.directory/'dependency-install.log',
            on_wait=lambda elapsed: self.output.progress(t('working', name=t('case_dependency-install'), elapsed=elapsed)))
        try:
            terminal.expect('Dependency preparation completed: apt-get install -y sshfs')
            terminal.finish()
        finally:
            terminal.close()
            self.output.diagnostics(terminal.buffer.decode(errors='replace'), '', failed=terminal.status != 0)
        assert self.exec(target, 'command -v sshfs').strip()
        versions = self.exec(target, 'sudo --version; apt-get --version')
        self.events.append(dict(action='dependency-install', target=target, status='ok', versions=versions))

    def network(self, target):
        try:
            self.exec(target, "python3 -c \"import urllib.request; urllib.request.urlopen('https://ubuntu.com',timeout=30).read(1)\"")
            return True
        except Error as exc:
            self.events.append(dict(action="network-probe", target=target, status="warning", error=str(exc)))
            self.output.keep(t("network_retry", error=exc))
            return False

    def tui(self):
        target, imported = self.target(), self.target()
        backup = Path(self.workspace.name) / "tui-backup.tar.gz"
        with self.terminal([]) as terminal:
            def send(keys, expected):
                terminal.send(keys)
                if expected == 'Containers':
                    terminal.expect_menu(expected)
                else:
                    terminal.expect(expected)
            def result(parent, chinese=False):
                self.menu_result(terminal,parent,chinese)
            down, up, back = "\x1b[B", "\x1bOA", "\x1b[D"
            terminal.expect("my-ai-sandbox")
            send(down * 4 + "\n", "mas Preferences")
            send("\n", "Select interface language / 请选择界面语言")
            terminal.send("\x1b");result("mas Preferences")
            send("\n", "Select interface language / 请选择界面语言")
            terminal.send(up + "\n");result("mas 选项",True)
            assert self.cli("config", "get", "language").strip() == 'zh_cn'
            send("\n", "请选择界面语言 / Select interface language")
            terminal.send(down + "\n");result("mas Preferences")
            send(back, "my-ai-sandbox")
            send(up * 4 + "\x1b[C", "No managed containers.")
            send(back, "my-ai-sandbox")
            send(down + "\n", "Enter the container name (")
            terminal.send("\x1b");result("my-ai-sandbox")
            send("\n", "Enter the container name (")
            send(target + "\n", "Choose an image version (leave empty and press Enter to use the host Ubuntu version):")
            terminal.send("\n")
            self.wait("TUI new", lambda: self.state(target, "Stopped"), terminal)
            result("my-ai-sandbox")
            send(up + "\n", "Containers")
            send("\n", "Container: " + target)
            send("\n", "Name: " + target)
            terminal.expect("State: Stopped");terminal.expect("GPU configuration:")
            send("\n", '\"status\": \"Stopped\"')
            result("Info: " + target)
            send(back, "Container: " + target)
            terminal.send(down + "\n")
            self.wait("TUI start", lambda: self.state(target, "Running"), terminal)
            result("Container: " + target)
            terminal.send(down * 2 + "\n")
            self.wait("TUI stop", lambda: self.state(target, "Stopped"), terminal)
            result("Container: " + target)
            send(down * 2 + "\n", "Enter the host destination path for the backup file:")
            terminal.send(str(backup) + "\n")
            self.wait("TUI export", backup.exists, terminal)
            result("Container: " + target)
            send("\n", "Enter the host destination path for the backup file:")
            send(str(backup) + "\n", "Overwrite ")
            send("\n", "Cancelled.");result("Container: " + target)
            send(down + "\n", "Delete container " + target)
            send("\n", "Cancelled.");result("Container: " + target)
            assert self.state(target, 'Stopped')
            send("\n", "Delete container " + target)
            terminal.send(down + "\n")
            self.wait("TUI delete", lambda: self.state(target, "Absent"), terminal)
            result("Containers")
            send(back, "my-ai-sandbox")
            send(down * 2 + "\n", "Enter the name for the imported container (")
            send(imported + "\n", "Enter the host path of the backup file to import:")
            terminal.send(str(backup) + "\n")
            self.wait("TUI import", lambda: self.state(imported, "Stopped"), terminal)
            result("my-ai-sandbox")
            send(up * 2 + "\n", "Containers")
            send("\n", "Container: " + imported)
            terminal.send(down + "\n")
            self.wait("TUI imported start", lambda: self.state(imported, "Running"), terminal)
            result("Container: " + imported)
            extra = self.target()
            self.cli('new', extra)
            send(back, "Containers")
            names = [item['name'] for item in self.manager.list()]
            terminal.send(down * (len(names)-names.index(imported)) + "\n")
            self.wait("TUI stop all", lambda: self.state(imported, "Stopped"), terminal)
            result("Containers")
            send(back, "my-ai-sandbox")
            terminal.send(up + "\n");terminal.finish()
            self.cli('delete', extra, '--yes')
            for forbidden in (b'\x1b[?1049', b'\x1b[?1047', b'\x1b[?47', b'\x1b[2J', b'\x1b[3J', b'\x1b[H'):
                assert forbidden not in terminal.buffer, repr(forbidden)
            assert b'"status": "Stopped"' in terminal.buffer
            assert b'[ok] start ' in terminal.buffer
        for choice in ('exit', 'stop', 'restart', 'menu', 'escape'):
            with self.terminal([]) as terminal:
                terminal.expect('my-ai-sandbox'); terminal.send('\n')
                terminal.expect_menu('Containers'); terminal.send('\n')
                terminal.expect('Container: ' + imported); terminal.send(down * 2 + '\n')
                self.check_shell(terminal)
                boot = self.exec(imported, 'cat /proc/sys/kernel/random/boot_id')
                terminal.send('exit\n'); terminal.expect('Container terminal finished: ' + imported)
                after_question = terminal.cursor
                keys = {'exit': '\n', 'stop': down + '\n', 'restart': up * 2 + '\n',
                        'menu': up + '\n', 'escape': '\x1b'}
                terminal.send(keys[choice])
                if choice == 'menu':
                    terminal.expect('Container: ' + imported)
                    terminal.send(back); terminal.expect_menu('Containers')
                    terminal.send(back); terminal.expect('my-ai-sandbox')
                    terminal.send(up + '\n')
                terminal.finish()
                assert b'Operation result' not in terminal.buffer[after_question:]
                if choice != 'menu':
                    assert ('Container: ' + imported).encode() not in terminal.buffer[after_question:]
                assert self.state(imported, 'Stopped' if choice == 'stop' else 'Running')
                if choice != 'stop':
                    current_boot = self.exec(imported, 'cat /proc/sys/kernel/random/boot_id')
                    assert (current_boot != boot) == (choice == 'restart')


    def cleanup(self):
        self.output.progress(t("working", name=t("cleanup_stage"), elapsed=0))
        try:
            self.workspace.cleanup()
        except OSError as exc:
            self.cleanup_errors.append(t("backup_cleanup", error=exc))
        if not self.created_project:
            return
        try:
            from .imports import Imports
            from .isolation import Isolation
            owners = {e['owner']['id']: e['owner'] for e in self.events
                      if e.get('phase') == 'staging-created'}
            projects = {p['name'] for p in Isolation.list_objects(self.host,
                ['project','list','local:','--format=json'])} if owners else set()
            for owner in owners.values():
                if owner['project'] in projects:
                    Imports.cleanup(self.manager, owner)
        except (Error, OSError) as exc:
            self.cleanup_errors.append(str(exc))
        for target in self.targets:
            try:
                for entry in self.manager.mountedfs(target):
                    self.manager.unmountfs(target, entry["path"])
                item = self.manager.find(target)
                if item:
                    if item["status"] != "Stopped":
                        self.manager._run_lxd_until_state("cleanup-stop", target, ["stop", "local:" + target,
                                                "--timeout", str(self.timeout)], "Stopped", require_marker=False)
                    self.manager._run_lxd_until_state("cleanup-delete", target, ["delete", "local:" + target],
                                            "Absent", require_marker=False)
            except Exception as exc:
                self.cleanup_errors.append(f"{target}: {exc}")
        for target in self.legacy_targets:
            try:
                item = self.manager.legacy.find(target)
                if item:
                    if item.get('config', {}).get('user.mas.test.run') != self.project:
                        raise Error(t('legacy_cleanup_conflict', target=target))
                    if item['status'] != 'Stopped':
                        self.manager.legacy._run_lxd_until_state('cleanup-stop',target,
                            ['stop','local:'+target,'--timeout',str(self.timeout)],'Stopped',require_marker=False)
                    self.manager.legacy._run_lxd_until_state('cleanup-delete',target,
                        ['delete','local:'+target],'Absent',require_marker=False)
            except (Error, OSError) as exc:
                self.cleanup_errors.append('default/' + target + ': ' + str(exc))
        for name in self.legacy_profiles:
            try:
                from .isolation import Isolation
                policy = Isolation(self.manager.legacy)
                item, etag, endpoint = policy.resource('profiles', name)
                if item['config'].get('user.mas.test.run') != self.project:
                    raise Error(t('legacy_cleanup_conflict', target=name))
                body, _ = self.host.configuration.request('DELETE',endpoint,etag=etag)
                policy.sync_result(body)
            except (Error, OSError) as exc:
                self.cleanup_errors.append('default/profile/' + name + ': ' + str(exc))
        try:
            from .isolation import PROFILE
            self.manager.isolation.check()
            _, etag, endpoint = self.manager.isolation.resource('profiles', PROFILE)
            body, _ = self.manager.lxd.configuration.request('DELETE', endpoint, etag=etag)
            self.manager.isolation.sync_result(body)
            self.host.command(["project", "delete", "local:" + self.project])
        except Error as exc:
            self.cleanup_errors.append(str(exc))

    def save(self):
        (self.directory / "report.json").write_text(json.dumps({
            "version": __version__, "platform": platform.platform(),
            "product": str(self.product) if self.product else "source checkout",
            "product_sha256": hashlib.sha256(self.product.read_bytes()).hexdigest() if self.product else None,
            "os_release": Path("/etc/os-release").read_text(), "python": sys.version,
            "project": self.project, "targets": self.targets, "cases": self.results,
            "events": self.events, "cleanup_errors": self.cleanup_errors,
            "unit_tests": self.unit_results, "gpu": self.gpu_results,
            'isolation': self.isolation_results, 'legacy_targets': self.legacy_targets,
            'guest_boundary': getattr(self, 'guest_reports', []),
            'legacy_profiles': self.legacy_profiles,
            "elapsed": time.monotonic() - self.started,
        }, indent=2))


def install_and_test(args):
    """Only the tester orchestrates installation followed by verification."""
    from .install import install_file, group_refresh_required, refreshed_command
    try:
        version = subprocess.check_output([sys.executable, str(args.install), "--version"], text=True, timeout=600).strip()
        if version != __version__:
            raise Error(t("installer_mismatch"))
        code = subprocess.call([sys.executable, str(args.install), "--product", str(args.product)])
        if code:
            return code
        tester = Path.home() / ".local/bin/mas-test"
        install_file(Path(sys.argv[0]).resolve(), tester)
        print(t("install_stage"), flush=True)
        command = [sys.executable, str(tester), "--product", str(Path.home() / ".local/bin/mas"),
                   "--timeout", str(args.timeout), "--output", str(args.output.absolute())]
        if group_refresh_required():
            command = refreshed_command(command)
        return subprocess.call(command)
    except (Error, OSError, subprocess.SubprocessError) as exc:
        print(t("install_failed", error=exc), file=sys.stderr)
        return 1


def main(argv=None):
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] == '--security':
        from .security_testing import main as security_main
        return security_main(args_list[1:])
    parser = Parser(description=t('help_test'))
    parser.add_argument("--output", type=Path, default=Path("test-results") / time.strftime("%Y%m%d-%H%M%S"), help=t("help_output"))
    parser.add_argument("--timeout", type=int, default=600, help=t("help_timeout"))
    parser.add_argument("--install", type=Path, help=t("help_test_install"))
    parser.add_argument("--product", type=Path, help=t('help_product'))
    args = parser.parse_args(argv)
    if args.timeout < 300:
        parser.error(t('timeout_minimum'))
    if not __debug__:
        parser.error(t('test_optimization'))
    global PRODUCT_UNDER_TEST
    if args.install:
        if args.product is None:
            parser.error(t("product_required"))
        return install_and_test(args)
    if args.product is None and zipfile.is_zipfile(sys.argv[0]):
        args.product = Path.home() / ".local/bin/mas"
        if not args.product.is_file():
            parser.error(t('product_required'))
    PRODUCT_UNDER_TEST = args.product
    try:
        suite = Suite(args.output.absolute(), args.timeout, args.product)
    except (Error, OSError) as exc:
        print(t("test_start_error", error=exc), file=sys.stderr)
        return 1
    success = False
    try:
        suite.run()
        success = True
    except (Exception, KeyboardInterrupt):
        suite.output.clear()
        traceback.print_exc()
    finally:
        try:
            suite.cleanup()
        except Exception as exc:
            suite.cleanup_errors.append(str(exc))
        try:
            suite.save()
        except OSError as exc:
            success = False
            suite.output.keep(t("error", error=exc))
    suite.output.clear()
    for error in suite.cleanup_errors:
        suite.output.keep(t("cleanup_failed", error=error))
    if not suite.cleanup_errors:
        suite.output.result(t("cleanup_ok"), passed=True)
    counts = {status: sum(item["status"] == status for item in suite.results.values())
              for status in ("passed", "failed", "not_run")}
    suite.output.keep(t("final_summary", **counts, elapsed=time.monotonic()-suite.started))
    suite.output.keep(t("report", path=suite.directory / "report.json"))
    return 0 if success and not suite.cleanup_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
