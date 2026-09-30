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
from mas.output import Output
from mas.testing import Terminal, python_command
from tests import test_menu


def event(status, **extra):
    return dict(action='new', target='test-demo', observation='Stopped',
                elapsed=2.1, status=status, **extra)


class ProgressTests(unittest.TestCase):
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
