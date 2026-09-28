"""Installation ownership, archive boundaries, PATH and test presentation."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
import zipfile

from mas import __version__, config
from mas.install import configure_path
from mas.test_output import Output


class DistributionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name) / 'home with spaces'
        self.home.mkdir()
        env = patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.home / '.config')})
        env.start()
        self.addCleanup(env.stop)

    def test_first_install_defaults_chinese_and_saved_english_wins(self):
        from mas.i18n import choose_language
        with patch('mas.menu.interactive', side_effect=lambda callback: callback(None)), \
                patch('mas.menu.language', side_effect=lambda ui, current: current):
            self.assertEqual(choose_language(), 'zh_cn')
            config.set_value('language', 'en_us')
            self.assertEqual(choose_language(), 'en_us')

    def test_path_is_persistent_idempotent_and_quoted(self):
        profile = self.home / '.bash_profile'
        profile.write_text('export ORIGINAL_SETTING=preserved\n')
        with patch.dict(os.environ, {'PATH': '/usr/bin:/bin'}):
            configure_path(self.home, 'bash')
            once = profile.read_text()
            configure_path(self.home, 'bash')
        self.assertEqual(profile.read_text(), once)
        self.assertEqual(once.count('# >>> my-ai-sandbox PATH >>>'), 1)
        self.assertIn('ORIGINAL_SETTING=preserved', once)
        for file in (profile, self.home / '.bashrc'):
            result = subprocess.check_output(['bash', '--noprofile', '--norc', '-c',
                '. "$1"; . "$1"; printf "%s" "$PATH"', 'test', str(file)],
                env={**os.environ, 'PATH': '/usr/bin:/bin'}, text=True)
            self.assertEqual(result.split(':'), [str(self.home / '.local/bin'), '/usr/bin', '/bin'])

    def test_zsh_startup_selection(self):
        with patch.dict(os.environ, {'ZDOTDIR': str(self.home / 'zsh')}):
            configure_path(self.home, 'zsh')
        self.assertTrue((self.home / 'zsh/.zprofile').exists())
        self.assertTrue((self.home / 'zsh/.zshrc').exists())

    def test_plain_output_hides_only_progress_and_retains_diagnostics(self):
        stream = io.StringIO()
        output = Output(stream)
        output.progress('normal tick')
        output.diagnostics('WARNING: native warning\nnormal data\n',
                           '[waiting] start demo: Running — waited 1.0s\n[错误] 创建 demo：不存在 — 已等待 1.0 秒\nunknown diagnostic\n')
        output.keep('stage passed')
        value = stream.getvalue()
        self.assertNotIn('normal tick', value)
        self.assertNotIn('normal data', value)
        self.assertNotIn('waited', value)
        self.assertNotIn('\033', value)
        self.assertIn('WARNING: native warning', value)
        self.assertIn('unknown diagnostic', value)
        self.assertIn('[错误]', value)
        self.assertIn('stage passed', value)

    def test_interactive_progress_cleared_before_summary(self):
        stream = io.StringIO()
        stream.isatty = lambda: True
        output = Output(stream)
        output.progress('first tick')
        output.progress('second tick')
        output.keep('stage passed')
        self.assertEqual(stream.getvalue(), '\r\033[2Kfirst tick\r\033[2Ksecond tick\r\033[2Kstage passed\n')

    def test_bootstrap_downloads_tester_only_when_requested(self):
        import bootstrap
        assets = {'mas.pyz': b'product', 'mas-install.pyz': b'installer', 'mas-test.pyz': b'tester'}
        checksums = ''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in assets.items()).encode()
        release = {'tag_name': 'v'+__version__, 'assets': [dict(name=name,browser_download_url=name)
                   for name in (*assets,'SHA256SUMS')]}
        for testing in (False, True):
            def download(name):
                return checksums if name == 'SHA256SUMS' else assets[name]
            with self.subTest(testing=testing), patch.object(sys, 'argv', ['bootstrap.py','--language','zh_cn']+(['--test'] if testing else [])), \
                    patch.object(bootstrap,'release',return_value=release), patch.object(bootstrap,'download',side_effect=download) as fetch, \
                    patch.object(bootstrap.subprocess,'call',return_value=0) as call, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bootstrap.main(),0)
                names = [entry.args[0] for entry in fetch.call_args_list]
                self.assertEqual('mas-test.pyz' in names,testing)
                command=call.call_args.args[0]
                self.assertTrue(command[1].endswith('mas-test.pyz' if testing else 'mas-install.pyz'))
                self.assertEqual('--install' in command,testing)

    def test_tester_installs_before_testing_and_stops_on_install_failure(self):
        from mas.testing import install_and_test
        args=SimpleNamespace(install=Path('/tmp/installer.pyz'),product=Path('/tmp/product.pyz'),timeout=600,output=self.home/'results')
        for code in (0,1):
            calls=[]
            def execute(command):
                calls.append(command)
                return code
            with self.subTest(code=code), patch('mas.testing.subprocess.check_output',return_value=__version__+'\n'), \
                    patch('mas.testing.subprocess.call',side_effect=execute), patch('mas.install.install_file') as copy, \
                    patch('mas.install.group_refresh_required',return_value=False), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(install_and_test(args),code)
                self.assertEqual(len(calls),1 if code else 2)
                self.assertEqual(calls[0][1],str(args.install))
                if code: copy.assert_not_called()
                else: self.assertTrue(calls[1][1].endswith('/mas-test'))

    def test_installer_refreshes_using_installer_code(self):
        from mas.install import install
        with patch('mas.install.prepare_system',return_value=True), patch('mas.install.refreshed_command',side_effect=lambda c:c), \
                patch('mas.install.run') as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(install(Path('/tmp/product.pyz')),0)
        code=run.call_args.args[0][-1]
        self.assertIn('from mas.install import finish',code)
        self.assertNotIn('testing',code)

    def test_packaged_product_excludes_tests_and_installer(self):
        if not zipfile.is_zipfile(sys.argv[0]):
            self.skipTest('Archive boundary is verified by the packaged tester.')
        # The integration product is passed to the public tester at startup.
        from mas.testing import PRODUCT_UNDER_TEST
        if PRODUCT_UNDER_TEST is None:
            self.skipTest("No product archive supplied.")
        with zipfile.ZipFile(PRODUCT_UNDER_TEST) as archive:
            names=archive.namelist()
        self.assertFalse(any(name.startswith(('tests/', 'mas/locales/test/')) for name in names))
        for forbidden in ('mas/testing.py','mas/test_output.py','mas/install.py'):
            self.assertNotIn(forbidden,names)


    def test_successful_native_command_keeps_diagnostics_and_raw_output(self):
        from mas.core import Manager, MANAGED
        from mas.cli import Progress
        events=[]
        manager=Manager(Mock(prefix=[sys.executable], timeout=300), events.append)
        manager.find=Mock(return_value={"name":"demo","status":"Stopped","type":"container","config":{MANAGED:"true"}})
        manager._operation("new", "demo", ["-c", "import sys;print('normal native output');print('native notice',file=sys.stderr)"], "Stopped")
        event=events[-1]
        self.assertIn('normal native output',event['native_stdout'])
        self.assertIn('native notice',event['native_stderr'])
        with contextlib.redirect_stderr(io.StringIO()) as output:
            Progress()(event)
        self.assertIn('native notice',output.getvalue())
        self.assertNotIn('normal native output',output.getvalue())


    def test_network_retry_retains_warning_and_report_event(self):
        from mas.testing import Suite
        from mas.core import Error
        suite=Suite.__new__(Suite)
        suite.events=[]
        stream=io.StringIO()
        suite.output=Output(stream)
        suite.exec=Mock(side_effect=Error("native connection failure"))
        self.assertFalse(suite.network("test-network"))
        self.assertIn("native connection failure",stream.getvalue())
        self.assertIn("警告",stream.getvalue())
        self.assertEqual(suite.events[0]["status"],"warning")


    def test_installer_rejects_mismatched_product_before_setup(self):
        from mas.install import main
        with patch("mas.install.subprocess.check_output",return_value="0.1.3\n"), \
                patch("mas.install.install") as install, contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main(["--product","unused.pyz"]),1)
        install.assert_not_called()
        self.assertIn("安装程序与产品版本不匹配",errors.getvalue())
