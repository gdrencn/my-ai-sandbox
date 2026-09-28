"""Portable real-LXD test runner, using only Python's standard library."""

import contextlib
import errno
import fcntl
import hashlib
import json

import os
from pathlib import Path
import platform
import pty
import select
import signal
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
from .cli import progress
from .core import Error, LXD, Manager, host_image

from .i18n import t, Parser


def random_target():
    return "test-" + uuid.uuid4().hex


class Terminal:
    def __init__(self, command, timeout, transcript):
        self.timeout = timeout
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
             "overwrite-confirmation", "ownership-and-stop-all", "delete-confirmation", "language-config", "tui"]

    def __init__(self, report_dir, timeout, product=None):
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
            config.set_value("language", "en_us")
        self.timeout = timeout
        self.project = random_target()
        self.host = LXD(timeout=timeout)
        self.manager = Manager(LXD(project=self.project, timeout=timeout), self.report)
        self.created_project = False
        self.targets = []
        self.events = []
        self.results = {case: {"status": "not_run"} for case in self.CASES}
        self.cleanup_errors = []
        self.counter = 0

    def report(self, event):
        self.events.append(event)
        progress(event)

    @contextlib.contextmanager
    def case(self, name):
        start = time.monotonic()
        print(t("test_case", name=name), flush=True)
        try:
            yield
        except BaseException as exc:
            self.results[name] = {"status": "failed", "elapsed": time.monotonic() - start, "error": str(exc)}
            raise
        else:
            self.results[name] = {"status": "passed", "elapsed": time.monotonic() - start}
            print(t("test_pass", name=name, elapsed=self.results[name]["elapsed"]), flush=True)

    def target(self):
        name = random_target()
        self.targets.append(name)
        return name

    def command(self, args):
        # Exercise the actual CLI with an injected isolated manager. Product CLI
        # never accepts a remote/project override or a test environment variable.
        source = ("import os,sys;os.environ['XDG_CONFIG_HOME']=" + repr(str(self.config_home)) + ";sys.path.insert(0," + repr(str(self.product) if self.product else sys.path[0]) + ");"
                  "from mas.cli import main,progress;from mas.core import Manager,LXD;"
                  "raise SystemExit(main(manager=Manager(LXD(project=" + repr(self.project) +
                  ",timeout=" + str(self.timeout) + "),report=progress)))")
        return [sys.executable, "-c", source, *args]

    def cli(self, *args, answer=None, code=0):
        start = time.monotonic()
        result = subprocess.run(self.command(list(args)), input=answer or "", capture_output=True,
                                text=True, timeout=self.timeout * 3)
        self.counter += 1
        (self.directory / f"cli-{self.counter}.txt").write_text(result.stdout + result.stderr)
        print(result.stderr, end="", flush=True)
        print(t("test_cli", command=" ".join(args), elapsed=time.monotonic()-start), flush=True)
        if result.returncode != code:
            raise AssertionError(t("cli_failed", args=args, expected=code, actual=result.returncode, stdout=result.stdout, stderr=result.stderr))
        return result.stdout

    @contextlib.contextmanager
    def terminal(self, args):
        self.counter += 1
        terminal = Terminal(self.command(args), self.timeout, self.directory / f"terminal-{self.counter}.log")
        try:
            yield terminal
        finally:
            terminal.close()

    def wait(self, label, probe, terminal=None):
        start = time.monotonic()
        while time.monotonic() - start < self.timeout:
            if terminal:
                terminal.read()
                if terminal.status is not None:
                    raise AssertionError(t("pty_unexpected", buffer=terminal.buffer[-2000:]))
            if probe():
                elapsed = time.monotonic() - start
                print(t("test_wait", label=label, elapsed=elapsed), flush=True)
                self.events.append(dict(action="test-wait", target=label, status="ok", elapsed=elapsed))
                return
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
            from tests import test_core, test_i18n
            units = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module)
                                       for module in (test_core, test_i18n))
            result = unittest.TextTestRunner(verbosity=2).run(units)
            assert result.wasSuccessful(), t("unit_failed")
        self.host.command(["project", "create", "local:" + self.project,
                           "-c", "features.images=false", "-c", "features.profiles=false"])
        self.created_project = True
        with self.case("new-default"):
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
        with self.case("start-user-network"):
            self.cli("start", target)
            assert self.exec(target, "su --login sandbox -c 'id -un; sudo -n id -u'").splitlines() == ["sandbox", "0"]
            self.wait("outbound HTTPS", lambda: self.network(target))
            self.exec(target, "printf '%s' mas-roundtrip-data > /home/sandbox/mas-proof")
        with self.case("running-guards"):
            self.cli("delete", target, answer="y\n", code=1)
            self.cli("export", target, str(self.directory / "forbidden.tar.gz"), code=1)
            assert self.state(target, "Running")
        with self.case("enter-running-default-exit"):
            with self.terminal(["enter", target]) as terminal:
                terminal.expect("sandbox@")
                self.check_shell(terminal)
                terminal.send("exit\n")
                terminal.expect(f"Stop {target}? [y/N]")
                terminal.send("\n")
                terminal.finish()
            assert self.state(target, "Running")
        with self.case("enter-stopped-stop-exit"):
            self.cli("stop", target)
            with self.terminal(["enter", target]) as terminal:
                terminal.expect("sandbox@")
                self.check_shell(terminal)
                terminal.send("exit\n")
                terminal.expect(f"Stop {target}? [y/N]")
                terminal.send("y\n")
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
            self.cli("export", target, str(sentinel), answer="\n")
            assert sentinel.read_bytes() == b"unchanged"
            self.cli("export", target, str(sentinel), answer="y\n")
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
        with self.case("delete-confirmation"):
            self.cli("delete", imported, answer="\n")
            assert self.state(imported, "Stopped")
            self.cli("delete", imported, answer="y\n")
            assert self.state(imported, "Absent")
            self.cli("delete", target, answer="y\n")
        with self.case("language-config"):
            assert self.cli("config", "get", "language").strip() == "en_us"
            self.cli("config", "set", "language", "zh_cn")
            assert "管理" in self.cli("--help")
            assert self.cli("config", "get", "language").strip() == "zh_cn"
            self.cli("config", "set", "language", "en_us")
        with self.case("tui"):
            self.tui()

    def network(self, target):
        try:
            self.exec(target, "python3 -c \"import urllib.request; urllib.request.urlopen('https://ubuntu.com',timeout=30).read(1)\"")
            return True
        except Error:
            return False

    def tui(self):
        target, imported = self.target(), self.target()
        backup = Path(self.workspace.name) / "tui-backup.tar.gz"
        with self.terminal([]) as terminal:
            terminal.expect("my-ai-sandbox")
            terminal.send("c")
            terminal.expect("Settings")
            terminal.send("2")
            terminal.expect(t("settings_title", locale="zh_cn"))
            assert self.cli("config", "get", "language").strip() == "zh_cn"
            terminal.send("q")
            terminal.expect(t("tui_title", locale="zh_cn"))
            terminal.send("n")
            terminal.expect(t("new_target", locale="zh_cn"))
            terminal.send(target + "\n")
            terminal.expect(t("new_image", locale="zh_cn"))
            terminal.send("\n")
            self.wait("TUI Chinese new", lambda: self.state(target, "Stopped"), terminal)
            terminal.send("d")
            terminal.expect("[y/N]")
            terminal.send("\n")
            terminal.expect(t("cancelled", locale="zh_cn"))
            assert self.state(target, "Stopped")
            terminal.send("c")
            terminal.expect(t("settings_title", locale="zh_cn"))
            terminal.send("1")
            terminal.expect("Settings")
            terminal.send("q")
            terminal.expect("my-ai-sandbox")
            self.cli("delete", target, answer="y\n")
            terminal.send("r")
            terminal.send("n")
            terminal.expect("New TARGET:")
            terminal.send(target + "\n")
            terminal.expect("Image (Enter = host Ubuntu):")
            terminal.send("\n")
            self.wait("TUI new", lambda: self.state(target, "Stopped"), terminal)
            terminal.send("i")
            terminal.expect("Info:")
            terminal.send("q")
            terminal.send("s")
            self.wait("TUI start", lambda: self.state(target, "Running"), terminal)
            terminal.send("e")
            terminal.expect("sandbox@")
            self.check_shell(terminal)
            terminal.send("exit\n")
            terminal.expect(f"Stop {target}? [y/N]")
            terminal.send("n\n")
            terminal.expect("my-ai-sandbox")
            terminal.send("t")
            self.wait("TUI stop", lambda: self.state(target, "Stopped"), terminal)
            terminal.send("x")
            terminal.expect("Export FILE:")
            terminal.send(str(backup) + "\n")
            self.wait("TUI export", backup.exists, terminal)
            terminal.send("x")
            terminal.expect("Export FILE:")
            terminal.send(str(backup) + "\n")
            terminal.expect("[y/N]")
            terminal.send("\n")
            terminal.expect(t("cancelled", locale="en_us"))
            terminal.send("d")
            terminal.expect("[y/N]")
            terminal.send("\n")
            terminal.expect(t("cancelled", locale="en_us"))
            assert self.state(target, "Stopped")
            terminal.send("d")
            terminal.expect("[y/N]")
            terminal.send("y\n")
            self.wait("TUI delete", lambda: self.state(target, "Absent"), terminal)
            terminal.send("m")
            terminal.expect("Import TARGET:")
            terminal.send(imported + "\n")
            terminal.expect("Backup FILE:")
            terminal.send(str(backup) + "\n")
            self.wait("TUI import", lambda: self.state(imported, "Stopped"), terminal)
            terminal.send("s")
            self.wait("TUI imported start", lambda: self.state(imported, "Running"), terminal)
            terminal.send("a")
            self.wait("TUI stop all", lambda: self.state(imported, "Stopped"), terminal)
            terminal.send("r")
            terminal.send("q")
            terminal.finish()

    def cleanup(self):
        try:
            self.workspace.cleanup()
        except OSError as exc:
            self.cleanup_errors.append(t("backup_cleanup", error=exc))
        if not self.created_project:
            return
        for target in self.targets:
            try:
                item = self.manager.find(target)
                if item:
                    if item["status"] != "Stopped":
                        self.manager._operation("cleanup-stop", target, ["stop", "local:" + target,
                                                "--timeout", str(self.timeout)], "Stopped", require_marker=False)
                    self.manager._operation("cleanup-delete", target, ["delete", "local:" + target],
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
        }, indent=2))


def main(argv=None):
    parser = Parser(description=t('help_test'))
    parser.add_argument("--output", type=Path, default=Path("test-results") / time.strftime("%Y%m%d-%H%M%S"), help=t("help_output"))
    parser.add_argument("--timeout", type=int, default=600, help=t("help_timeout"))
    parser.add_argument("--product", type=Path, help=t('help_product'))
    args = parser.parse_args(argv)
    if args.product is None and zipfile.is_zipfile(sys.argv[0]):
        args.product = Path.home() / ".local/bin/mas"
        if not args.product.is_file():
            parser.error(t('product_required'))
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
        traceback.print_exc()
    finally:
        suite.cleanup()
        suite.save()
    print(t("report", path=suite.directory / "report.json"))
    return 0 if success and not suite.cleanup_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
