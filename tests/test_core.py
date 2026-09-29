import contextlib
import io
import subprocess
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mas.core import Error, LXD, MANAGED, Manager, confirm, host_image, validate_target
from mas.cli import main


class BehaviorTests(unittest.TestCase):
    def setUp(self):
        from mas.i18n import catalog
        catalog("en_us")
        language = patch("mas.config.language", return_value="en_us")
        language.start()
        self.addCleanup(language.stop)

    def manager(self, status="Stopped", owned=True):
        lxd = Mock(timeout=300, project="default")
        lxd.instances.return_value = [{"name": "demo", "type": "container", "status": status,
                                      "config": {MANAGED: "true"} if owned else {}}]
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        manager = Manager(lxd, fs_state=Path(temporary.name)/"state")
        manager.gpu = Mock()  # GPU behavior has independent unit/native coverage.
        manager._run_lxd_until_state = Mock()
        return manager

    def test_confirmation_defaults_and_explicit_yes(self):
        for answer in ("", "n", "no", "anything"):
            self.assertFalse(confirm("Proceed?", lambda _: answer))
        for answer in ("y", "Y", "yes", " YES "):
            self.assertTrue(confirm("Proceed?", lambda _: answer))
        self.assertFalse(confirm("Proceed?", Mock(side_effect=EOFError)))

    def test_delete_requires_consent_and_rechecks_state(self):
        manager = self.manager()
        self.assertFalse(manager.delete("demo", lambda _: ""))
        manager._run_lxd_until_state.assert_not_called()
        self.assertTrue(manager.delete("demo", lambda _: "y"))
        manager._run_lxd_until_state.assert_called_once()

    def test_delete_detects_state_change_during_prompt(self):
        manager = self.manager()
        def ask(_):
            manager.lxd.instances.return_value[0]["status"] = "Running"
            return "y"
        with self.assertRaises(Error):
            manager.delete("demo", ask)
        manager._run_lxd_until_state.assert_not_called()

    def test_running_delete_and_export_refused_before_prompt(self):
        manager = self.manager("Running")
        ask = Mock(return_value="y")
        with self.assertRaises(Error):
            manager.delete("demo", ask)
        with self.assertRaises(Error):
            manager.export("demo", "/tmp/unused-backup", ask)
        ask.assert_not_called()

    def test_export_decline_preserves_file(self):
        manager = self.manager()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup"
            path.write_bytes(b"original")
            self.assertFalse(manager.export("demo", path, lambda _: ""))
            self.assertEqual(path.read_bytes(), b"original")
        manager._run_lxd_until_state.assert_not_called()

    def test_unmanaged_rejected(self):
        manager = self.manager(owned=False)
        self.assertEqual(manager.list(), [])
        for method in (manager.start, manager.stop, manager.info, manager.enter, manager.delete):
            with self.subTest(method=method.__name__), self.assertRaises(Error):
                method("demo")
        manager._run_lxd_until_state.assert_not_called()

    def test_query_failure_is_not_absence(self):
        manager = self.manager()
        manager.lxd.instances.side_effect = Error("connection lost")
        with self.assertRaisesRegex(Error, "connection lost"):
            manager.absent("new-target")

    def test_collision_applies_to_unmanaged_targets(self):
        manager = self.manager(owned=False)
        with self.assertRaisesRegex(Error, "already exists"):
            manager.new("demo")
        with self.assertRaisesRegex(Error, "already exists"):
            manager.import_container("demo", "missing.tar.gz")

    def test_remote_and_snapshot_targets_rejected(self):
        for name in ("remote:demo", "demo/snap", "--all", "", "a;id"):
            with self.subTest(name=name), self.assertRaises(Error):
                validate_target(name)

    def test_host_release_selection(self):
        with patch.object(Path, "read_text", return_value='ID=ubuntu\nVERSION_ID="26.04"\n'):
            self.assertEqual(host_image(), "ubuntu:26.04")
        with patch.object(Path, "read_text", return_value='ID=debian\nVERSION_ID="13"\n'):
            with self.assertRaises(Error):
                host_image()

    def test_enter_and_exit_reuse_shared_functions(self):
        manager = self.manager()
        manager.lxd.prefix = ["lxc"]
        manager.start, manager.stop = Mock(), Mock()
        with patch("mas.core.subprocess.call", return_value=0) as call:
            manager.enter("demo", lambda _: "y")
        manager.start.assert_called_once_with("demo")
        manager.stop.assert_called_once_with("demo")
        self.assertEqual(call.call_args.args[0][-3:], ["su", "--login", "sandbox"])

    def test_stop_all_only_managed(self):
        manager = self.manager()
        manager.lxd.instances.return_value.append({"name": "external", "type": "container", "config": {}})
        manager.stop = Mock()
        manager.stop_all()
        manager.stop.assert_called_once_with("demo")

    def test_cli_rejects_bad_stop_and_timeout(self):
        for args in (["stop"], ["stop", "demo", "--all"], ["--timeout", "299", "list"]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                main(args)
            self.assertEqual(exc.exception.code, 2)

    def test_bare_cli_opens_tui(self):
        manager = self.manager()
        with patch("mas.terminal_ui.run") as run:
            self.assertEqual(main([], manager), 0)
        run.assert_called_once_with(manager)

    def test_timeout_minimum(self):
        with self.assertRaises(Error):
            LXD(timeout=299)

    def test_success_exit_code_does_not_skip_state_wait(self):
        lxd = Mock(prefix=["lxc"], timeout=600)
        manager = Manager(lxd, Mock())
        manager.gpu = Mock()  # GPU behavior has independent unit/native coverage.
        manager.find = Mock(side_effect=[
            {"status": state, "type": "container", "config": {MANAGED: "true"}}
            for state in ("Stopped", "Stopped", "Running")])
        process = Mock()
        process.poll.return_value = 0
        clock = [0]
        with patch("mas.core.subprocess.Popen", return_value=process), \
                patch("mas.core.time.monotonic", side_effect=lambda: clock[0]), \
                patch("mas.core.time.sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)) as sleep:
            manager._run_lxd_until_state("start", "demo", ["start", "local:demo"], "Running")
        self.assertEqual(manager.find.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 1])
        self.assertEqual(manager.report.call_args.args[0]["elapsed"], 2)

    def test_wait_timeout_reports_last_state_and_stops_client(self):
        lxd = Mock(prefix=["lxc"], timeout=300)
        manager = Manager(lxd, Mock())
        manager.gpu = Mock()  # GPU behavior has independent unit/native coverage.
        manager.find = Mock(return_value={"status": "Stopped", "type": "container", "config": {MANAGED: "true"}})
        process = Mock()
        process.poll.return_value = None
        clock = [0]
        with patch("mas.core.subprocess.Popen", return_value=process), \
                patch("mas.core.time.monotonic", side_effect=lambda: clock[0]), \
                patch("mas.core.time.sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            with self.assertRaisesRegex(Error, "last state: Stopped"):
                manager._run_lxd_until_state("start", "demo", ["start", "local:demo"], "Running")
        process.kill.assert_called_once()
        self.assertEqual(manager.report.call_args.args[0]["elapsed"], 300)
        self.assertEqual(manager.report.call_args.args[0]["status"], "error")

    def test_newest_stable_channel_not_default_lts(self):
        from mas.install import stable_channel
        self.assertEqual(stable_channel('  5.21/stable: 5.21.8-abc 2026-09-25\n'
                                        '  latest/stable: 6.9-abc 2026-09-25\n'
                                        '  6/stable: 6.9-abc 2026-09-25\n'), "6/stable")

    def test_existing_lxd_configuration_is_preserved(self):
        from mas.install import initialize
        lxd = Mock()
        lxd.command.side_effect = ['[{"name":"user-pool"}]', '[{"name":"default","devices":{}}]', '[]']
        with patch("mas.install.LXD", return_value=lxd), patch("mas.install.run") as run:
            with self.assertRaisesRegex(Error, "root disk"):
                initialize()
        run.assert_not_called()

    def test_fresh_install_authenticates_snap_seed_wait(self):
        from mas.install import prepare_system

        for snap_present in (True, False):
            commands = []

            def execute(args, **kwargs):
                commands.append(args)
                native = args[1:] if args[0] == "sudo" else args
                needs_root = native[0] in ("apt-get", "systemctl") or native[:2] in (
                    ["snap", "wait"], ["snap", "install"])
                if needs_root and args[0] != "sudo":
                    return subprocess.CompletedProcess(args, 1, "", "error: access denied (try with sudo)")
                output = "  6/stable: 6.9-abc 2026-09-25\n" if native == ["snap", "info", "lxd"] else ""
                return subprocess.CompletedProcess(args, 0, output, "")

            with self.subTest(snap_present=snap_present), \
                    patch("mas.install.prepare_dependencies"), \
                    patch("mas.install.prepare_fuse_access"), \
                    patch("mas.install.Path.read_text", side_effect=['ID=ubuntu\n', 'systemd\n']), \
                    patch("mas.install.Path.exists", return_value=False), \
                    patch("mas.install.shutil.which", side_effect=lambda name: "/usr/bin/snap" if name == "snap" and snap_present else None), \
                    patch("mas.install.os.geteuid", return_value=1000), \
                    patch("mas.install.os.getgid", return_value=1000), \
                    patch("mas.install.os.getgroups", return_value=[986]), \
                    patch("mas.install.pwd.getpwuid", return_value=SimpleNamespace(pw_name="tester")), \
                    patch("mas.install.grp.getgrnam", return_value=SimpleNamespace(gr_gid=986, gr_mem=["tester"])), \
                    patch("mas.install.sys.stdin.isatty", return_value=True), \
                    patch("mas.install.subprocess.run", side_effect=execute), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(prepare_system())
                self.assertNotIn(["sudo", "-v"], commands)
                self.assertIn(["sudo", "snap", "wait", "system", "seed.loaded"], commands)
                self.assertIn(["sudo", "snap", "install", "lxd", "--channel=6/stable"], commands)


if __name__ == "__main__":
    unittest.main()
