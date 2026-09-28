"""Portable real-LXD test runner, using only Python's standard library."""

import contextlib
import errno
import fcntl
import hashlib
import io
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
from .test_output import Output
from .core import Error, LXD, Manager, host_image

from .i18n import t, Parser, catalog, progress_text


PRODUCT_UNDER_TEST = None

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
             "overwrite-confirmation", "ownership-and-stop-all", "delete-confirmation", "language-config", "tui"]

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
        self.manager = Manager(LXD(project=self.project, timeout=timeout), self.report)
        self.created_project = False
        self.targets = []
        self.events = []
        self.results = {case: {"status": "not_run"} for case in self.CASES}
        self.cleanup_errors = []
        self.counter = 0

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
                  "from mas.cli import main,progress;from mas.core import Manager,LXD;"
                  "events=open(" + repr(str(self.event_path)) + ", 'a');"
                  "report=lambda event:(events.write(json.dumps(event)+'\\n'),events.flush(),progress(event));"
                  "raise SystemExit(main(manager=Manager(LXD(project=" + repr(self.project) +
                  ",timeout=" + str(self.timeout) + "),report=report)))")
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
            from tests import test_core, test_i18n, test_distribution, test_menu
            units = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module)
                                       for module in (test_core, test_i18n, test_distribution, test_menu))
            with (self.directory / "unit.log").open("w+") as log:
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    result = unittest.TextTestRunner(stream=log, verbosity=2).run(units)
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
                terminal.expect(f"Stop {target}?")
                terminal.send("\n")
                terminal.finish()
            assert self.state(target, "Running")
        with self.case("enter-stopped-stop-exit"):
            self.cli("stop", target)
            with self.terminal(["enter", target]) as terminal:
                terminal.expect("sandbox@")
                self.check_shell(terminal)
                terminal.send("exit\n")
                terminal.expect(f"Stop {target}?")
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
        with self.case("delete-confirmation"):
            with self.terminal(["delete", imported]) as terminal:
                terminal.expect("Delete " + imported)
                terminal.send("\n")
                terminal.finish()
            assert self.state(imported, "Stopped")
            with self.terminal(["delete", imported]) as terminal:
                terminal.expect("Delete " + imported)
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
                terminal.expect(expected)
            down, up, back = "\x1b[B", "\x1bOA", "\x1b[D"
            terminal.expect("my-ai-sandbox")
            send(down + "\n", "Settings")
            send("\n", "Language / 语言")
            send("\x1b", "Language: en_us")
            send("\n", "Language / 语言")
            send(up + "\n", "语言：zh_cn")
            assert self.cli("config", "get", "language").strip() == 'zh_cn'
            send("\n", "语言 / Language")
            send(down + "\n", "Language: en_us")
            send(back, "my-ai-sandbox")
            send(up + "\x1b[C", "Container management")
            # Empty list and cancelled creation return safely to their parent menu.
            send("\n", "No managed containers.")
            send(back, "Container management")
            send(down + "\n", "New TARGET:")
            send("\x1b", "Container management")
            send("\n", "New TARGET:")
            send(target + "\n", "Image (Enter = host Ubuntu):")
            terminal.send("\n")
            self.wait("TUI new", lambda: self.state(target, "Stopped"), terminal)
            send(up + "\n", "Containers")
            send("\n", "Container: " + target)
            send("\n", "Info:")
            send(down + up + back, "Container: " + target)
            terminal.send(down + "\n")
            self.wait("TUI start", lambda: self.state(target, "Running"), terminal)
            send(down + "\n", "sandbox@")
            self.check_shell(terminal)
            send("exit\n", f"Stop {target}?")
            send("\n", "Container: " + target)
            assert self.state(target, 'Running')
            terminal.send(down + "\n")
            self.wait("TUI stop", lambda: self.state(target, "Stopped"), terminal)
            send(down + "\n", "Export FILE:")
            terminal.send(str(backup) + "\n")
            self.wait("TUI export", backup.exists, terminal)
            send("\n", "Export FILE:")
            send(str(backup) + "\n", "Overwrite ")
            send("\n", "Cancelled.")
            send(down + "\n", "Delete " + target)
            send("\n", "Cancelled.")
            assert self.state(target, 'Stopped')
            send("\n", "Delete " + target)
            terminal.send(down + "\n")
            self.wait("TUI delete", lambda: self.state(target, "Absent"), terminal)
            send(back, "Container management")
            send(down * 2 + "\n", "Import TARGET:")
            send(imported + "\n", "Backup FILE:")
            terminal.send(str(backup) + "\n")
            self.wait("TUI import", lambda: self.state(imported, "Stopped"), terminal)
            send(up * 2 + "\n", "Containers")
            send("\n", "Container: " + imported)
            terminal.send(down + "\n")
            self.wait("TUI imported start", lambda: self.state(imported, "Running"), terminal)
            send(back, "Containers")
            send(back, "Container management")
            terminal.send(down * 3 + "\n")
            self.wait("TUI stop all", lambda: self.state(imported, "Stopped"), terminal)
            send(back, "my-ai-sandbox")
            terminal.send(down * 2 + "\n")
            terminal.finish()
            for forbidden in (b'\x1b[?1049', b'\x1b[?1047', b'\x1b[?47', b'\x1b[2J', b'\x1b[3J', b'\x1b[H'):
                assert forbidden not in terminal.buffer, repr(forbidden)
            assert b'"status": "Stopped"' in terminal.buffer
            assert b'[ok] start ' in terminal.buffer

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
        suite.cleanup()
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
