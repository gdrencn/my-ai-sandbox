"""Exercise actual terminal key sequences, including inline rendering and terminal modes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from mas import config, menu
from mas.testing import Terminal


class MenuTests(unittest.TestCase):
    def terminal_case(self, expression, keys, expected):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            config.set_value('language', 'en_us')
            source = ('import sys,json;sys.path.insert(0,' + repr(sys.path[0]) + ');'
                      'from mas import menu;result=menu.interactive(lambda ui:' + expression + ');'
                      'print("RESULT="+json.dumps(result))')
            terminal = Terminal([sys.executable, '-c', source], 300, Path(directory)/'pty.log')
            try:
                terminal.expect('English (en_us)' if 'language' in expression else 'Menu test')
                terminal.send(keys)
                terminal.expect('RESULT=' + json.dumps(expected))
                terminal.finish()
                self.assert_inline(terminal.buffer)
            finally:
                terminal.close()

    def test_csi_language_radio_and_saved_default(self):
        self.terminal_case("menu.language(ui, 'zh_cn')", '\x1b[B\n', 'en_us')
        self.terminal_case("menu.language(ui, 'en_us')", '\n', 'en_us')

    def test_ss3_up_and_chinese_default(self):
        self.terminal_case("menu.language(ui, 'zh_cn')", '\n', 'zh_cn')
        self.terminal_case("menu.language(ui, 'en_us')", '\x1bOA\n', 'zh_cn')

    def test_multi_select_space_toggles_independent_of_focus(self):
        self.terminal_case("ui.choose('Menu test', [('a','A'),('b','B'),('c','C')], multiple=True)",
                           ' \x1bOB \x1b[B\n', ['a','b'])

    def test_confirm_defaults_no_escape_and_explicit_yes(self):
        self.terminal_case("ui.confirm('Menu test')", '\n', False)
        self.terminal_case("ui.confirm('Menu test')", '\x1b', False)
        self.terminal_case("ui.confirm('Menu test')", '\x1b[B\n', True)

    def test_wrap_navigation_in_real_terminal(self):
        options = "ui.choose('Menu test', [('a','A'),('b','B'),('c','C')])"
        self.terminal_case(options, '\x1b[A\n', 'c')
        self.terminal_case(options, '\x1b[B' * 3 + '\n', 'a')
        self.terminal_case("ui.choose('Menu test', [('a','A')])", '\x1b[A\x1b[B\n', 'a')
        self.terminal_case("ui.confirm('Menu test')", '\x1b[A\n', True)
        self.terminal_case("ui.choose('Menu test', [('a','A'),('b','B'),('c','C')], multiple=True)",
                           ' \x1b[A \x1b[B\n', ['a', 'c'])

    def test_function_failure_stays_visible_until_explicit_return(self):
        source = """import sys
from mas import menu, config
from mas.core import Error
from mas.terminal_ui import UI
config.set_value('language', 'en_us')
def failure():
    raise Error('NATIVE_FAILURE_SENTINEL')
def exercise(view):
    UI(view, None).present('ACTION_TITLE', failure)
    print('PARENT_MENU', flush=True)
menu.interactive(exercise)
"""
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            source = 'import sys;sys.path.insert(0,' + repr(sys.path[0]) + ')\n' + source
            terminal = Terminal([sys.executable, '-c', source], 300, Path(directory)/'failure.log')
            try:
                terminal.expect('NATIVE_FAILURE_SENTINEL')
                terminal.expect('Operation result')
                terminal.read()
                self.assertNotIn(b'PARENT_MENU', terminal.buffer)
                terminal.send('\n')
                terminal.expect('PARENT_MENU'); terminal.finish()
                self.assert_inline(terminal.buffer)
                history = self.render_history(terminal.buffer)
                self.assertLess(history.index('ACTION_TITLE'), history.index('NATIVE_FAILURE_SENTINEL'))
                self.assertLess(history.index('NATIVE_FAILURE_SENTINEL'), history.index('Operation result'))
                self.assertLess(history.index('Operation result'), history.index('PARENT_MENU'))
            finally:
                terminal.close()

    def test_text_backspace(self):
        self.terminal_case("ui.input('Menu test')", 'abc\x7fd\n', 'abd')

    def test_nonterminal_confirmation_declines(self):
        with patch('mas.menu.sys.stdin.isatty', return_value=False):
            self.assertFalse(menu.confirm('No terminal'))

    def test_explicit_cli_consent_is_mutually_exclusive(self):
        from mas.cli import parser
        for command in ('delete', 'export', 'enter'):
            args = [command, 'test-target'] + (['backup.tar.gz'] if command == 'export' else [])
            self.assertTrue(parser().parse_args(args + ['--yes']).consent)
            self.assertFalse(parser().parse_args(args + ['--no']).consent)
            with patch('sys.stderr'), self.assertRaises(SystemExit):
                parser().parse_args(args + ['--yes', '--no'])

    def test_resize_keeps_selection_and_viewport_valid(self):
        import fcntl
        import signal
        import struct
        import termios
        with tempfile.TemporaryDirectory() as directory:
            source = ('import sys,json;sys.path.insert(0,' + repr(sys.path[0]) + ');from mas import menu;'
                      'result=menu.interactive(lambda ui:ui.choose("Resize menu",[(i,str(i)) for i in range(30)]));'
                      'print("RESULT="+str(result))')
            terminal = Terminal([sys.executable, '-c', source], 300, Path(directory)/'resize.log')
            try:
                terminal.expect('Resize menu')
                fcntl.ioctl(terminal.fd, termios.TIOCSWINSZ, struct.pack('HHHH', 8, 32, 0, 0))
                os.kill(terminal.pid, signal.SIGWINCH)
                terminal.send('\x1b[B' * 25 + '\n')
                terminal.expect('RESULT=25')
                terminal.finish()
                self.assert_inline(terminal.buffer)
            finally:
                terminal.close()

    def test_shell_and_operations_receive_normal_terminal_mode(self):
        source = """import sys, termios
from types import SimpleNamespace
from mas import menu
from mas.terminal_ui import UI, LeaveMenu
original = termios.tcgetattr(0)
def shell(target):
    assert termios.tcgetattr(0) == original
    print('SHELL_OUTPUT', flush=True)
    menu.confirm('Exit confirmation')
    assert termios.tcgetattr(0) == original
manager = SimpleNamespace(enter=shell)
def exercise(view):
    view.choose('Before operation', [('go', 'Go')])
    assert termios.tcgetattr(0) == original
    try:
        UI(view, manager).enter('test-target')
    except LeaveMenu:
        assert termios.tcgetattr(0) == original
        return 'host'
    raise AssertionError('Menu should have exited')
print('HISTORY_SENTINEL', end='', flush=True)
print('RESULT=' + menu.interactive(exercise))
"""
        source = 'import sys;sys.path.insert(0,' + repr(sys.path[0]) + ')\n' + source
        with tempfile.TemporaryDirectory() as directory:
            terminal = Terminal([sys.executable, '-c', source], 300, Path(directory)/'return.log')
            try:
                terminal.expect('Before operation')
                terminal.send('\n')
                terminal.expect('Exit confirmation')
                terminal.send('\n')
                terminal.expect('RESULT=host')
                self.assertNotIn(b'Returned menu', terminal.buffer)
                terminal.finish()
                self.assert_inline(terminal.buffer)
                self.assertIn(b'HISTORY_SENTINEL', terminal.buffer)
                self.assertIn(b'SHELL_OUTPUT', terminal.buffer)
                history = self.render_history(terminal.buffer)
                self.assertIn('HISTORY_SENTINEL', history)
                self.assertIn('SHELL_OUTPUT', history)
                self.assertIn('Before operation', history)
                self.assertIn('Exit confirmation', history)
            finally:
                terminal.close()

    def assert_inline(self, output):
        for forbidden in (b'\x1b[?1049', b'\x1b[?1047', b'\x1b[?47', b'\x1b[2J', b'\x1b[3J', b'\x1b[H'):
            self.assertNotIn(forbidden, output)

    def test_unicode_and_cursor_editing(self):
        self.terminal_case("ui.input('Menu test')", '中文ab\x1b[D\x7fX\n', '中文Xb')

    def test_cancel_and_interrupt_restore_terminal(self):
        for key in ('\x1b', '\x03'):
            source = """import termios
from mas import menu
original = termios.tcgetattr(0)
try:
    menu.interactive(lambda ui: ui.input('Mode check'))
except (menu.Cancelled, KeyboardInterrupt):
    pass
assert termios.tcgetattr(0) == original
print('RESTORED')
"""
            source = 'import sys;sys.path.insert(0,' + repr(sys.path[0]) + ')\n' + source
            with tempfile.TemporaryDirectory() as directory:
                terminal = Terminal([sys.executable, '-c', source], 300, Path(directory)/'mode.log')
                try:
                    terminal.expect('Mode check')
                    terminal.send(key)
                    terminal.expect('RESTORED')
                    terminal.finish()
                    self.assert_inline(terminal.buffer)
                finally:
                    terminal.close()

    def render_history(self, output):
        # Interpret the inline renderer's row movement/erasure to ensure earlier
        # output survives on screen, not merely somewhere in a raw transcript.
        import re
        rows, row, column = [''], 0, 0
        for token in re.split(r'(\x1b\[[0-?]*[ -/]*[@-~])', output.decode()):
            if token.startswith('\x1b['):
                if token.endswith('A'):
                    row -= int(token[2:-1] or 1)
                    self.assertGreaterEqual(row, 0)
                elif token == '\x1b[2K':
                    rows[row] = ''
                continue
            for char in token:
                if char == '\r':
                    column = 0
                elif char == '\n':
                    row += 1
                    while row >= len(rows):
                        rows.append('')
                else:
                    line = rows[row].ljust(column)
                    rows[row] = line[:column] + char + line[column+1:]
                    column += 1
        return '\n'.join(rows)
