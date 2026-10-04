"""Real PTY resize regressions assert displayed history as well as input results."""
import fcntl
import os
from pathlib import Path
import struct
import tempfile
import termios
import unittest
from unittest.mock import patch

from mas import config
from mas.i18n import t
from mas.testing import Terminal, python_command
from tests import test_menu


class MenuResizeTests(unittest.TestCase):
    def resize(self, terminal, width, height, text):
        start = len(terminal.buffer)
        fcntl.ioctl(terminal.fd, termios.TIOCSWINSZ, struct.pack('HHHH', height, width, 0, 0))
        terminal.cursor = start
        terminal.expect(text)

    def exercise(self, expression, initial, changes, keys, expected, checks, edit=''):
        source = '''import sys,termios
from mas import menu
original=termios.tcgetattr(0)
print('HISTORY_BEFORE_MENU',flush=True)
try:
    result=menu.interactive(lambda ui:EXPRESSION)
    print('RESULT='+str(result),flush=True)
except menu.Cancelled:
    print('CANCELLED',flush=True)
except KeyboardInterrupt:
    print('INTERRUPTED',flush=True)
assert termios.tcgetattr(0)==original
print('MODE_RESTORED',flush=True)
'''.replace('EXPRESSION', expression)
        with tempfile.TemporaryDirectory() as directory:
            terminal = Terminal(python_command(source), 30, Path(directory)/'resize.log')
            try:
                terminal.expect(initial)
                if edit:
                    terminal.send(edit)
                    terminal.expect(edit + '▏')
                for width, height, marker in changes:
                    self.resize(terminal, width, height, marker)
                    history = test_menu.MenuTests().render_history(terminal.buffer)
                    self.assertEqual(history.count('HISTORY_BEFORE_MENU'), 1, history)
                    for label, count in checks:
                        self.assertEqual(history.count(label), count, history)
                terminal.send(keys)
                terminal.expect(expected)
                terminal.expect('MODE_RESTORED')
                terminal.finish()
                test_menu.MenuTests().assert_inline(terminal.buffer)
                self.assertIn(b'\x1b[?25h', terminal.buffer)
                return test_menu.MenuTests().render_history(terminal.buffer)
            finally:
                terminal.close()

    def test_language_resize_replaces_active_block_without_keypress(self):
        for language in ('zh_cn', 'en_us'):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
                config.set_value('language', language)
                footer=t('menu_keys', action=t('menu_cancel'))
                history=self.exercise("menu.language(ui,'en_us')", footer,
                    [(100,30,footer),(180,48,footer),(100,30,footer),(160,42,footer)],
                    '\n','RESULT=en_us',[(t('language_title'),1),('English (en_us)',1),(t('language_zh'),1),(footer,1)])
                self.assertEqual(history.count(t('language_title')),1)

    def test_shorter_viewport_removes_old_rows_and_preserves_multiple_selection(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            config.set_value('language','en_us')
            footer=t('menu_multi_keys', action=t('menu_cancel'))
            # Only the final six options remain in the seven-row active viewport.
            expression="ui.choose('VIEWPORT_TITLE',[(str(i),'OPTION_'+str(i)) for i in range(8)],default='7',multiple=True,checked=['2'])"
            history=self.exercise(expression,footer,[(100,8,footer)],' \n',"RESULT=['2', '7']",
                [('VIEWPORT_TITLE',1),('OPTION_7',1),(footer,1)])
            self.assertEqual(history.count('OPTION_7'),1)

    def test_shorter_active_block_erases_obsolete_rows(self):
        source='''import termios
from mas import menu
original=termios.tcgetattr(0)
print('HISTORY_BEFORE_MENU',flush=True)
def exercise(ui):
    with ui.prompt():
        ui.write('BLOCK_TITLE\\n')
        ui.draw([('OLD_ROW_'+str(i),False) for i in range(7)]+[('ACTIVE_ROW',True)])
        while ui.key()!='resize':pass
        ui.draw([('ACTIVE_ROW',True),('NEW_HINT',False)])
        while ui.key()!='activate':pass
menu.interactive(exercise)
assert termios.tcgetattr(0)==original
print('MODE_RESTORED',flush=True)
'''
        with tempfile.TemporaryDirectory() as directory:
            terminal=Terminal(python_command(source),30,Path(directory)/'block.log')
            try:
                terminal.expect('ACTIVE_ROW')
                self.resize(terminal,180,48,'NEW_HINT')
                history=test_menu.MenuTests().render_history(terminal.buffer)
                self.assertNotIn('OLD_ROW_',history)
                for label in ('HISTORY_BEFORE_MENU','BLOCK_TITLE','ACTIVE_ROW','NEW_HINT'):
                    self.assertEqual(history.count(label),1,history)
                terminal.send('\n');terminal.expect('MODE_RESTORED');terminal.finish()
                test_menu.MenuTests().assert_inline(terminal.buffer)
            finally:terminal.close()

    def test_input_and_cancel_interrupt_keep_edit_position_and_restore_terminal(self):
        for language in ('zh_cn','en_us'):
            for keys,expected in [('\x1b[D\x7fX\n','RESULT=中文Xb'),('\x1b','CANCELLED'),('\x03','INTERRUPTED')]:
                with self.subTest(language=language,expected=expected), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'XDG_CONFIG_HOME':directory}):
                    config.set_value('language',language)
                    source="ui.input('INPUT_TITLE')"
                    footer=t('input_keys')
                    history=self.exercise(source,footer,[(100,30,footer),(180,48,footer),(110,35,footer)],keys,expected,
                        [('INPUT_TITLE',1),('中文ab▏',1),(footer,1)],edit='中文ab')
                    self.assertEqual(history.count('INPUT_TITLE'),1)

    def test_short_window_hint_is_kept_once_after_clearing_old_activity(self):
        source='''import fcntl,struct,termios
from mas import menu
print('HISTORY_BEFORE_MENU',flush=True)
def exercise(ui):
    with ui.prompt():
        ui.draw([('OLD_ACTIVITY',False)])
        fcntl.ioctl(ui.fd,termios.TIOCSWINSZ,struct.pack('HHHH',4,20,0,0))
        hint='HINT '+('detail '*15)
        ui.draw([('NEW_ACTIVITY',True)]+ui.instructions(hint))
        while ui.key()!='resize':pass
        ui.draw([('NEW_ACTIVITY',True)]+ui.instructions(hint))
        while ui.key()!='activate':pass
menu.interactive(exercise)
print('DONE',flush=True)
'''
        with tempfile.TemporaryDirectory() as directory:
            terminal=Terminal(python_command(source),30,Path(directory)/'hint.log')
            try:
                terminal.expect('NEW_ACTIVITY')
                self.resize(terminal,100,30,'NEW_ACTIVITY')
                history=test_menu.MenuTests().render_history(terminal.buffer)
                self.assertNotIn('OLD_ACTIVITY',history)
                for label in ('HISTORY_BEFORE_MENU','HINT','NEW_ACTIVITY'):
                    self.assertEqual(history.count(label),1,history)
                terminal.send('\n');terminal.expect('DONE');terminal.finish()
                test_menu.MenuTests().assert_inline(terminal.buffer)
            finally:terminal.close()
