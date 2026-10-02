"""Restart composition and explicit destinations after a terminal ends."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from mas import cli, menu
from mas.core import Error, Manager, ShellExitError
from mas.i18n import t
from mas.terminal_ui import UI, run
from mas.testing import Terminal, python_command
from tests import test_lifecycle_mounts


class RestartTests(unittest.TestCase):
    def manager(self):
        manager = Manager(Mock(prefix=['lxc']), isolation=Mock())
        manager.require = Mock()
        manager.start, manager.stop = Mock(), Mock()
        return manager

    def test_restart_composes_complete_foundations_and_short_circuits_failure(self):
        for enter in (False, True):
            manager = self.manager()
            manager.enter = Mock(return_value='exit')
            trace = Mock()
            for name in ('stop', 'start', 'enter'):
                trace.attach_mock(getattr(manager, name), name)
            ask = Mock()
            manager.restart('demo', enter=enter, ask=ask)
            self.assertEqual([c[0] for c in trace.mock_calls], ['stop', 'enter' if enter else 'start'])
            if enter:
                manager.enter.assert_called_once_with('demo', ask)
            failure = Error('STOP_FAILED')
            manager.stop.side_effect = failure
            trace.reset_mock()
            with self.assertRaises(Error) as caught:
                manager.restart('demo', enter=enter, ask=ask)
            self.assertIs(caught.exception, failure)
            self.assertEqual([c[0] for c in trace.mock_calls], ['stop'])

    def test_restart_keeps_each_transition_mount_phases_and_single_preparation(self):
        fixture = test_lifecycle_mounts.LifecycleMountTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.lxd.prefix = ['lxc']
        for enter in (False, True):
            fixture.instance['status'] = 'Running'; fixture.trace.clear()
            with patch('mas.core.subprocess.call', return_value=0):
                fixture.manager.restart('demo', enter=enter, ask=lambda _: 'exit')
            phases = [c[0] for c in fixture.trace]
            self.assertEqual(phases, ['unmount'] * 3 + ['stop'] + ['mount'] * 3
                             + ['unmount'] * 3 + ['start', 'prepare-user'] + ['mount'] * 3)

    def test_every_terminal_code_offers_all_destinations_without_inference(self):
        for code in (0, 7, 130, 143):
            for choice in ('stop', 'restart', 'menu', 'exit'):
                with self.subTest(code=code, choice=choice):
                    manager = self.manager(); manager.restart = Mock()
                    ask = Mock(return_value=choice)
                    with patch('mas.core.subprocess.call', return_value=code):
                        if code:
                            with self.assertRaises(ShellExitError) as caught:
                                manager.enter('demo', ask)
                            self.assertIn(str(code), str(caught.exception))
                            self.assertEqual(caught.exception.return_to_menu, choice == 'menu')
                        else:
                            self.assertEqual(manager.enter('demo', ask), 'menu' if choice == 'menu' else 'exit')
                    ask.assert_called_once()
                    self.assertEqual(manager.stop.call_count, int(choice == 'stop'))
                    self.assertEqual(manager.restart.call_count, int(choice == 'restart'))

    def test_post_terminal_failure_preserves_both_diagnostics(self):
        manager = self.manager(); failure = OSError('STOP_FAILED'); manager.stop.side_effect = failure
        with patch('mas.core.subprocess.call', return_value=143), self.assertRaises(ShellExitError) as caught:
            manager.enter('demo', lambda _: 'stop')
        self.assertIn('143', str(caught.exception)); self.assertIn('STOP_FAILED', str(caught.exception))
        self.assertIs(caught.exception.__cause__, failure)
        self.assertFalse(caught.exception.return_to_menu)

    def test_preparation_failure_prevents_shell_and_post_terminal(self):
        manager = self.manager(); manager.start.side_effect = Error('START_FAILED'); ask = Mock()
        with patch('mas.core.subprocess.call') as shell, self.assertRaisesRegex(Error, 'START_FAILED'):
            manager.restart('demo', enter=True, ask=ask)
        manager.stop.assert_called_once_with('demo'); shell.assert_not_called(); ask.assert_not_called()

    def test_legacy_consent_and_missing_input_have_explicit_safe_destinations(self):
        for answer in (True, False, 'yes', 'no', '', None):
            manager = self.manager()
            self.assertEqual(manager.on_exit('demo', lambda _: answer), 'exit')
            self.assertEqual(manager.stop.call_count, int(answer in (True, 'yes')))
        manager = self.manager()
        self.assertEqual(manager.on_exit('demo', Mock(side_effect=EOFError)), 'exit')
        with patch('mas.menu.sys.stdin.isatty', return_value=False), patch('mas.menu.interactive') as screen:
            self.assertEqual(menu.post_terminal('finished'), 'exit')
        screen.assert_not_called()

    def test_cli_dispatch_consent_help_and_start_interface(self):
        manager = Mock(); manager.enter.return_value = manager.restart.return_value = 'exit'
        for flag in ('-e', '--enter'):
            with patch('mas.menu.post_terminal') as selector:
                self.assertEqual(cli.main(['restart', 'demo', flag], manager), 0)
                manager.restart.assert_called_with('demo', enter=True, ask=selector)
        for command in ('enter', 'restart'):
            for flag, answer in (('--yes', True), ('--no', False)):
                args = [command, 'demo'] + (['-e'] if command == 'restart' else []) + [flag]
                self.assertEqual(cli.main(args, manager), 0)
                call = getattr(manager, command).call_args
                callback = call.args[1] if command == 'enter' else call.kwargs['ask']
                self.assertIs(callback('finished'), answer)
        manager.restart.reset_mock()
        self.assertEqual(cli.main(['restart', 'demo'], manager), 0)
        manager.restart.assert_called_once_with('demo')
        for args in (['start', 'demo', '-e'], ['restart', '--all'], ['restart', 'demo', '--yes']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                cli.main(args, manager)
            self.assertEqual(caught.exception.code, 2)
        for language in ('en_us', 'zh_cn'):
            with patch('mas.config.language', return_value=language), contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as caught:
                    cli.main(['restart', '--help'], manager)
                self.assertEqual(caught.exception.code, 0)
            self.assertIn('--enter', output.getvalue())

    def test_cli_return_to_menu_retains_failure_status_without_repeating_error(self):
        for failed in (False, True):
            manager = Mock(); manager.enter.return_value = 'menu'
            if failed:
                manager.enter.side_effect = ShellExitError('SHELL_FAILED', return_to_menu=True)
            with (patch('mas.terminal_ui.run', return_value=0) as application,
                  contextlib.redirect_stderr(io.StringIO()) as output):
                self.assertEqual(cli.main(['enter', 'demo'], manager), int(failed))
            application.assert_called_once_with(manager, target='demo')
            self.assertEqual(output.getvalue().count('SHELL_FAILED'), int(failed))

    def test_menu_return_keeps_enter_focus_and_skips_result_page(self):
        for failed in (False, True):
            view, manager = Mock(), Mock(); manager.enter.return_value = 'menu'
            view.choose.side_effect = ['enter', 'back']
            if failed:
                manager.enter.side_effect = ShellExitError('SHELL_FAILED', return_to_menu=True)
            ui = UI(view, manager)
            with contextlib.redirect_stderr(io.StringIO()) as output:
                ui.container('demo')
            self.assertEqual(view.choose.call_count, 2)
            self.assertEqual(view.choose.call_args_list[1].kwargs['default'], 'enter')
            self.assertEqual(ui.terminal_failed, failed)
            self.assertEqual(output.getvalue().count('SHELL_FAILED'), int(failed))

    def test_application_exit_after_return_preserves_terminal_failure_status(self):
        manager = Mock()
        manager.enter.side_effect = ShellExitError('SHELL_FAILED', return_to_menu=True)
        view = Mock(); view.choose.side_effect = ['enter', 'back', 'exit']
        with (patch('mas.terminal_ui.sys.stdin.isatty', return_value=True),
              patch('mas.terminal_ui.sys.stdout.isatty', return_value=True),
              patch('mas.menu.interactive', side_effect=lambda callback: callback(view)),
              contextlib.redirect_stderr(io.StringIO()) as output):
            self.assertEqual(run(manager, target='demo'), 1)
        self.assertEqual(output.getvalue().count('SHELL_FAILED'), 1)
        self.assertNotIn(t('page_result'), [c.args[0] for c in view.choose.call_args_list])

    def test_real_post_terminal_choices_restore_terminal_in_both_languages(self):
        keys = {'exit': '\n', 'stop': '\x1b[B\n', 'restart': '\x1b[A' * 2 + '\n',
                'menu': '\x1b[A\n', 'escape': '\x1b', 'left': '\x1b[D'}
        for language in ('zh_cn', 'en_us'):
            for choice, presses in keys.items():
                with self.subTest(language=language, choice=choice), tempfile.TemporaryDirectory() as directory:
                    source = f'''import json, termios
from mas import config, menu
config.set_value('language', {language!r})
before = termios.tcgetattr(0)
choice = menu.post_terminal('TERMINAL_FINISHED')
assert termios.tcgetattr(0) == before
print('DESTINATION=' + choice, flush=True)
'''
                    with patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
                        terminal = Terminal(python_command(source), 30, Path(directory) / 'terminal.log')
                    try:
                        terminal.expect('TERMINAL_FINISHED')
                        terminal.expect('❯ ' + t('shell_leave', locale=language))
                        terminal.send(presses)
                        terminal.expect('DESTINATION=' + ('exit' if choice in ('escape', 'left') else choice))
                        terminal.finish()
                    finally:
                        terminal.close()
