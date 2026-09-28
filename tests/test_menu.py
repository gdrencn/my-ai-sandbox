"""Exercise actual terminal key sequences, not mocked curses key codes."""
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
            finally:
                terminal.close()

    def test_shell_return_restores_immediate_arrow_input(self):
        source = '''import curses, sys, termios
from types import SimpleNamespace
from mas import menu
from mas.tui import UI
manager = SimpleNamespace(report=None, enter=lambda target: menu.confirm('Nested exit'))
def exercise(screen):
    ui = UI(screen, manager)
    ui.enter('test-target')
    flags = termios.tcgetattr(0)[3]
    assert not flags & (termios.ICANON | termios.ECHO), flags
    return ui.view.choose('Returned menu', [('first', 'First'), ('second', 'Second')])
print('RESULT=' + curses.wrapper(exercise))
'''
        source = 'import sys;sys.path.insert(0,' + repr(sys.path[0]) + ')\n' + source
        with tempfile.TemporaryDirectory() as directory:
            terminal = Terminal([sys.executable, '-c', source], 300, Path(directory)/'nested.log')
            try:
                terminal.expect('Nested exit')
                terminal.send('\n')
                terminal.expect('Returned menu')
                terminal.send('\x1b[B\n')
                terminal.expect('RESULT=second')
                terminal.finish()
            finally:
                terminal.close()
