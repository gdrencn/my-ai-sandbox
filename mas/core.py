"""Shared operations. Only this module implements container lifecycle behavior."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time

MANAGED = "user.mas.managed"
DEFAULT_TIMEOUT = 600

USER_SETUP = r'''set -eu
if command -v cloud-init >/dev/null 2>&1; then
    cloud-init status --wait || test "$?" = 2
fi
if ! command -v sudo >/dev/null 2>&1; then
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


def confirm(message, ask=input):
    """One confirmation policy, independent of CLI or TUI presentation."""
    try:
        return ask(message + " [y/N] ").strip().lower() in ("y", "yes")
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
        raise Error("Cannot select an Ubuntu image from this host; specify --image explicitly.")
    return "ubuntu:" + values["VERSION_ID"]


def validate_target(target):
    if not re.fullmatch(r"[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", target):
        raise Error("TARGET must be a local container name (1–63 letters, digits or hyphens; start with a letter).")


class LXD:
    def __init__(self, project="default", timeout=DEFAULT_TIMEOUT):
        if timeout < 300:
            raise Error("Timeout must be at least 300 seconds.")
        executable = shutil.which("lxc")
        if not executable and Path("/snap/bin/lxc").exists():
            executable = "/snap/bin/lxc"
        if not executable:
            raise Error("LXD/lxc is missing. Run the installer to prepare this machine.")
        self.prefix = [executable, "--project", project]
        self.project = project
        self.timeout = timeout

    def command(self, args, timeout=None):
        try:
            result = subprocess.run(self.prefix + args, text=True, capture_output=True,
                                    stdin=subprocess.DEVNULL, timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise Error("LXD query timed out; the server operation may still be running.") from exc
        if result.returncode:
            raise Error(result.stderr.strip() or result.stdout.strip() or "LXD command failed.")
        return result.stdout

    def instances(self, timeout=None):
        try:
            return json.loads(self.command(["list", "local:", "--format=json"], timeout))
        except (ValueError, TypeError) as exc:
            raise Error("LXD returned invalid instance data; absence cannot be established.") from exc


class Manager:
    def __init__(self, lxd=None, report=None):
        self.lxd = lxd or LXD()
        self.report = report or (lambda event: None)

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
            raise Error(f"Container {target} does not exist.")
        if not self.managed(instance):
            raise Error(f"Container {target} is not managed by mas; no action taken.")
        if stopped and instance["status"] != "Stopped":
            raise Error(f"Container {target} must be stopped first (currently {instance['status']}).")
        return instance

    def absent(self, target):
        if self.find(target) is not None:
            raise Error(f"TARGET {target} already exists; nothing will be overwritten.")

    def list(self):
        return sorted((item for item in self.lxd.instances() if self.managed(item)),
                      key=lambda item: item["name"])

    def info(self, target):
        return self.require(target)

    def _operation(self, action, target, args, expected, require_marker=True):
        """Wait for BOTH native command completion and a structured postcondition.

        Capture output to a file to avoid pipe backpressure on long operations.
        A timeout kills the client, not necessarily the daemon-side operation.
        """
        start = time.monotonic()
        deadline = start + self.lxd.timeout
        last = "not yet observed"
        process = None
        outcome = "error"
        try:
            with tempfile.TemporaryFile(mode="w+t") as output:
                process = subprocess.Popen(self.lxd.prefix + args, stdin=subprocess.DEVNULL,
                                           stdout=output, stderr=output, text=True)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise Error(f"{action} {target} timed out; last state: {last}. "
                                    "LXD may still be working; inspect before retrying.")
                    tick = time.monotonic()
                    code = process.poll()
                    if code is not None and code != 0:
                        output.seek(0)
                        raise Error(output.read().strip() or f"LXD exited with {code}.")
                    instance = self.find(target, remaining)
                    last = instance["status"] if instance else "Absent"
                    if instance and last == "Error":
                        raise Error(f"{target} entered LXD Error state.")
                    matches = last == expected
                    if instance and require_marker:
                        matches = matches and self.managed(instance)
                    self.report(dict(action=action, target=target, status="waiting",
                                     elapsed=round(time.monotonic() - start, 3), observation=last))
                    if code == 0 and matches:
                        outcome = "ok"
                        return instance
                    time.sleep(max(0, min(1 - (time.monotonic() - tick), deadline - time.monotonic())))
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            self.report(dict(action=action, target=target, status=outcome,
                             elapsed=round(time.monotonic() - start, 3), observation=last))

    def new(self, target, image=None):
        self.absent(target)
        image = image or host_image()
        if image.startswith("-"):
            raise Error("Invalid image reference.")
        return self._operation("new", target,
                               ["init", image, "local:" + target, "-c", MANAGED + "=true"], "Stopped")

    def start(self, target):
        instance = self.require(target)
        if instance["status"] == "Running":
            self.report(dict(action="start", target=target, status="ok", elapsed=0, observation="Running"))
        elif instance["status"] != "Stopped":
            raise Error(f"Cannot start {target} from {instance['status']}.")
        else:
            self._operation("start", target, ["start", "local:" + target], "Running")
        return self._operation("prepare-user", target,
                               ["exec", "local:" + target, "--", "/bin/sh", "-c", USER_SETUP], "Running")

    def stop(self, target):
        instance = self.require(target)
        if instance["status"] == "Stopped":
            self.report(dict(action="stop", target=target, status="ok", elapsed=0, observation="Stopped"))
            return instance
        if instance["status"] != "Running":
            raise Error(f"Cannot stop {target} from {instance['status']}.")
        return self._operation("stop", target, ["stop", "local:" + target, "--timeout", str(self.lxd.timeout)], "Stopped")

    def stop_all(self):
        failures = []
        for instance in self.list():
            try:
                self.stop(instance["name"])
            except Error as exc:
                failures.append(str(exc))
        if failures:
            raise Error("Some containers could not be stopped:\n" + "\n".join(failures))

    def delete(self, target, ask=input):
        self.require(target, stopped=True)
        if not confirm(f"Delete {target}?", ask):
            return False
        self.require(target, stopped=True)
        self._operation("delete", target, ["delete", "local:" + target], "Absent")
        return True

    def import_container(self, target, filename):
        self.absent(target)
        path = Path(filename).expanduser().absolute()
        if not path.is_file():
            raise Error(f"Backup does not exist: {path}")
        instance = self._operation("import", target, ["import", "local:", str(path), target],
                                   "Stopped", require_marker=False)
        if instance.get("type") != "container":
            raise Error(f"Imported {target} is not a container; it was left unmanaged. Only container backups are supported.")
        # lxc import has no config override. Mark only after this import succeeds.
        self._operation("mark-import", target,
                        ["config", "set", "local:" + target, MANAGED + "=true"], "Stopped")

    def export(self, target, filename, ask=input):
        self.require(target, stopped=True)
        destination = Path(filename).expanduser().absolute()
        overwrite = destination.exists() or destination.is_symlink()
        if overwrite and not confirm(f"Overwrite {destination}?", ask):
            return False
        if overwrite and (destination.is_symlink() or not destination.is_file()):
            raise Error("Export destination must be a regular file, not a directory or symbolic link.")
        self.require(target, stopped=True)
        if not destination.parent.is_dir():
            raise Error(f"Export directory does not exist: {destination.parent}")
        # Publish only the complete backup. A declined overwrite preserves the old file.
        with tempfile.TemporaryDirectory(prefix=".mas-export-", dir=destination.parent) as directory:
            backup = Path(directory) / "backup.tar.gz"
            self._operation("export", target, ["export", "local:" + target, str(backup)], "Stopped")
            try:
                with tarfile.open(backup, "r:*") as archive:
                    if not any(member.name.rstrip("/") == "backup/index.yaml" for member in archive):
                        raise Error("LXD export is missing its backup metadata.")
                if overwrite:
                    os.replace(backup, destination)
                else:
                    os.link(backup, destination)
            except (tarfile.TarError, OSError) as exc:
                raise Error(f"Cannot validate or publish export: {exc}") from exc
        return True

    def on_exit(self, target, ask=input):
        if confirm(f"Stop {target}?", ask):
            self.stop(target)

    def enter(self, target, ask=input):
        self.require(target)
        self.start(target)
        code = subprocess.call(self.lxd.prefix + ["exec", "local:" + target, "--", "su", "--login", "sandbox"])
        self.on_exit(target, ask)
        if code:
            raise Error(f"Container terminal exited with status {code}.")
