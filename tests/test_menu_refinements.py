"""Approved menu behavior, rendered through real PTYs in both languages."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch

from mas import config, menu
from mas.core import Error
from mas.gpu import GPU, KEY
from mas.i18n import t
from mas.presentation import show_mounts
from mas.terminal_ui import UI
from mas.testing import Terminal, python_command
from tests import test_menu


class MenuFixture:
    """No LXD or filesystem mutations; exercise the real UI/rendering only."""
    def __init__(self):
        self.item = dict(name='demo', status='Stopped', config={KEY: json.dumps(dict(
            version=1, enabled=False, backend='nvidia-cdi', driver_paths=[], devices={},
            runtime_file=None, runtime_profile=None))})
        self.info_calls = 0
        self.hardware_calls = 0
        self.actions = []
        self.lxd = None
        self.gpu = GPU(self)
        self.entries = [dict(path='/home/sandbox', destination='/host/demo/home/sandbox', status='mounted'),
                        dict(path='/var/log', destination='/host/demo/var/log', status='residual')]

    def list(self):
        return [self.item]

    def legacy_list(self):
        return []

    def info(self, target):
        self.info_calls += 1
        return copy.deepcopy(self.item)

    def hardware(self, target):
        self.hardware_calls += 1
        return dict(available=True, enabled=False, configured=True)

    def mountedfs(self, target):
        return self.entries

    def mountfs(self, target, path):
        self.actions.append(['mount', target, path])
        return '/host/demo' + path

    def unmountfs(self, target, path):
        self.actions.append(['unmount', target, path])


class RefinementTests(unittest.TestCase):
    def test_filesystem_group_preserves_parent_and_submenu_focus(self):
        view, manager = Mock(), Mock()
        manager.mountfs.return_value = '/host/a'
        view.choose.side_effect = ['filesystem', 'mountfs', None, 'back', 'back']
        view.input.return_value = '/a'
        with contextlib.redirect_stdout(io.StringIO()):
            UI(view, manager).container('demo')
        first = view.choose.call_args_list[0]
        self.assertEqual([key for key, _ in first.args[1]],
                         ['info', 'start', 'enter', 'stop', 'restart', 'export', 'delete', 'filesystem', 'hardware', 'back'])
        self.assertEqual([key for key, _ in view.choose.call_args_list[1].args[1]],
                         ['mountedfs', 'mountfs', 'unmountfs', 'back'])
        self.assertEqual(view.choose.call_args_list[3].kwargs['default'], 'mountfs')
        self.assertEqual(view.choose.call_args_list[4].kwargs['default'], 'filesystem')
        manager.mountfs.assert_called_once_with('demo', '/a')
        manager.unmountfs.assert_not_called()

    def test_unmount_cancel_and_empty_result_have_no_mutation(self):
        for selection in (None, menu.Cancelled()):
            view, manager = Mock(), Mock()
            manager.mountedfs.return_value = [dict(path='/a', status='mounted')]
            view.choose.side_effect = ['unmountfs', selection, None, 'back']
            with contextlib.redirect_stdout(io.StringIO()) as output:
                UI(view, manager).filesystem('demo')
            self.assertIn(t('cancelled'), output.getvalue())
            manager.unmountfs.assert_not_called()
        view, manager = Mock(), Mock()
        manager.mountedfs.return_value = []
        view.choose.side_effect = ['unmountfs', None, 'back']
        with contextlib.redirect_stdout(io.StringIO()) as output:
            UI(view, manager).filesystem('demo')
        self.assertIn(t('fs_empty'), output.getvalue())
        manager.unmountfs.assert_not_called()

    def test_information_reuses_one_snapshot_without_discovery(self):
        for enabled in (None, False, True):
            view, manager = Mock(), MenuFixture()
            if enabled is None:
                manager.item['config'].clear()
            elif enabled:
                from mas.gpu import devices
                record = json.loads(manager.item['config'][KEY])
                record.update(enabled=True, devices=devices('nvidia-cdi', []))
                manager.item['config'][KEY] = json.dumps(record)
            view.choose.side_effect = ['configuration', None, 'configuration', None, 'back']
            with patch('mas.gpu.detect') as detect, contextlib.redirect_stdout(io.StringIO()) as output:
                UI(view, manager).info('demo')
            self.assertEqual(manager.info_calls, 1)
            self.assertEqual(manager.hardware_calls, 0)
            detect.assert_not_called()
            detail = json.dumps(manager.item, indent=2)
            self.assertEqual(output.getvalue().count(detail), 2)
            summary = view.choose.call_args_list[0].kwargs['description']
            self.assertIn(t('info_gpu', value=t('gpu_unconfigured' if enabled is None else
                                               'state_enabled' if enabled else 'state_disabled')), summary)

    def test_invalid_gpu_record_remains_an_error(self):
        manager, view = MenuFixture(), Mock()
        manager.item['config'][KEY] = '{broken'
        with patch('mas.gpu.detect') as detect, self.assertRaises(Error):
            UI(view, manager).info('demo')
        view.choose.assert_not_called()
        detect.assert_not_called()

    def test_navigation_failure_has_title_and_explicit_return(self):
        view = Mock()
        trace = []
        view.heading.side_effect = lambda title: trace.append(('heading', title))
        view.choose.side_effect = lambda *args, **kwargs: trace.append(('choose', args[0]))
        ui = UI(view, None)
        ui.write = lambda text, error=False: trace.append(('write', text))
        ui.present('PAGE', Mock(side_effect=Error('READ_FAILED')), back=False)
        self.assertEqual(trace[0], ('heading', 'PAGE'))
        self.assertIn('READ_FAILED', trace[1][1])
        self.assertEqual(trace[2], ('choose', t('page_result')))

    def test_read_only_mount_columns_are_complete_aligned_and_plain(self):
        entries = [dict(path='/中文', destination='/host/' + 'x' * 220, status='mounted'),
                   dict(path='/abcdef', destination='/host/b', status='residual')]
        lines = []
        show_mounts(entries, lines.append)
        for line, entry in zip(lines, entries):
            self.assertIn(entry['destination'], line)
            self.assertNotIn('\t', line)
            self.assertNotIn('\x1b', line)
        starts = [menu.cells(line[:line.index('/host/')]) for line in lines]
        self.assertEqual(starts[0], starts[1])
        lines = []
        show_mounts([dict(path='/a\x1b[2J', destination='/host/\npath', status='mounted')], lines.append)
        self.assertNotIn('\x1b', lines[0]); self.assertNotIn('\n', lines[0])

    def terminal(self, source, directory):
        return Terminal(python_command(source), 30, Path(directory) / 'menu.log')

    def test_complete_menu_paths_in_both_languages(self):
        for language in ('zh_cn', 'en_us'):
            with (self.subTest(language=language), tempfile.TemporaryDirectory() as directory,
                  patch.dict(os.environ, {'XDG_CONFIG_HOME': directory})):
                source = f"""import json
from mas import config, menu
from mas.terminal_ui import UI
from tests.test_menu_refinements import MenuFixture
config.set_value('language', {language!r})
manager = MenuFixture()
menu.interactive(lambda view: UI(view, manager).loop())
print('FIXTURE_RESULT='+json.dumps(dict(info=manager.info_calls, hardware=manager.hardware_calls, actions=manager.actions)), flush=True)
"""
                terminal = self.terminal(source, directory)
                tr = lambda key, **values: t(key, locale=language, **values)
                down, up, back = '\x1b[B', '\x1b[A', '\x1b[D'
                def send(keys, text):
                    terminal.send(keys); terminal.expect(text)
                def result(parent):
                    terminal.expect(tr('page_result')); send(back, parent)
                try:
                    terminal.expect('my-ai-sandbox');terminal.expect('Esc/← ' + tr('menu_exit'))
                    send(down * 4 + '\n', tr('page_settings'))
                    send(down + '\n', 'my-ai-sandbox')
                    send(up * 4 + '\n', tr('page_list'))
                    send('\n', tr('page_container', target='demo'))
                    send('\n', tr('info_name', name='demo'))
                    terminal.expect(tr('info_state', status=tr('state_stopped')))
                    terminal.expect(tr('info_gpu', value=tr('state_disabled')))
                    send('\n', '"status": "Stopped"')
                    result(tr('menu_info_title', target='demo'))
                    send(down + '\n', tr('page_container', target='demo'))
                    send(down * 8 + '\n', tr('page_hardware', target='demo'))
                    send(back, tr('page_container', target='demo'))
                    send(up + '\n', tr('page_filesystem', target='demo'))
                    send(down + '\n', tr('fs_path_prompt'))
                    send('/var/log\n', tr('fs_mounted_at', path='/host/demo/var/log'))
                    result(tr('page_filesystem', target='demo'))
                    send(down + '\n', tr('fs_unmount_select'))
                    terminal.expect(tr('state_mounted'));terminal.expect(tr('state_residual'))
                    send(up + '\n', tr('menu_done'))
                    result(tr('page_filesystem', target='demo'))
                    send(up * 2 + '\n', '/host/demo/home/sandbox')
                    result(tr('page_filesystem', target='demo'))
                    send(back, tr('page_container', target='demo'))
                    send(back, tr('page_list'));send(back, 'my-ai-sandbox')
                    send(up + '\n', 'FIXTURE_RESULT=');terminal.finish()
                    history = test_menu.MenuTests().render_history(terminal.buffer)
                    for key in ('page_settings', 'page_hardware'):
                        self.assertEqual(history.splitlines().count(tr(key, target='demo')), 1)
                    self.assertNotIn('\n\n\n', history)
                    for key in ('page_container', 'page_list', 'page_filesystem'):
                        title = re.escape(tr(key, target='demo'))
                        self.assertNotRegex(history, '\n' + title + r'\n\s*\n' + title + '\n')
                    raw = terminal.buffer.split(b'FIXTURE_RESULT=', 1)[1].splitlines()[0]
                    measured = json.loads(raw)
                    self.assertEqual(measured, dict(info=1, hardware=1,
                        actions=[['mount', 'demo', '/var/log'], ['unmount', 'demo', '/var/log']]))
                    test_menu.MenuTests().assert_inline(terminal.buffer)
                finally:
                    terminal.close()

    def test_empty_list_and_migration_descriptions_follow_the_title(self):
        for language in ('zh_cn', 'en_us'):
            with (self.subTest(language=language), tempfile.TemporaryDirectory() as directory,
                  patch.dict(os.environ, {'XDG_CONFIG_HOME': directory})):
                source = f"""from mas import config, menu
from mas.terminal_ui import UI
from tests.test_menu_refinements import MenuFixture
config.set_value('language', {language!r})
manager=MenuFixture();manager.list=lambda:[]
def exercise(view):
    ui=UI(view, manager)
    ui.present('unused', ui.containers, back=False)
    ui.present('unused', ui.migration, back=False)
    print('DONE', flush=True)
menu.interactive(exercise)
"""
                terminal = self.terminal(source, directory)
                try:
                    terminal.expect(t('menu_empty', locale=language));terminal.send('\x1b[D')
                    terminal.expect(t('migration_empty', locale=language));terminal.send('\x1b[D')
                    terminal.expect('DONE');terminal.finish()
                    history = test_menu.MenuTests().render_history(terminal.buffer)
                    for title, body in (('page_list','menu_empty'), ('menu_migrate','migration_help')):
                        self.assertEqual(history.splitlines().count(t(title,locale=language)), 1)
                        self.assertLess(history.index(t(title,locale=language)), history.index(t(body,locale=language)))
                    self.assertNotIn('unused', history)
                    self.assertNotIn('\n\n\n', history)
                finally:
                    terminal.close()

    def test_footer_context_and_long_instructions_in_narrow_terminals(self):
        for language, height in [('zh_cn', 8), ('en_us', 8), ('zh_cn', 4), ('en_us', 4)]:
            with (self.subTest(language=language,height=height), tempfile.TemporaryDirectory() as directory,
                  patch.dict(os.environ, {'XDG_CONFIG_HOME': directory})):
                source = f"""import fcntl,struct,termios
from mas import config,menu
from mas.i18n import t
config.set_value('language', {language!r})
print('RESIZE_READY',flush=True);input()
fcntl.ioctl(0,termios.TIOCSWINSZ,struct.pack('HHHH',{height},39,0,0))
def exercise(view):
    view.choose('MAIN',[(1,'One')],cancel='exit')
    view.choose('SUBMENU',[(1,'One')])
    view.confirm('DECISION')
    view.choose('CONTEXT',[(1,'One')],description=[t('migration_help')])
    view.input(t('new_target'))
    print('DONE',flush=True)
menu.interactive(exercise)
"""
                terminal = self.terminal(source, directory)
                try:
                    terminal.expect('RESIZE_READY');terminal.send('\n')
                    for title in ('MAIN','SUBMENU','DECISION','CONTEXT'):
                        terminal.expect(title)
                        action = 'exit' if title == 'MAIN' else 'cancel' if title == 'DECISION' else 'back'
                        hint = t('menu_keys', locale=language, action=t('menu_'+action,locale=language))
                        separator = rb'(?:\x1b\[[0-?]*[ -/]*[@-~]|\r|\n)*'
                        pattern = separator.join(re.escape(char.encode()) for char in hint)
                        terminal.expect_pattern(pattern, hint)
                        terminal.send('\n')
                    terminal.expect('▏');terminal.send('demo\n')
                    terminal.expect('DONE');terminal.finish()
                    history = test_menu.MenuTests().render_history(terminal.buffer)
                    flattened = history.replace('\n', '')
                    for key in ('migration_help','new_target'):
                        self.assertIn(t(key,locale=language), flattened)
                    for action in ('exit','back','cancel'):
                        self.assertIn(t('menu_keys',locale=language,action=t('menu_'+action,locale=language)), flattened)
                    self.assertNotIn('\n\n\n',history[history.index('MAIN'):])
                    test_menu.MenuTests().assert_inline(terminal.buffer)
                finally:
                    terminal.close()
