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
import select
import signal
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
from .core import Error, LXD, Manager, MANAGED, host_image

from .i18n import t, Parser, catalog, progress_text


PRODUCT_UNDER_TEST = None

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
    def __init__(self, command, timeout, transcript, on_wait=None):
        self.timeout = timeout
        self.on_wait = on_wait
        self.started = self.last_update = time.monotonic()
        self.buffer = b""
        self.cursor = 0
        self.status = None
        self.transcript = transcript.open("wb")
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.environ["TERM"] = "xterm"
            os.execvpe(command[0], command, os.environ)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 200, 0, 0))

    def read(self):
        now = time.monotonic()
        if self.on_wait and now - self.last_update >= 1:
            self.on_wait(now - self.started)
            self.last_update = now
        if select.select([self.fd], [], [], 0.1)[0]:
            try:
                chunk = os.read(self.fd, 65536)
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                chunk = b""
            self.buffer += chunk
            self.transcript.write(chunk)
            self.transcript.flush()
        if self.status is None:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.status = os.waitstatus_to_exitcode(status)

    def send(self, value):
        os.write(self.fd, value.encode())

    def expect(self, text):
        expected = text.encode()
        start = time.monotonic()
        while time.monotonic() - start < self.timeout:
            self.read()
            index = self.buffer.find(expected, self.cursor)
            if index != -1:
                self.cursor = index + len(expected)
                return
            if self.status is not None:
                raise AssertionError(t("pty_exited", status=self.status, text=text, buffer=self.buffer[-2000:]))
        raise AssertionError(t("pty_timeout", timeout=self.timeout, text=text, buffer=self.buffer[-2000:]))

    def finish(self):
        start = time.monotonic()
        while self.status is None and time.monotonic() - start < self.timeout:
            self.read()
        if self.status != 0:
            raise AssertionError(t("pty_status", status=self.status, buffer=self.buffer[-2000:]))

    def close(self):
        if self.status is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.pid, signal.SIGTERM)
            os.waitpid(self.pid, 0)
        os.close(self.fd)
        self.transcript.close()


class Suite:
    CASES = ["unit", "new-default", "missing-image", "list-info", "start-user-network", "running-guards",
             "enter-running-default-exit", "enter-stopped-stop-exit", "export-import",
             "overwrite-confirmation", "ownership-and-stop-all", "delete-confirmation", "language-config", "tui", "invalid-inputs", "lifecycle-repeat", "unmarked-import", "filesystems", "filesystem-recovery", "filesystem-menu"]

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
        self.host = LXD(timeout=timeout)
        self.fs_root = self.directory / "mounts"
        self.fs_state = self.directory / "mount-state"
        self.manager = Manager(LXD(project=self.project, timeout=timeout), self.report, self.fs_root, self.fs_state)
        self.created_project = False
        self.targets = []
        self.events = []
        self.results = {case: {"status": "not_run"} for case in self.CASES}
        self.cleanup_errors = []
        self.counter = 0
        self.unit_results = None

    def report(self, event):
        self.events.append(event)
        self.output.progress(progress_text(event))
        self.output.diagnostics(event.get("native_stdout", ""), event.get("native_stderr", ""))

    @contextlib.contextmanager
    def case(self, name):
        start = time.monotonic()
        self.current_case = name
        title = t("case_" + name)
        self.output.progress(t("working", name=title, elapsed=0))
        try:
            yield
        except BaseException as exc:
            self.results[name] = {"status": "failed", "elapsed": time.monotonic() - start, "error": str(exc)}
            self.output.keep(t("stage_failed", name=title, elapsed=time.monotonic()-start, error=exc))
            raise
        else:
            self.results[name] = {"status": "passed", "elapsed": time.monotonic() - start}
            self.output.keep(t("test_pass", name=title, elapsed=self.results[name]["elapsed"]))

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
                  "raise SystemExit(main(manager=Manager(LXD(project=" + repr(self.project) +
                  ",timeout=" + str(self.timeout) + ",diagnostic=progress.output.keep),report=report,fs_root=" + repr(str(self.fs_root)) + ",fs_state=" + repr(str(self.fs_state)) + "))) ")
        return [sys.executable, "-c", source, *args]

    def read_events(self, path, diagnostics=False):
        if path.exists():
            events = [json.loads(line) for line in path.read_text().splitlines() if line]
            self.events.extend(events)
            if diagnostics:
                for event in events:
                    self.output.diagnostics(event.get("native_stdout", ""), event.get("native_stderr", ""))

    def cli(self, *args, answer=None, code=0):
        start = time.monotonic()
        self.counter += 1
        arguments = list(args)
        if answer is not None and args[0] in ('delete', 'export', 'enter'):
            arguments.append('--yes' if answer.strip().lower() in ('y', 'yes') else '--no')
        command = self.command(arguments)
        event_path = self.event_path
        stdout_path = self.directory / f"cli-{self.counter}.stdout.log"
        stderr_path = self.directory / f"cli-{self.counter}.stderr.log"
        action = catalog(self.language).get("action_" + args[0], args[0])
        with stdout_path.open("w+") as stdout, stderr_path.open("w+") as stderr:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, text=True)
            try:
                try:
                    process.stdin.write(answer or "")
                    process.stdin.close()
                except BrokenPipeError:
                    pass
                while process.poll() is None:
                    elapsed = time.monotonic() - start
                    if elapsed >= self.timeout * 3:
                        raise Error(t("wait_timeout", label=" ".join(args), timeout=self.timeout*3))
                    self.output.progress(t("working", name=action + " " + " ".join(args[1:]), elapsed=elapsed))
                    time.sleep(1)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                self.read_events(event_path)
                stdout.seek(0)
                stderr.seek(0)
                out, err = stdout.read(), stderr.read()
                if process.returncode != 0 and code != 0:
                    self.output.keep(t("expected_error", command=" ".join(args)))
                self.output.diagnostics(out, err, failed=process.returncode != 0)
        if process.returncode != code:
            raise AssertionError(t("cli_failed", args=args, expected=code, actual=process.returncode, stdout=out, stderr=err))
        return out

    @contextlib.contextmanager
    def terminal(self, args):
        self.counter += 1
        # English UI fixture expectations are isolated from user-facing output.
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config_home)}):
            previous = config.get("language")
            config.set_value("language", "en_us")
        terminal = Terminal(self.command(args), self.timeout, self.directory / f"terminal-{self.counter}.log",
                            on_wait=lambda elapsed: self.output.progress(t("working", name=t("case_" + self.current_case), elapsed=elapsed)))
        event_path = self.event_path
        try:
            yield terminal
        finally:
            terminal.close()
            self.read_events(event_path, diagnostics=True)
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config_home)}):
                config.set_value("language", previous)

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

    def exec(self, target, script):
        return self.manager.lxd.command(["exec", "local:" + target, "--", "/bin/sh", "-c", script])

    def check_shell(self, terminal):
        # Split literal strings so terminal input echo cannot satisfy the output match.
        terminal.send("printf 'MAS_%s\\n' SHELL; id -un; sudo -n id -u\n")
        terminal.expect("MAS_SHELL\r\n")
        terminal.expect("sandbox\r\n")
        terminal.expect("0\r\n")

    def run(self):
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
            self.host.command(["project", "create", "local:" + self.project,
                               "-c", "features.images=false", "-c", "features.profiles=false"])
            self.created_project = True
            self.cli("new", target)
            assert self.state(target, "Stopped")
            assert self.manager.info(target)["config"]["image.version"] == host_image().split(":")[1]
        with self.case("missing-image"):
            missing = self.target()
            self.cli("new", missing, "--image", "ubuntu:mas-missing-" + uuid.uuid4().hex, code=1)
            assert self.state(missing, "Absent"), t("image_unexpected")
        with self.case("list-info"):
            assert target in self.cli("list")
            assert json.loads(self.cli("info", target))["status"] == "Stopped"
            self.cli("new", target, code=1)
        with self.case("invalid-inputs"):
            missing = self.target()
            for action in ('start', 'stop', 'info', 'delete', 'enter'):
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
        with self.case("lifecycle-repeat"):
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
            finally:
                self.exec(target, 'usermod --shell /bin/bash sandbox')
        with self.case("running-guards"):
            self.cli("delete", target, answer="y\n", code=1)
            self.cli("export", target, str(self.directory / "forbidden.tar.gz"), code=1)
            assert self.state(target, "Running")
        with self.case("enter-running-default-exit"):
            with self.terminal(["enter", target]) as terminal:
                terminal.expect("sandbox@")
                self.check_shell(terminal)
                terminal.send("exit\n")
                terminal.expect(f"Stop container {target}?")
                terminal.send("\n")
                terminal.finish()
            assert self.state(target, "Running")
        with self.case("enter-stopped-stop-exit"):
            self.cli("stop", target)
            with self.terminal(["enter", target]) as terminal:
                terminal.expect("sandbox@")
                self.check_shell(terminal)
                terminal.send("exit\n")
                terminal.expect(f"Stop container {target}?")
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
            for action in ("start", "stop", "delete", "info", "enter"):
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
try {
    $entries=[IO.Directory]::GetFileSystemEntries($path)
    if ([IO.File]::ReadAllText((Join-Path $path 'mas-secret')) -ne 'container secret') { throw 'Read mismatch' }
    $file=Join-Path $path 'windows-created'
    [IO.File]::WriteAllText($file,'from Windows')
    if ([IO.File]::ReadAllText($file) -ne 'from Windows') { throw 'Write mismatch' }
    [IO.File]::AppendAllText($file,' edited')
    if ([IO.File]::ReadAllText($file) -ne 'from Windows edited') { throw 'Edit mismatch' }
    [IO.File]::Delete($file)
    $dir=Join-Path $path 'windows-directory'
    [IO.Directory]::CreateDirectory($dir) | Out-Null
    [IO.Directory]::Delete($dir)
    Write-Output 'WINDOWS_UNC_OK'
} catch { Write-Output $_.Exception.Message; exit 1 }
""".replace('WINDOWS_PATH', "'" + windows.replace("'", "''") + "'")
        result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-EncodedCommand',
                                 base64.b64encode(script.encode('utf-16le')).decode()],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=self.timeout)
        assert result.returncode == 0 and 'WINDOWS_UNC_OK' in result.stdout, result.stdout + result.stderr
        assert not (home/'windows-created').exists() and not (home/'windows-directory').exists()
        self.events.append(dict(action='filesystem-windows-unc', status='ok', path=windows,
                                operations=['list', 'read', 'create', 'edit', 'delete', 'mkdir', 'rmdir']))

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
        terminal.expect(parent)

    def filesystem_menu(self, target):
        with self.terminal([]) as terminal:
            down='\x1b[B';back='\x1b[D';parent='Container: '+target
            terminal.expect('my-ai-sandbox');terminal.send('\n')
            terminal.expect('Container management');terminal.send('\n')
            terminal.expect('Containers')
            names=[item['name'] for item in self.manager.list()]
            terminal.send(down*names.index(target)+'\n')
            terminal.expect(parent)
            terminal.send(down*7+'\n')
            terminal.expect('Enter a directory path inside the container (leave empty and press Enter to use the sandbox home directory):');terminal.send('/var/log\n')
            terminal.expect('Mounted at ')
            self.menu_result(terminal,parent)
            terminal.send('\x1b[A\n')
            terminal.expect(str(self.fs_root/target/'var/log'))
            self.menu_result(terminal,parent)
            terminal.send(down*2+'\n')
            terminal.expect('Select the container directory to unmount:');terminal.send('\x1b[A\n')
            terminal.expect('Completed.')
            self.menu_result(terminal,parent)
            terminal.send(back);terminal.expect('Containers')
            terminal.send(back);terminal.expect('Container management')
            terminal.send(back);terminal.expect('my-ai-sandbox')
            terminal.send(down*2+'\n');terminal.finish()
        assert not self.manager.mountedfs(target) and not self.fs_root.exists()

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
                terminal.send(keys);terminal.expect(expected)
            def result(parent, chinese=False):
                self.menu_result(terminal,parent,chinese)
            down, up, back = "\x1b[B", "\x1bOA", "\x1b[D"
            terminal.expect("my-ai-sandbox")
            send(down + "\n", "Settings")
            send("\n", "Select interface language / 请选择界面语言")
            terminal.send("\x1b");result("Settings")
            send("\n", "Select interface language / 请选择界面语言")
            terminal.send(up + "\n");result("设置",True)
            assert self.cli("config", "get", "language").strip() == 'zh_cn'
            send("\n", "请选择界面语言 / Select interface language")
            terminal.send(down + "\n");result("Settings")
            send(back, "my-ai-sandbox")
            send(up + "\x1b[C", "Container management")
            send("\n", "No managed containers.")
            send(back, "Container management")
            send(down + "\n", "Enter the container name:")
            terminal.send("\x1b");result("Container management")
            send("\n", "Enter the container name:")
            send(target + "\n", "Choose an image version (leave empty and press Enter to use the host Ubuntu version):")
            terminal.send("\n")
            self.wait("TUI new", lambda: self.state(target, "Stopped"), terminal)
            result("Container management")
            send(up + "\n", "Containers")
            send("\n", "Container: " + target)
            send("\n", '\"status\": \"Stopped\"')
            result("Container: " + target)
            terminal.send(down + "\n")
            self.wait("TUI start", lambda: self.state(target, "Running"), terminal)
            result("Container: " + target)
            terminal.send(down * 2 + "\n")
            self.wait("TUI stop", lambda: self.state(target, "Stopped"), terminal)
            result("Container: " + target)
            send(down + "\n", "Enter the destination path for the backup file:")
            terminal.send(str(backup) + "\n")
            self.wait("TUI export", backup.exists, terminal)
            result("Container: " + target)
            send("\n", "Enter the destination path for the backup file:")
            send(str(backup) + "\n", "Overwrite ")
            send("\n", "Cancelled.");result("Container: " + target)
            send(down + "\n", "Delete container " + target)
            send("\n", "Cancelled.");result("Container: " + target)
            assert self.state(target, 'Stopped')
            send("\n", "Delete container " + target)
            terminal.send(down + "\n")
            self.wait("TUI delete", lambda: self.state(target, "Absent"), terminal)
            result("Containers")
            send(back, "Container management")
            send(down * 2 + "\n", "Enter the name for the imported container:")
            send(imported + "\n", "Enter the path of the backup file to import:")
            terminal.send(str(backup) + "\n")
            self.wait("TUI import", lambda: self.state(imported, "Stopped"), terminal)
            result("Container management")
            send(up * 2 + "\n", "Containers")
            send("\n", "Container: " + imported)
            terminal.send(down + "\n")
            self.wait("TUI imported start", lambda: self.state(imported, "Running"), terminal)
            result("Container: " + imported)
            send(back, "Containers")
            send(back, "Container management")
            terminal.send(down * 3 + "\n")
            self.wait("TUI stop all", lambda: self.state(imported, "Stopped"), terminal)
            result("Container management")
            send(back, "my-ai-sandbox")
            terminal.send(down * 2 + "\n");terminal.finish()
            for forbidden in (b'\x1b[?1049', b'\x1b[?1047', b'\x1b[?47', b'\x1b[2J', b'\x1b[3J', b'\x1b[H'):
                assert forbidden not in terminal.buffer, repr(forbidden)
            assert b'"status": "Stopped"' in terminal.buffer
            assert b'[ok] start ' in terminal.buffer
        for stop in (False, True, None):
            with self.terminal([]) as terminal:
                terminal.expect('my-ai-sandbox'); terminal.send('\n')
                terminal.expect('Container management'); terminal.send('\n')
                terminal.expect('Containers'); terminal.send('\n')
                terminal.expect('Container: ' + imported); terminal.send(down * 2 + '\n')
                terminal.expect('sandbox@'); self.check_shell(terminal)
                terminal.send('exit\n'); terminal.expect(f'Stop container {imported}?')
                after_question = terminal.cursor
                terminal.send('\x1b' if stop is None else (down if stop else '') + '\n')
                terminal.finish()
                assert b'Operation result' not in terminal.buffer[after_question:]
                assert ('Container: ' + imported).encode() not in terminal.buffer[after_question:]
                assert self.state(imported, 'Stopped' if stop else 'Running')


    def cleanup(self):
        self.output.progress(t("working", name=t("cleanup_stage"), elapsed=0))
        try:
            self.workspace.cleanup()
        except OSError as exc:
            self.cleanup_errors.append(t("backup_cleanup", error=exc))
        if not self.created_project:
            return
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
        try:
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
            "unit_tests": self.unit_results,
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
    parser = Parser(description=t('help_test'))
    parser.add_argument("--output", type=Path, default=Path("test-results") / time.strftime("%Y%m%d-%H%M%S"), help=t("help_output"))
    parser.add_argument("--timeout", type=int, default=600, help=t("help_timeout"))
    parser.add_argument("--install", type=Path, help=t("help_test_install"))
    parser.add_argument("--product", type=Path, help=t('help_product'))
    args = parser.parse_args(argv)
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
        suite.output.keep(t("cleanup_ok"))
    counts = {status: sum(item["status"] == status for item in suite.results.values())
              for status in ("passed", "failed", "not_run")}
    suite.output.keep(t("final_summary", **counts, elapsed=time.monotonic()-suite.started))
    suite.output.keep(t("report", path=suite.directory / "report.json"))
    return 0 if success and not suite.cleanup_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
