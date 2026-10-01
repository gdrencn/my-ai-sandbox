"""Shared display and post-shell navigation contracts."""
import io
import re
import unittest
from unittest.mock import Mock, patch

from mas import menu
from mas.core import Error, Manager, ShellExitError
from mas.output import Output, boundary
from mas.terminal_ui import UI, LeaveMenu


class MenuContractTests(unittest.TestCase):
    def test_columns_left_align_by_display_width_and_preserve_status_color(self):
        rows = menu.column_rows([('中文', menu.status_cell('运行中', 'Running')),
                                 ('abcdef', menu.status_cell('已停止', 'Stopped'))])
        plain = lambda text: re.sub(r'\x1b\[[0-9;]*m', '', text)
        for row in rows:
            result = menu.rendered(row, 40)
            self.assertEqual(menu.cells(plain(result).split(row.values[1].text)[0]), 8)
            self.assertIn('\x1b[3', result)
        for width in range(2, 20):
            for row in rows:
                self.assertLessEqual(menu.cells(plain(menu.rendered(row, width))), width)
        safe = menu.rendered(menu.column_rows([('\x1b[2Jbad', 'ok')])[0], 40)
        self.assertNotIn('\x1b[2J', safe)
        with self.assertRaises(ValueError): menu.column_rows([('a',), ('b', 'c')])

    def test_long_input_instruction_keeps_all_text(self):
        for text in ('请输入容器内目录路径（不输入，直接回车默认使用 sandbox 用户的主目录）：',
                     'Enter a directory path inside the container (leave empty and press Enter to use the sandbox home directory):'):
            lines = menu.wrapped(text, 39)
            self.assertEqual(''.join(lines), text)
            self.assertTrue(all(menu.cells(line) <= 39 for line in lines))

    def test_shared_output_emits_one_boundary_gap_not_one_per_result(self):
        stream = io.StringIO()
        screen = menu.Screen.__new__(menu.Screen)
        screen.needs_gap = True
        screen.write = stream.write
        token = boundary.set(screen.before_output)
        try:
            output = Output(stream)
            output.keep('success')
            output.keep('native warning')
            self.assertEqual(stream.getvalue(), '\nsuccess\nnative warning\n')
        finally: boundary.reset(token)

    def test_unmount_selection_has_no_duplicate_table_and_uniform_columns(self):
        for abnormal in (False, True):
            view, manager = Mock(), Mock()
            entries = [dict(path='/a', destination='/host/a', status='mounted'),
                       dict(path='/b', destination='/host/b', status='residual' if abnormal else 'mounted')]
            manager.mountedfs.return_value = entries
            view.choose.side_effect = ['unmountfs', '/a', None, 'back']
            with patch('mas.terminal_ui.sys.stdout', io.StringIO()), patch('mas.presentation.show_mounts') as table:
                UI(view, manager).filesystem('demo')
            table.assert_not_called()
            options = view.choose.call_args_list[1].args[1]
            self.assertEqual([len(row.values) for _, row in options[:-1]], [2,2] if abnormal else [1,1])
            self.assertEqual([row.values[0].text for _, row in options[:-1]], ['/a','/b'])
            manager.unmountfs.assert_called_once_with('demo', '/a')

    def test_shell_finish_leaves_menu_even_when_cleanup_failed(self):
        for error in (None, ShellExitError('cleanup failed')):
            view, manager = Mock(), Mock()
            manager.enter.side_effect = error
            with self.assertRaises(LeaveMenu) as caught:
                UI(view, manager).present('Enter', lambda: UI(view,manager).enter('demo'))
            self.assertIs(caught.exception.error, error)
            view.choose.assert_not_called()

    def test_preentry_failure_keeps_ordinary_result_page(self):
        view, manager = Mock(), Mock()
        manager.enter.side_effect = Error('start failed')
        with patch('mas.terminal_ui.sys.stderr', io.StringIO()):
            UI(view,manager).present('Enter', lambda: UI(view,manager).enter('demo'))
        view.choose.assert_called_once()

    def test_core_marks_only_post_shell_failures(self):
        manager = Manager(Mock(prefix=[]), isolation=Mock())
        manager.require = Mock();manager.start = Mock();manager.on_exit = Mock()
        for code, failure in ((1,None), (0,Error('stop failed')), (0,OSError('cleanup failed'))):
            manager.on_exit.side_effect = failure
            with patch('mas.core.subprocess.call', return_value=code), self.assertRaises(ShellExitError):
                manager.enter('demo')
        manager.start.side_effect = Error('preentry')
        with patch('mas.core.subprocess.call') as shell, self.assertRaises(Error) as caught:
            manager.enter('demo')
        self.assertNotIsInstance(caught.exception, ShellExitError)
        shell.assert_not_called()

    def test_rendered_spacing_in_real_terminals_for_both_languages(self):
        import os
        from pathlib import Path
        import sys
        import tempfile
        from mas.testing import Terminal, python_command
        from tests.test_menu import MenuTests
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            for language in ('zh_cn', 'en_us'):
                for case in ('create', 'mount', 'no-input', 'error', 'cancel', 'empty'):
                    with self.subTest(language=language, case=case):
                        source = """
import sys
from mas import config, menu
from mas.terminal_ui import UI
from mas.output import Output
from mas.core import Error
from mas.i18n import t
config.set_value('language', LANGUAGE)
def exercise(view):
    ui = UI(view, None)
    def action():
        if CASE == 'create':
            view.input(t('new_target'));view.input(t('new_image'))
        if CASE == 'mount':view.input(t('fs_path_prompt'))
        if CASE == 'cancel':raise menu.Cancelled
        if CASE == 'error':raise Error('FAILURE_SENTINEL')
        if CASE == 'empty':
            ui.write(t('menu_empty'));return
        output = Output()
        output.progress('WAITING_SENTINEL')
        output.keep('RESULT_SENTINEL')
        output.keep('NATIVE_DIAGNOSTIC_SENTINEL')
        ui.write('END_SENTINEL')
    ui.present('ACTION_SENTINEL', action)
    print('HOST_SENTINEL', flush=True)
menu.interactive(exercise)
""".replace('LANGUAGE', repr(language)).replace('CASE', repr(case))
                        terminal = Terminal(python_command(source), 300, Path(directory)/'spacing.log')
                        try:
                            terminal.expect('ACTION_SENTINEL')
                            if case == 'create':
                                terminal.expect('请输入容器名' if language == 'zh_cn' else 'Enter the container name')
                                terminal.send('demo\n')
                                terminal.expect('选择镜像版本' if language == 'zh_cn' else 'Choose an image version')
                                terminal.send('\n')
                            if case == 'mount':
                                terminal.expect('请输入容器内的绝对目录路径' if language == 'zh_cn' else 'Enter an absolute directory path')
                                terminal.send('\n')
                            result = '操作结果' if language == 'zh_cn' else 'Operation result'
                            terminal.expect(result);terminal.send('\n')
                            terminal.expect('HOST_SENTINEL');terminal.finish()
                            history = MenuTests().render_history(terminal.buffer)
                            self.assertIn('\n\n' + result, history)
                            self.assertNotIn('\n\n\n', history)
                            if case not in ('error', 'cancel', 'empty'):
                                self.assertIn('\n\nRESULT_SENTINEL\nNATIVE_DIAGNOSTIC_SENTINEL\nEND_SENTINEL\n\n' + result, history)
                            if case == 'no-input':
                                self.assertIn('ACTION_SENTINEL\n\nRESULT_SENTINEL', history)
                        finally:
                            terminal.close()
