"""Shared operations. Only this module implements container lifecycle behavior."""

import json

import os
from functools import cached_property
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

from .i18n import t, state
from .diagnostics import cleanup_scope, notify, emit_native, failure_text

MANAGED = "user.mas.managed"
DEFAULT_TIMEOUT = 600

CLOUD_INIT_WAIT = r'''
if command -v cloud-init >/dev/null 2>&1; then
    if cloud-init status --wait; then
        :
    else
        code=$?
        if test "$code" -ne 2; then
            tail -n 60 /var/log/cloud-init-output.log >&2 || true
            exit "$code"
        fi
    fi
fi
'''

USER_SETUP = r'''set -eu
''' + CLOUD_INIT_WAIT + r'''
if ! command -v sudo >/dev/null 2>&1; then
    if test -f /var/lib/mas/development.json; then
        echo 'sudo was removed from this prepared container; install it explicitly to restore the required sandbox sudo capability' >&2
        exit 1
    fi
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y sudo
fi
if ! id sandbox >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash sandbox
fi
test "$(id -u sandbox)" -ne 0
install -d -m 0750 /etc/sudoers.d
umask 077
printf '%s\n' 'sandbox ALL=(ALL:ALL) NOPASSWD: ALL' > /etc/sudoers.d/90-mas-sandbox.tmp
visudo -cf /etc/sudoers.d/90-mas-sandbox.tmp
chmod 0440 /etc/sudoers.d/90-mas-sandbox.tmp
mv /etc/sudoers.d/90-mas-sandbox.tmp /etc/sudoers.d/90-mas-sandbox
su --login sandbox -c 'sudo -n /usr/bin/true'
'''


class Error(RuntimeError):
    """An actionable operation failure."""

class ShellExitError(Error):
    """Post-terminal failure, with the explicitly chosen return destination."""
    def __init__(self, message, *, return_to_menu=False):
        super().__init__(message)
        self.return_to_menu = return_to_menu



def read_output(stream):
    # pread leaves the shared file offset unchanged while the child is writing.
    return os.pread(stream.fileno(), os.fstat(stream.fileno()).st_size, 0).decode("utf-8", errors="replace")


def finish_client(process, timeout):
    """Terminate/reap our client within a bound, not the daemon's operation."""
    if process is None:
        return
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise Error(t('client_cleanup_timeout', pid=process.pid, timeout=timeout)) from exc


def confirm(message, ask=None):
    """One confirmation policy, independent of CLI or TUI presentation."""
    try:
        if ask is None:
            return False
        answer = ask(message)
        return answer if isinstance(answer, bool) else answer.strip().lower() in ("y", "yes")
    except EOFError:
        return False


def host_image():
    """WSL exposes its Ubuntu release in the same file as native Ubuntu."""
    import shlex
    values = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = "".join(shlex.split(value))
    if values.get("ID") != "ubuntu" or not re.fullmatch(r"\d+\.\d+", values.get("VERSION_ID", "")):
        raise Error(t('host_image_error'))
    return "ubuntu:" + values["VERSION_ID"]


def validate_target(target):
    if not re.fullmatch(r"[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", target):
        raise Error(t('invalid_target'))


class LXD:
    def __init__(self, project="default", timeout=DEFAULT_TIMEOUT, diagnostic=None):
        if timeout < 300:
            raise Error(t('timeout_minimum'))
        executable = shutil.which("lxc")
        if not executable and Path("/snap/bin/lxc").exists():
            executable = "/snap/bin/lxc"
        if not executable:
            raise Error(t('lxd_missing'))
        self.prefix = [executable, "--project", project]
        self.project = project
        self.diagnostic = diagnostic
        self.timeout = timeout

    def command(self, args, timeout=None, input_data=None):
        try:
            prefix = [self.prefix[0], "--force-local"] if args and args[0] == "query" else self.prefix
            result = subprocess.run(prefix + args, text=True, capture_output=True,
                                    input=input_data, **({"stdin": subprocess.DEVNULL} if input_data is None else {}),
                                    timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise Error(t('lxd_query_timeout')) from exc
        if result.returncode:
            raise Error(failure_text(result.stdout, result.stderr) or t('lxd_failed'))
        emit_native(result.stderr, self.diagnostic)
        return result.stdout

    def instances(self, timeout=None):
        try:
            instances = json.loads(self.command(["list", "local:", "--format=json"], timeout))
            if not isinstance(instances, list) or any(
                    not isinstance(item, dict)
                    or any(not isinstance(item.get(key), str) for key in ("name", "status", "type"))
                    or not isinstance(item.get("config"), dict) for item in instances):
                raise ValueError("Invalid instance list schema")
            return instances
        except (ValueError, TypeError) as exc:
            raise Error(t('lxd_invalid_data')) from exc

    @cached_property
    def configuration(self):
        from .lxd_config import Configuration
        return Configuration(self)


class Manager:
    def __init__(self, lxd=None, report=None, fs_root=None, fs_state=None, isolation=None):
        from .isolation import PROJECT
        self.lxd = lxd or LXD(project=PROJECT)
        self.report = report or (lambda event: None)
        self.fs_root, self.fs_state = fs_root, fs_state
        if isolation is not None:
            self.isolation = isolation

    @cached_property
    def isolation(self):
        from .isolation import Isolation
        return Isolation(self)

    def emit(self, event):
        notify(self.report, event)

    def _completed(self, action, target, observation, started):
        self.emit(dict(action=action, target=target, status='ok', scope='function',
                       observation=observation, elapsed=time.monotonic()-started))

    def _cleanup_warning(self, action, target, error):
        self.emit(dict(action=action, target=target, status='warning', observation='not yet observed',
                       elapsed=0, native_stderr=t('cleanup_secondary', error=error)))

    @cached_property
    def filesystems(self):
        from .filesystems import Filesystems
        return Filesystems(self, self.fs_root, self.fs_state)

    @cached_property
    def gpu(self):
        from .gpu import GPU
        return GPU(self)

    @cached_property
    def imports(self):
        from .imports import Imports
        return Imports(self)

    def hardware(self, target, enabled=None, *, capability=None):
        if enabled is not None:
            self.isolation.audit(self.require(target, stopped=True))
        return (self.gpu.status(target, capability=capability) if enabled is None
                else self.gpu.set(target, enabled, capability=capability))

    def mountfs(self, target, path=None, *, default_home=False):
        self.isolation.audit(self.require(target))
        return self.filesystems.mount(target, path, default_home=default_home)

    def unmountfs(self, target, path=None):
        return self.filesystems.unmount(target, path)

    def mountedfs(self, target):
        return self.filesystems.list(target)

    @staticmethod
    def managed(instance):
        return (instance.get("type") == "container"
                and instance.get("config", {}).get(MANAGED) == "true")

    def find(self, target, timeout=None):
        validate_target(target)
        return next((item for item in self.lxd.instances(timeout) if item["name"] == target), None)

    def require(self, target, stopped=False):
        instance = self.find(target)
        if instance is None:
            raise Error(t("container_missing", target=target))
        if not self.managed(instance):
            raise Error(t("container_unmanaged", target=target))
        if stopped and instance["status"] != "Stopped":
            raise Error(t("container_must_stop", target=target, status=state(instance["status"])))
        return instance

    def absent(self, target):
        if self.find(target) is not None:
            raise Error(t("target_exists", target=target))

    def list(self):
        return sorted((item for item in self.lxd.instances() if self.managed(item)),
                      key=lambda item: item["name"])

    def info(self, target):
        return self.require(target)

    def _run_lxd_until_state(self, action, target, args, expected, require_marker=True, client=None):
        """Wait for BOTH native command completion and a structured postcondition.

        Capture output to a file to avoid pipe backpressure on long operations.
        A timeout kills the client, not necessarily the daemon-side operation.
        """
        start = time.monotonic()
        deadline = start + self.lxd.timeout
        last = "not yet observed"
        process = None
        outcome = "error"
        native_stdout, native_stderr = "", ""
        native_failure = False
        with cleanup_scope(lambda: finish_client(process, self.lxd.timeout),
                           lambda exc: self._cleanup_warning(action, target, exc)):
            try:
                with tempfile.TemporaryFile(mode="w+t") as output, tempfile.TemporaryFile(mode="w+t") as errors:
                    process = subprocess.Popen((client or self.lxd).prefix + args, stdin=subprocess.DEVNULL,
                                               stdout=output, stderr=errors, text=True)
                    while True:
                        native_stdout, native_stderr = read_output(output), read_output(errors)
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise Error(t("operation_timeout", action=action, target=target, last=state(last)))
                        tick = time.monotonic()
                        code = process.poll()
                        if code is not None:
                            native_stdout, native_stderr = read_output(output), read_output(errors)
                        if code is not None and code != 0:
                            native_failure = True
                            raise Error(failure_text(native_stdout, native_stderr) or t("lxd_exit", code=code))
                        instance = self.find(target, remaining)
                        last = instance["status"] if instance else "Absent"
                        if instance and last == "Error":
                            raise Error(t("container_error", target=target))
                        matches = last == expected
                        if instance and require_marker:
                            matches = matches and self.managed(instance)
                        self.emit(dict(action=action, target=target, status="waiting", scope="native",
                                         elapsed=round(time.monotonic() - start, 3), observation=last))
                        if code == 0 and matches:
                            outcome = "ok"
                            return instance
                        time.sleep(max(0, min(1 - (time.monotonic() - tick), deadline - time.monotonic())))
            finally:
                self.emit(dict(action=action, target=target, status=outcome, scope='native',
                               elapsed=round(time.monotonic() - start, 3), observation=last,
                               native_stdout=native_stdout, native_stderr=native_stderr, native_failure=native_failure))

    def new(self, target, image=None):
        started = time.monotonic()
        self.absent(target)
        image = image or host_image()
        if image.startswith("-"):
            raise Error(t('invalid_image'))
        self.isolation.check()
        from .isolation import PROFILE
        from . import development
        data = development.cloud_config()
        result = self._run_lxd_until_state("new", target,
                               ["init", image, "local:" + target, "-p", PROFILE, "-c", MANAGED + "=true",
                                '-c', 'cloud-init.user-data=' + data], "Stopped")
        self.isolation.audit(result)
        self.gpu.ensure(target)
        self.isolation.audit(self.find(target))
        identity = result['config'].get('volatile.uuid')
        def prepared_instance():
            current = self.require(target)
            if not identity or current['config'].get('volatile.uuid') != identity:
                raise Error(t('new_identity_changed', target=target))
            return current
        def stop_prepared():
            prepared_instance()
            self.stop(target)
        with cleanup_scope(stop_prepared, lambda error: self._cleanup_warning('new', target, error)):
            prepared_instance()
            self.start(target)
            prepared_instance()
            self._run_lxd_until_state('prepare-development', target,
                ['exec', 'local:' + target, '--', '/bin/sh', '-c', development.verification()], 'Running')
            development.finish(self, target, data, identity)
        result = self.require(target, stopped=True)
        self._completed('new', target, 'Stopped', started)
        return result

    def start(self, target):
        return self._lifecycle(target, 'start')

    def stop(self, target):
        return self._lifecycle(target, 'stop')

    def restart(self, target, enter=False, ask=None):
        """Compose complete foundations; a failed stop prevents the next call."""
        self.stop(target)
        return self.enter(target, ask) if enter else self.start(target)

    def _prepare_user(self, target):
        return self._run_lxd_until_state('prepare-user', target,
                               ['exec', 'local:' + target, '--', '/bin/sh', '-c', USER_SETUP], 'Running')

    def _check_lifecycle_state(self, target, action):
        instance = self.require(target)
        if instance['status'] not in ('Running', 'Stopped'):
            raise Error(t('cannot_' + action, target=target, status=state(instance['status'])))
        return instance

    def _lifecycle(self, target, action):
        """External coordination surrounds the complete internal mas operation."""
        expected = 'Running' if action == 'start' else 'Stopped'
        instance = self._check_lifecycle_state(target, action)
        if action == 'start':
            self.isolation.audit(instance)
        if instance['status'] == expected:
            return self._execute_lifecycle(target, action, instance)
        # One outer lock spans all phases; nested foundations reuse that lock.
        with self.filesystems.locked():
            instance = self._check_lifecycle_state(target, action)
            if instance['status'] == expected:
                return self._execute_lifecycle(target, action, instance)
            entries = self._before_lifecycle(target, action)
            result = self._execute_lifecycle(target, action)
            self._after_lifecycle(target, expected, entries)
            return result

    def _before_lifecycle(self, target, action):
        entries = self.mountedfs(target)
        completed = []
        for index, entry in enumerate(entries):
            try:
                self.unmountfs(target, entry['path'])
            except (Error, OSError) as exc:
                raise Error(t('lifecycle_unmount_failed', action=t('action_' + action), target=target,
                              path=entry['path'], error=exc, completed=', '.join(completed) or '—',
                              pending=', '.join(e['path'] for e in entries[index+1:]) or '—')) from exc
            completed.append(entry['path'])
        if action == 'start':
            self.gpu.ensure(target)
        return entries

    def _execute_lifecycle(self, target, action, already=None):
        """User preparation is inside mas start, not external post-processing."""
        started = time.monotonic()
        expected = 'Running' if action == 'start' else 'Stopped'
        result = already
        if already is None:
            instance = self.require(target, stopped=action == 'start')
            if action == 'start':
                self.isolation.audit(instance)
            command = [action, 'local:' + target]
            if action == 'stop':
                command += ['--timeout', str(self.lxd.timeout)]
            result = self._run_lxd_until_state(action, target, command, expected)
        if action == 'start':
            result = self._prepare_user(target)
            self.gpu.prepare(target)
        self._completed(action, target, expected, started)
        return result

    def _after_lifecycle(self, target, expected, entries):
        failures = []
        for entry in entries:
            try:
                self.mountfs(target, entry['path'], default_home=entry.get('default', False))
            except (Error, OSError) as exc:
                failures.append(entry['path'] + ' → ' + entry['destination'] + ': ' + str(exc))
        if failures:
            raise Error(t('lifecycle_restore_failed', target=target, status=state(expected),
                          errors='\n'.join(failures)))

    def stop_all(self):
        failures = []
        for instance in self.list():
            try:
                self.stop(instance["name"])
            except (Error, OSError) as exc:
                failures.append(instance['name'] + ': ' + str(exc))
        if failures:
            raise Error(t("stop_failures", errors="\n".join(failures)))

    def delete(self, target, ask=None):
        started = time.monotonic()
        self.require(target, stopped=True)
        self.filesystems.guard_delete(target)
        if not confirm(t("delete_confirm", target=target), ask):
            return False
        with self.filesystems.deletion_guard(target):
            self.require(target, stopped=True)
            self._run_lxd_until_state("delete", target, ["delete", "local:" + target], "Absent")
        self._completed('delete', target, 'Absent', started)
        return True

    def import_container(self, target, filename):
        started = time.monotonic()
        self.absent(target)
        path = Path(filename).expanduser().absolute()
        if not path.is_file():
            raise Error(t("backup_missing", path=path))
        self.isolation.check()
        instance = self.imports.restore(target, path)
        if instance.get("type") != "container":
            raise Error(t("import_not_container", target=target))
        try:
            self.isolation.audit(instance)
        except Error as exc:
            # A backup may carry our old marker. Quarantine only that known key;
            # preserve the instance and all unknown settings and guest data.
            if instance.get('config', {}).get(MANAGED) == 'true':
                try:
                    self._run_lxd_until_state('quarantine-import', target,
                        ['config', 'unset', 'local:' + target, MANAGED], 'Stopped', require_marker=False)
                except (Error, OSError) as quarantine_error:
                    self._cleanup_warning('import', target, quarantine_error)
            raise Error(t('policy_import_preserved', target=target, project=self.lxd.project, error=exc)) from exc
        # lxc import has no config override. Mark only after this import succeeds.
        self._run_lxd_until_state("mark-import", target,
                        ["config", "set", "local:" + target, MANAGED + "=true"], "Stopped")
        self.isolation.audit(self.find(target))
        self._completed('import', target, 'Stopped', started)

    @cached_property
    def legacy(self):
        return Manager(LXD(project='default', timeout=self.lxd.timeout, diagnostic=self.lxd.diagnostic),
                       self.report, self.fs_root, self.fs_state, isolation=self.isolation)

    def legacy_list(self):
        return sorted((item for item in self.legacy.lxd.instances() if self.managed(item)), key=lambda i: i['name'])

    def migrate(self, target, ask=None):
        from .isolation import BASE_CONFIG, PROFILE, PROFILE_KEY
        started = time.monotonic()
        self.absent(target)
        source = self.legacy.require(target, stopped=True)
        self.legacy.filesystems.guard_delete(target)
        self.isolation.audit(source, legacy=True)
        if not confirm(t('migration_confirm', target=target, project=self.lxd.project), ask):
            return False
        with self.legacy.filesystems.deletion_guard(target):
            source = self.legacy.require(target, stopped=True)
            self.absent(target)
            self.isolation.audit(source, legacy=True)
            overrides = []
            # The old profile is replaced. Preserve its safe effective settings
            # as instance-local values through LXD's native move overrides.
            for key, value in source['expanded_config'].items():
                if key not in source['config'] and key not in BASE_CONFIG and key != PROFILE_KEY:
                    overrides += ['--config', key + '=' + value]
            result = self._run_lxd_until_state('migrate', target,
                ['move', 'local:' + target, 'local:' + target, '--target-project', self.lxd.project,
                 '--profile', PROFILE, *overrides],
                'Stopped', client=self.legacy.lxd)
            self.isolation.audit(result)
        self._completed('migrate', target, 'Stopped', started)
        return True

    def export(self, target, filename, ask=None):
        started = time.monotonic()
        self.require(target, stopped=True)
        destination = Path(filename).expanduser().absolute()
        overwrite = destination.exists() or destination.is_symlink()
        if overwrite and not confirm(t("overwrite_confirm", path=destination), ask):
            return False
        if overwrite and (destination.is_symlink() or not destination.is_file()):
            raise Error(t('export_regular'))
        self.require(target, stopped=True)
        if not destination.parent.is_dir():
            raise Error(t("export_directory", path=destination.parent))
        # Publish only the complete backup. A declined overwrite preserves the old file.
        directory = tempfile.TemporaryDirectory(prefix=".mas-export-", dir=destination.parent)
        with cleanup_scope(directory.cleanup, lambda exc: self._cleanup_warning('export', target, exc)):
            backup = Path(directory.name) / "backup.tar.gz"
            self._run_lxd_until_state("export", target, ["export", "local:" + target, str(backup)], "Stopped")
            try:
                with tarfile.open(backup, "r:*") as archive:
                    if not any(member.name.rstrip("/") == "backup/index.yaml" for member in archive):
                        raise Error(t('export_metadata'))
                if overwrite:
                    os.replace(backup, destination)
                else:
                    os.link(backup, destination)
            except (tarfile.TarError, OSError) as exc:
                raise Error(t("export_failed", error=exc)) from exc
        self._completed('export', target, 'Stopped', started)
        return True

    def on_exit(self, target, ask=None):
        message = t('shell_finished', target=target)
        try:
            choice = ask(message) if ask is not None else 'exit'
        except EOFError:
            choice = 'exit'
        if choice is None:
            choice = 'exit'
        if choice not in ('stop', 'restart', 'menu', 'exit'):
            # Preserve existing boolean/yes-no providers and CLI consent flags.
            choice = 'stop' if confirm(message, lambda _: choice) else 'exit'
        if choice == 'stop':
            self.stop(target)
        elif choice == 'restart':
            self.restart(target)
        return 'menu' if choice == 'menu' else 'exit'

    def enter(self, target, ask=None):
        self.require(target)
        self.start(target)
        code = subprocess.call(self.lxd.prefix + ["exec", "local:" + target, "--", "su", "--login", "sandbox"])
        # Session completion is independent of the shell's exit-code success.
        try:
            choice = self.on_exit(target, ask)
        except (Error, OSError) as exc:
            detail = str(exc)
            if code:
                detail = t('shell_exit', code=code) + '\n' + detail
            raise ShellExitError(detail) from exc
        if code:
            raise ShellExitError(t('shell_exit', code=code), return_to_menu=choice == 'menu')
        return choice
