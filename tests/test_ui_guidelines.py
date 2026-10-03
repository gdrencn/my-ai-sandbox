"""Native output and real-terminal contracts for the shared CLI/TUI components."""
import contextlib
import io
from importlib.resources import files
import os
from pathlib import Path
import re
import shlex
import struct
import sys
import tempfile
import termios
import fcntl
import unittest
from unittest.mock import Mock, patch
import zipfile

from mas import config
from mas.cli import main
from mas.diagnostics import diagnostic_lines
from mas.install import dependency_script
from mas.presentation import Progress
from mas.test_output import Output
from mas.testing import Terminal, python_command
from tests import test_menu


class GuidelineTests(unittest.TestCase):
    def test_apt_prefix_diagnostics_survive_product_and_tester_success(self):
        sample = 'W: Target Packages is configured multiple times\nE: Native detail\nErr: repository detail'
        self.assertEqual(diagnostic_lines(sample, ''), sample.splitlines())
        for language in ('zh_cn', 'en_us'):
            with patch('mas.config.language', return_value=language):
                for reporter in ('product', 'tester'):
                    stream = io.StringIO(); stream.isatty = lambda: True
                    output = Progress(stream) if reporter == 'product' else Output(stream)
                    if reporter == 'product':
                        event = dict(action='prepare-user', target='fixture', status='waiting', scope='native',
                                     observation='Running', elapsed=1, live_lines=['Setting up fixture'])
                        output(event)
                        output({**event, 'status': 'ok', 'native_stdout': sample, 'live_output': True})
                        output.output.keep('DONE')
                    else:
                        output.progress('Setting up fixture'); output.diagnostics(sample, ''); output.keep('DONE')
                    history = test_menu.MenuTests().render_history(stream.getvalue().encode())
                    self.assertNotIn('Setting up fixture', history)
                    for line in sample.splitlines():
                        self.assertEqual(history.count(line), 1)

    def test_cli_list_reuses_columns_with_complete_names_and_plain_redirected_output(self):
        for language in ('zh_cn', 'en_us'):
            stream = io.StringIO()
            manager = Mock(); manager.list.return_value = [
                dict(name='long-container-name', status='Stopped'), dict(name='a', status='Running')]
            with patch('mas.config.language', return_value=language), contextlib.redirect_stdout(stream):
                self.assertEqual(main(['list'], manager=manager), 0)
            lines = stream.getvalue().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(len(lines[0].split()[0]), len('long-container-name'))
            self.assertEqual(re.search(r'\S+$', lines[0]).start(), re.search(r'\S+$', lines[1]).start())
            self.assertNotIn('\t', stream.getvalue()); self.assertNotIn('\x1b', stream.getvalue())
            manager.list.assert_called_once_with()

    def test_python_language_cancel_has_feedback_and_130_without_downloading(self):
        for language in ('zh_cn', 'en_us'):
            with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
                config.set_value('language', language)
                source = "import sys,runpy;sys.argv=['bootstrap.py'];runpy.run_module('bootstrap',run_name='__main__')"
                terminal = Terminal(python_command(source), 30, Path(directory)/'cancel.log')
                try:
                    terminal.expect('Esc'); terminal.send('\x1b'); terminal.finish(status=130)
                    text = terminal.buffer.decode()
                    self.assertIn('已取消' if language == 'zh_cn' else 'Cancelled.', text)
                    self.assertNotIn('安装失败' if language == 'zh_cn' else 'Installation failed', text)
                    self.assertNotIn('正在安装', text)
                    self.assertIn(b'\x1b[?25h', terminal.buffer)
                finally: terminal.close()

    def bootstrap_source(self):
        if zipfile.is_zipfile(sys.argv[0]):
            with zipfile.ZipFile(sys.argv[0]) as archive:
                return archive.read('install.sh').decode()
        return (Path(__file__).resolve().parents[1]/'install.sh').read_text()

    def test_pre_python_cancel_and_narrow_terminal_fail_before_setup(self):
        for narrow in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                script = Path(directory)/'bootstrap.sh'; script.write_text(self.bootstrap_source())
                source = "command() { if [[ $1 == -v && $2 == python3 ]]; then return 1; fi; builtin command \"$@\"; }; export -f command; exec bash " + shlex.quote(str(script))
                if narrow:
                    source = 'stty cols 20 rows 4; ' + source
                terminal = Terminal(['bash', '-c', source], 30, Path(directory)/'fallback.log')
                try:
                    if narrow:
                        terminal.finish(status=1)
                        self.assertIn('--language', terminal.buffer.decode())
                    else:
                        terminal.expect('Esc'); terminal.send('\x1b'); terminal.finish(status=130)
                        self.assertIn('已取消', terminal.buffer.decode())
                        self.assertIn(b'\x1b[?25h', terminal.buffer)
                    self.assertNotIn(b'apt-get', terminal.buffer)
                finally: terminal.close()

    def test_settings_gpu_and_network_have_one_entry_title_in_real_terminals(self):
        for language in ('zh_cn', 'en_us'):
            for item in ('language', 'gpu', 'network'):
                with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
                    config.set_value('language', language)
                    source = '''
from mas import menu
from mas.terminal_ui import UI
class Manager:
    def hardware(self,*args,**kwargs):
        return dict(available=True,enabled=True,configured=True)
def run(view):
    ui=UI(view,Manager())
    ui.settings() if ITEM == 'language' else ui.hardware('demo')
menu.interactive(run)
print('DONE',flush=True)
'''.replace('ITEM', repr(item))
                    terminal = Terminal(python_command(source), 30, Path(directory)/'titles.log')
                    try:
                        terminal.expect('Esc')
                        terminal.send(('\x1b[B' if item == 'network' else '')+'\n')
                        from mas.i18n import t
                        title = t('language_title' if item == 'language' else item+'_choose')
                        terminal.expect(title); terminal.expect('Esc'); terminal.send('\x1b')
                        terminal.expect(t('page_result')); terminal.expect('Esc'); terminal.send('\n')
                        terminal.expect('Esc'); terminal.send('\x1b[B\n' if item == 'network' else '\x1b[A\n')
                        terminal.expect('DONE'); terminal.finish()
                        history = test_menu.MenuTests().render_history(terminal.buffer)
                        # Option labels can contain the text; entry titles are complete lines.
                        self.assertEqual(history.splitlines().count(title), 1, history)
                    finally: terminal.close()

    def test_query_feedback_precedes_delayed_queries_and_clears_on_all_outcomes(self):
        for language in ('zh_cn', 'en_us'):
            for task, loading, method in (('info','info_loading','info'), ('hardware','hardware_loading','hardware'),
                                          ('migration','migration_loading','legacy_list'), ('filesystem','fs_list_loading','mountedfs')):
                for fail in (False, True):
                    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
                        config.set_value('language', language)
                        source = '''
import sys,termios
from mas import menu
from mas.core import Error
from mas.terminal_ui import UI
from tests.test_menu_refinements import MenuFixture
manager=MenuFixture();original=getattr(manager,METHOD);calls=0
saved_mode=termios.tcgetattr(0);changed_mode=termios.tcgetattr(0);changed_mode[3]&=~termios.ECHO
termios.tcsetattr(0,termios.TCSANOW,changed_mode)
def delayed(*args,**kwargs):
    global calls
    calls+=1
    if calls==1:
        assert sys.stdin.readline().strip()=='RELEASE'
        if FAIL: raise Error('NATIVE_QUERY_FAILED')
    return original(*args,**kwargs)
setattr(manager,METHOD,delayed)
def run(view):
    ui=UI(view,manager)
    ui.present('TASK',lambda:ui.migration() if TASK=='migration' else getattr(ui,TASK)('demo'),back=False)
try:menu.interactive(run)
finally:termios.tcsetattr(0,termios.TCSANOW,saved_mode)
print('DONE',flush=True)
'''
                        source = 'METHOD='+repr(method)+';FAIL='+str(fail)+';TASK='+repr(task)+'\n'+source
                        terminal = Terminal(python_command(source), 30, Path(directory)/'query.log')
                        try:
                            if task == 'filesystem':
                                terminal.expect('Esc'); terminal.send('\n')
                            from mas.i18n import t
                            message = t(loading, **({} if task == 'migration' else {'target':'demo'}))
                            terminal.expect(message)
                            terminal.send('RELEASE\n')
                            if fail or task == 'filesystem':
                                terminal.expect(t('page_result'))
                            terminal.expect('Esc')
                            terminal.send('\n' if fail or task == 'filesystem' else '\x1b[D')
                            if task == 'filesystem':
                                terminal.expect('Esc'); terminal.send('\x1b[A\n')
                            terminal.expect('DONE'); terminal.finish()
                            history = test_menu.MenuTests().render_history(terminal.buffer)
                            self.assertNotIn(message,history)
                            if fail: self.assertIn('NATIVE_QUERY_FAILED',history)
                        finally: terminal.close()

    def test_shared_apt_renderer_handles_unicode_resize_and_preserves_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            command = dependency_script()+r'''
{ printf 'Unpacking 中文中文中文中文 package'; sleep .15; printf '\nW: Target Packages is configured multiple times\n'; printf 'Native question: '; sleep .2; printf '\nSetting up fixture\n'; } | mas_apt_render
printf 'DONE\n'
'''
            terminal = Terminal(['bash','-c','stty cols 25; '+command],30,Path(directory)/'apt.log')
            try:
                terminal.expect('Unpacking')
                fcntl.ioctl(terminal.fd,termios.TIOCSWINSZ,struct.pack('HHHH',40,18,0,0))
                terminal.expect('Native question: '); terminal.expect('DONE'); terminal.finish()
                self.assertIn('W: Target Packages is configured multiple times',terminal.buffer.decode())
                self.assertNotIn(b'\t',terminal.buffer)
                test_menu.MenuTests().assert_inline(terminal.buffer)
            finally: terminal.close()

    def test_cli_empty_list_reports_empty_without_progress_or_control_codes(self):
        for language in ('zh_cn', 'en_us'):
            manager=Mock();manager.list.return_value=[]
            out,err=io.StringIO(),io.StringIO()
            with patch('mas.config.language',return_value=language), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(main(['list'],manager=manager),0)
                from mas.i18n import t
                self.assertEqual(out.getvalue(),t('menu_empty')+'\n')
            self.assertEqual(err.getvalue(),'')

    def test_secondary_diagnostics_clear_another_reporters_active_row(self):
        from mas.diagnostics import warn
        stream=io.StringIO();stream.isatty=lambda:True
        with patch('sys.stderr',stream):
            progress=Progress(stream)
            progress.output.progress('OLD_WAIT')
            warn('cleanup_secondary',RuntimeError('NATIVE_SECONDARY_DETAIL'))
            progress.output.progress('NEW_WAIT')
            Output(stream).keep('DONE')
        history=test_menu.MenuTests().render_history(stream.getvalue().encode())
        self.assertNotIn('OLD_WAIT',history);self.assertNotIn('NEW_WAIT',history)
        self.assertEqual(history.count('NATIVE_SECONDARY_DETAIL'),1)
        self.assertTrue(history.endswith('DONE\n'))

    def test_pre_python_apt_adapter_preserves_unicode_and_native_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            script=files('mas').joinpath('dependencies.sh').read_text()+r'''
{ printf 'Unpacking ascii-package\n'; printf 'Unpacking 中文组件\nW: native repository detail\n'; } | mas_apt_render
printf 'DONE\n'
'''
            terminal=Terminal(['bash','-c','stty cols 20; '+script],30,Path(directory)/'adapter.log')
            try:
                terminal.expect('DONE');terminal.finish()
                history=test_menu.MenuTests().render_history(terminal.buffer)
                self.assertNotIn('Unpacking ascii-package',history)
                self.assertEqual(history.count('Unpacking 中文组件'),1)
                self.assertEqual(history.count('W: native repository detail'),1)
                test_menu.MenuTests().assert_inline(terminal.buffer)
            finally:terminal.close()

    def test_apt_crlf_preserves_package_list_context_across_read_boundaries(self):
        for script in (dependency_script(),files('mas').joinpath('dependencies.sh').read_text()):
            source=script+r'''
{ printf 'The following NEW packages will be installed:\r'; sleep .15; printf '\n  fixture\r'; sleep .15; printf '\nW: native detail\r\n'; } | mas_apt_render
'''
            import subprocess
            result=subprocess.run(['bash','-c',source],text=True,capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'W: native detail\n')
            self.assertNotIn('\x1b',result.stdout+result.stderr)
