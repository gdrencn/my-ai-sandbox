"""Verify persistent history and transient progress through the shared renderer."""
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from mas.cli import Progress
from mas.i18n import t
from mas.output import Output
from mas.testing import Terminal, python_command
from tests import test_menu


def event(status, **extra):
    return dict(action='new', target='test-demo', observation='Stopped',
                elapsed=2.1, status=status, **extra)


class ProgressTests(unittest.TestCase):
    def test_list_wait_in_real_terminals_preserves_results_and_diagnostics(self):
        for language in ('zh_cn', 'en_us'):
            for outcome in ('populated', 'empty', 'warning', 'failure', 'interrupt'):
                with (self.subTest(language=language, outcome=outcome),
                      tempfile.TemporaryDirectory() as directory,
                      patch.dict(os.environ, {'XDG_CONFIG_HOME': directory})):
                    source = f'''
import os, sys, termios
from types import SimpleNamespace
from mas import config
from mas.cli import main
from mas.core import Error
from mas.output import Output
config.set_value('language', {language!r})
calls = []
def listing():
    calls.append('list')
    assert termios.tcgetattr(0)[3] & termios.ICANON
    os.read(0, 1)  # Parent releases the query only after observing feedback.
    if {outcome!r} == 'interrupt':
        raise KeyboardInterrupt()
    if {outcome!r} == 'failure':
        raise Error('QUERY_FAILED')
    if {outcome!r} == 'warning':
        Output(sys.stderr).keep('NATIVE_QUERY_WARNING')
    return [] if {outcome!r} == 'empty' else [dict(name='demo', status='Stopped')]
status = main([], manager=SimpleNamespace(list=listing))
assert calls == ['list']
print('FINISHED=' + str(status), flush=True)
'''
                    terminal = Terminal(python_command(source), 30, Path(directory)/'list-wait.log')
                    tr = lambda key: t(key, locale=language)
                    try:
                        terminal.expect('my-ai-sandbox')
                        terminal.send('\n')
                        terminal.expect(tr('list_loading'))
                        terminal.send('\x04')  # Release the fixture without an echoed newline.
                        if outcome == 'interrupt':
                            terminal.expect('FINISHED=130')
                        else:
                            if outcome == 'failure':
                                terminal.expect('QUERY_FAILED')
                                terminal.expect(tr('page_result'))
                            else:
                                terminal.expect_menu(tr('page_list'))
                                terminal.expect(tr('menu_empty') if outcome == 'empty' else 'demo')
                            terminal.send('\x1b[D')
                            terminal.expect('my-ai-sandbox')
                            terminal.send('\x1b[A\n')
                            terminal.expect('FINISHED=0')
                        terminal.finish()
                        helper = test_menu.MenuTests()
                        history = helper.render_history(terminal.buffer)
                        self.assertNotIn(tr('list_loading'), history)
                        if outcome == 'warning':
                            self.assertEqual(history.count('NATIVE_QUERY_WARNING'), 1)
                        if outcome == 'failure':
                            self.assertIn('QUERY_FAILED', history)
                        if outcome == 'empty':
                            self.assertIn(tr('menu_empty'), history)
                        helper.assert_inline(terminal.buffer)
                    finally:
                        terminal.close()

    def test_scoped_wait_restores_output_boundary_and_keeps_plain_output(self):
        from mas.output import boundary
        stream = io.StringIO()
        outer = lambda: stream.write('BOUNDARY\n')
        token = boundary.set(outer)
        try:
            for failure in (None, KeyboardInterrupt()):
                try:
                    with Output(stream).waiting('READING'):
                        Output(stream).keep('DIAGNOSTIC')
                        if failure is not None:
                            raise failure
                except KeyboardInterrupt:
                    pass
                self.assertIs(boundary.get(), outer)
            self.assertEqual(stream.getvalue(), 'BOUNDARY\nDIAGNOSTIC\n' * 2)
        finally:
            boundary.reset(token)

    def test_plain_stream_keeps_results_and_diagnostics_only(self):
        with patch('mas.config.language', return_value='en_us'):
            stream = io.StringIO()
            report = Progress(stream)
            report(event('waiting'))
            report(event('ok', native_stderr='native notice', native_stdout='WARNING: notice'))
            report(event('error', native_failure=True, native_stderr='handled by caller'))
        text = stream.getvalue()
        self.assertNotIn('\x1b', text)
        self.assertNotIn('[waiting]', text)
        self.assertIn('[ok]', text)
        self.assertIn('[Error]', text)
        self.assertIn('native notice', text)
        self.assertIn('WARNING: notice', text)
        self.assertNotIn('handled by caller', text)

    def test_localized_narrow_line_does_not_wrap(self):
        stream = io.StringIO()
        stream.isatty = lambda: True
        output = Output(stream)
        with patch('mas.output.shutil.get_terminal_size', return_value=os.terminal_size((8, 24))):
            output.progress('中文中文等待')
        self.assertEqual(stream.getvalue(), '\r\x1b[2K中文中')
        output.keep('完成')
        self.assertTrue(stream.getvalue().endswith('\r\x1b[2K完成\n'))

    def test_query_warning_without_newline_survives_refresh(self):
        from mas.core import LXD
        stream = io.StringIO()
        stream.isatty = lambda: True
        report = Progress(stream)
        with patch('mas.core.shutil.which', return_value='/fake/lxc'):
            lxd = LXD(diagnostic=report.output.keep)
        report(event('waiting'))
        with patch('mas.core.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='[]', stderr='QUERY_WARNING')):
            self.assertEqual(lxd.instances(), [])
        report(event('waiting'))
        report(event('ok'))
        history = test_menu.MenuTests().render_history(stream.getvalue().encode())
        self.assertIn('QUERY_WARNING', history)
        self.assertNotIn('[等待中]', history)

    def test_live_install_region_clears_normal_logs_and_preserves_warning(self):
        source = """
import sys
from mas.presentation import Progress
report=Progress()
def event(status, **extra):
    return dict(action='prepare-user',target='fixture',status=status,scope='native',
                observation='Running',elapsed=1,**extra)
report(event('waiting',live_lines=['Unpacking nodejs fixture','Setting up npm fixture']))
report(event('waiting',live_lines=['Setting up npm fixture','Processing triggers fixture']))
report(event('ok',live_output=True,native_stdout='Setting up npm fixture\\nWARNING: fixture diagnostic'))
print('CREATION_COMPLETED', flush=True)
"""
        with tempfile.TemporaryDirectory() as directory:
            terminal=Terminal(python_command(source),300,Path(directory)/'live.log')
            try:
                terminal.expect('CREATION_COMPLETED');terminal.finish()
                raw=terminal.buffer
                self.assertIn(b'Unpacking nodejs fixture',raw)
                history=test_menu.MenuTests().render_history(raw)
                for text in ('Unpacking nodejs fixture','Setting up npm fixture','Processing triggers fixture'):
                    self.assertNotIn(text,history)
                self.assertIn('WARNING: fixture diagnostic',history)
                self.assertIn('CREATION_COMPLETED',history)
                test_menu.MenuTests().assert_inline(raw)
            finally:terminal.close()

    def test_width_uses_actual_output_terminal(self):
        stream = io.StringIO()
        stream.isatty = lambda: True
        stream.fileno = lambda: 17
        with patch('mas.output.os.get_terminal_size', return_value=os.terminal_size((5, 24))) as size:
            Output(stream).progress('abcdefgh')
        size.assert_called_once_with(17)
        self.assertEqual(stream.getvalue(), '\r\x1b[2Kabcd')

    def test_pty_waits_disappear_but_results_errors_and_menus_survive(self):
        source = '''
from mas.cli import main, Progress
from mas import menu
from mas.core import Error
from unittest.mock import Mock
report = Progress()
def new(*args):
    for status in ('waiting', 'waiting', 'ok'):
        report(dict(action='new', target='test-demo', observation='Stopped', elapsed=2, status=status,
                    native_stderr='NATIVE_WARNING' if status == 'ok' else ''))
manager = Mock(new=new)
assert main(['new', 'test-demo'], manager=manager) == 0
menu.interactive(lambda ui: ui.choose('NEXT_MENU', [('back', 'BACK')]))
def broken(*args):
    try:
        report(dict(action='start', target='test-demo', observation='Stopped', elapsed=1, status='waiting'))
        raise KeyboardInterrupt()
    finally:
        report(dict(action='start', target='test-demo', observation='Stopped', elapsed=2, status='error'))
manager.start = broken
assert main(['start', 'test-demo'], manager=manager) == 130
print('AFTER_INTERRUPT')
'''
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            terminal = Terminal(python_command(source), 300, Path(directory)/'progress.log')
            try:
                terminal.expect('NEXT_MENU')
                terminal.send('\n')
                terminal.expect('AFTER_INTERRUPT')
                terminal.finish()
                helper = test_menu.MenuTests()
                history = helper.render_history(terminal.buffer)
                self.assertNotIn('[等待中]', history)
                self.assertIn('[成功]', history)
                self.assertIn('[错误]', history)
                self.assertIn('NATIVE_WARNING', history)
                self.assertIn('NEXT_MENU', history)
                self.assertIn('AFTER_INTERRUPT', history)
                helper.assert_inline(terminal.buffer)
            finally:
                terminal.close()
