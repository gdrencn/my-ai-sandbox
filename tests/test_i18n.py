"""Configuration, translation, and installer selection contracts."""
import contextlib
import io
import json
import os
from pathlib import Path
import string
import tempfile
import unittest
from unittest.mock import patch, Mock

from mas import config
from mas.cli import main
from mas.i18n import catalog, choose_language, progress_text, t
from mas.tui import cells


class LanguageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = patch.dict(os.environ, {"XDG_CONFIG_HOME": directory.name})
        environment.start()
        self.addCleanup(environment.stop)

    def test_catalogs_have_matching_keys_and_placeholders(self):
        english, chinese = catalog("en_us"), catalog("zh_cn")
        self.assertEqual(english.keys(), chinese.keys())
        def fields(value):
            return {name for _, name, _, _ in string.Formatter().parse(value) if name}
        for key in english:
            self.assertEqual(fields(english[key]), fields(chinese[key]), key)

    def test_cli_config_without_lxd_and_preserves_other_preferences(self):
        config.path().parent.mkdir(parents=True)
        config.path().write_text('{"future_setting": 42}')
        with patch("mas.cli.LXD", side_effect=AssertionError("must not initialize LXD")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["config", "set", "language", "zh_cn"]), 0)
            self.assertEqual(main(["config", "get", "language"]), 0)
            self.assertEqual(main(["config"]), 0)
        self.assertIn("zh_cn", output.getvalue())
        self.assertEqual(config.load()["future_setting"], 42)
        self.assertEqual(config.language(), "zh_cn")
        self.assertIn("管理", t("cli_description"))
        with self.assertRaises(config.ConfigError):
            config.set_value("language", "zh_CN")
        with self.assertRaises(config.ConfigError):
            config.get("not-a-setting")

    def test_install_language_prompt_uses_saved_default(self):
        config.set_value("language", "zh_cn")
        ask = Mock(return_value="")
        self.assertEqual(choose_language(ask=ask), "zh_cn")
        self.assertIn("[zh_cn]", ask.call_args.args[0])
        self.assertEqual(choose_language("en_us"), "en_us")

    def test_broken_config_is_not_overwritten(self):
        config.path().parent.mkdir(parents=True)
        config.path().write_text("broken")
        with self.assertRaises(config.ConfigError):
            config.set_value("language", "zh_cn")
        self.assertEqual(config.path().read_text(), "broken")

    def test_chinese_progress_and_display_width(self):
        config.set_value("language", "zh_cn")
        text = progress_text(dict(status="waiting", action="start", target="test-abc",
                                  observation="Running", elapsed=1.2))
        self.assertIn("1.2", text)
        self.assertNotIn("Running", text)
        self.assertEqual(cells("a中文e\u0301"), 6)

    def test_ready_system_needs_no_sudo(self):
        from mas.install import prepare_system
        import grp
        from types import SimpleNamespace
        original = Path.read_text
        def read(path, *args, **kwargs):
            if str(path) == "/etc/os-release": return "ID=ubuntu\n"
            if str(path) == "/proc/1/comm": return "systemd\n"
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", read), \
                patch("mas.install.shutil.which", return_value="/snap/bin/lxd"), \
                patch("mas.install.os.geteuid", return_value=1000), \
                patch("mas.install.os.getgid", return_value=1000), \
                patch("mas.install.os.getgroups", return_value=[986]), \
                patch("mas.install.pwd.getpwuid", return_value=SimpleNamespace(pw_name="tester")), \
                patch("mas.install.grp.getgrnam", return_value=SimpleNamespace(gr_gid=986, gr_mem=["tester"])), \
                patch("mas.install.run") as run:
            self.assertFalse(prepare_system())
        run.assert_not_called()

    def test_numeric_release_resolution_and_pin(self):
        import bootstrap
        releases = [dict(tag_name=tag, draft=False, prerelease=True) for tag in
                    ("v0.1.9", "v0.1.10", "v0.1.0-test.100", "v0.1.3")]
        with patch("bootstrap.download", return_value=json.dumps(releases).encode()):
            self.assertEqual(bootstrap.release()["tag_name"], "v0.1.10")
        with patch("bootstrap.download", return_value=json.dumps(releases[0]).encode()) as download:
            bootstrap.release("0.1.9")
            self.assertTrue(download.call_args.args[0].endswith("/tags/v0.1.9"))
        with self.assertRaises(RuntimeError):
            bootstrap.release("v0.1.3-test.1")

    def test_language_selection_in_real_terminal(self):
        from mas.testing import Terminal
        import sys
        source = ("import sys;sys.path.insert(0," + repr(sys.path[0]) + ");"
                  "from mas.i18n import choose_language;print(choose_language())")
        terminal = Terminal([sys.executable, "-c", source], 300, Path(os.environ["XDG_CONFIG_HOME"]) / "terminal.log")
        try:
            terminal.expect("Language / 语言:")
            terminal.send("2\n")
            terminal.expect("zh_cn\r\n")
            terminal.finish()
            self.assertEqual(config.get("language"), "zh_cn")
        finally:
            terminal.close()
