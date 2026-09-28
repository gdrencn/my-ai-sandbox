"""Regression contracts for shared installation and inline action presentation."""
import contextlib
import io
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mas import menu
from mas.core import Error
from mas.install import dependency_script, enable_fuse_access, prepare_dependencies
from mas.filesystems import fuse_access_ready
from mas.terminal_ui import UI
from mas.testing import Terminal


class SharedSetupTests(unittest.TestCase):
    def shell(self, suffix, input=None, script=None, env=None):
        return subprocess.run(['bash', '-o', 'pipefail', '-c',
                               (dependency_script() if script is None else script) + '\n' + suffix],
                              input=input, text=True, capture_output=True, env=env)

    def test_dependencies_detect_all_combinations_and_install_once(self):
        # The real planner is exercised with a controlled command lookup and
        # absent snap path; apt is replaced only at the side-effect boundary.
        for available, expected in (([], ['python3', 'snapd', 'sshfs']),
                                    (['python3', 'snap'], ['sshfs']),
                                    (['lxd', 'sshfs'], ['python3']),
                                    (['python3', 'lxd', 'sshfs'], [])):
            script = dependency_script().replace('/snap/bin/lxd', '/nonexistent-mas-lxd')
            setup = 'command() { case "$2" in ' + '|'.join(available or ['unavailable']) + ') return 0;; *) return 1;; esac; }\n'
            setup += 'mas_run_apt() { printf "%s\\n" "$*"; }\nmas_install_dependencies'
            result = self.shell(setup, script=script)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['update', 'install -y ' + ' '.join(expected)] if expected else [])

    def test_refresh_failure_never_starts_install(self):
        result = self.shell('mas_missing_dependencies() { echo sshfs; }; mas_run_apt() { echo "$*"; return 42; }; mas_install_dependencies')
        self.assertEqual(result.returncode, 42)
        self.assertEqual(result.stdout, 'update\n')

    def test_ready_dependency_preparation_does_not_request_privilege(self):
        with patch('mas.install.subprocess.check_output', return_value=''), patch('mas.install.run') as run:
            prepare_dependencies()
        run.assert_not_called()

    def test_redirected_apt_keeps_diagnostics_not_normal_output(self):
        sample = ('Hit:1 http://example stable InRelease\nReading package lists... Done\n'
                  'The following NEW packages will be installed:\n  sshfs\n'
                  '0 upgraded, 1 newly installed, 0 to remove and 0 not upgraded.\n'
                  'W: native warning\nUnpacking sshfs (1) ...\nunknown native message\n'
                  'Setting up package failed unexpectedly\n')
        result = self.shell('mas_apt_render', sample)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, 'W: native warning\nunknown native message\nSetting up package failed unexpectedly\n')
        self.assertNotIn('\x1b', result.stdout)

    def test_apt_failure_keeps_full_log_and_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            apt = path/'apt-get'
            apt.write_text('#!/bin/sh\nprintf "Reading package lists... Done\\nE: fixture error\\n"\nexit 23\n')
            apt.chmod(0o755)
            sudo = path/'sudo'
            sudo.write_text('#!/bin/sh\nexec "$@"\n'); sudo.chmod(0o755)
            result = self.shell('mas_run_apt update', env={**os.environ, 'PATH': directory + ':' + os.environ['PATH']})
            self.assertEqual(result.returncode, 23)
            self.assertIn('E: fixture error', result.stdout)
            self.assertIn('Reading package lists... Done', result.stderr)
            self.assertNotIn('completed', result.stdout)

    def test_apt_tty_progress_and_normal_privilege_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            apt = path/'apt-get'
            apt.write_text('#!/bin/sh\nprintf "APT_QUESTION: "\nread answer\n[ "$answer" = continue ] || exit 21\nprintf "Reading package lists... Done\\nW: retained warning\\nSetting up sshfs ...\\n"\n')
            apt.chmod(0o755)
            sudo = path/'sudo'
            sudo.write_text('#!/bin/bash\nprintf "SYSTEM_AUTH: " >/dev/tty\nread -r answer </dev/tty\n[[ $answer == fixture ]] || exit 19\nexec "$@"\n')
            sudo.chmod(0o755)
            # Force the unprivileged branch in this isolated shell even if the
            # tests are launched by root. No real sudo or credentials are used.
            script = dependency_script().replace('[[ $EUID -eq 0 ]]', 'false')
            command = 'export PATH=' + shlex.quote(directory + ':' + os.environ['PATH']) + '\n' + script + '\nmas_run_apt install -y sshfs'
            terminal = Terminal(['bash', '-o', 'pipefail', '-c', command], 300, path/'tty.log')
            try:
                terminal.expect('SYSTEM_AUTH:')
                terminal.send('fixture\n')
                terminal.expect('APT_QUESTION:')
                terminal.send('continue\n')
                terminal.expect('Dependency preparation completed')
                terminal.finish()
                self.assertIn(b'\r\x1b[2K', terminal.buffer)
                self.assertIn(b'W: retained warning', terminal.buffer)
                self.assertNotIn(b'sudo -v', terminal.buffer)
            finally:
                terminal.close()

    def test_fuse_gate_preserves_settings_mode_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'fuse.conf'
            path.write_text('#user_allow_other\nmount_max=321'); path.chmod(0o640)
            self.assertFalse(fuse_access_ready(path))
            enable_fuse_access(path)
            self.assertEqual(path.read_text(), '#user_allow_other\nmount_max=321\nuser_allow_other\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            stamp = path.stat().st_mtime_ns
            enable_fuse_access(path)
            self.assertEqual(path.stat().st_mtime_ns, stamp)
            self.assertTrue(fuse_access_ready(path))
            other = Path(directory)/'link'; other.symlink_to(Path(directory)/'missing')
            with self.assertRaises(Error): enable_fuse_access(other)
            self.assertFalse(other.resolve().exists())

    def test_shared_result_return_orders_success_failure_and_cancel(self):
        for outcome in ('success', Error('NATIVE_FAILURE'), menu.Cancelled()):
            output = io.StringIO()
            view = Mock()
            def callback():
                print('FUNCTION_OUTPUT')
                if isinstance(outcome, Exception): raise outcome
                return 42
            def choose(title, choices):
                self.assertIn('\nACTION_TITLE\n\nFUNCTION_OUTPUT', output.getvalue())
                self.assertEqual(len(choices), 1)
                self.assertIsNone(choices[0][0])
                self.assertNotIn('PARENT_MENU', output.getvalue())
            view.choose.side_effect = choose
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                value = UI(view, Mock()).present('ACTION_TITLE', callback)
                print('PARENT_MENU')
            self.assertEqual(value, 42 if outcome == 'success' else None)
            view.choose.assert_called_once()
            if isinstance(outcome, Error): self.assertIn('NATIVE_FAILURE', output.getvalue())

    def test_shared_selection_wraps_without_changing_checked_values(self):
        selection = menu.Selection([('a','A'),('b','B'),('c','C')], multiple=True)
        selection.toggle()
        selection.move(-1); self.assertEqual(selection.index, 2)
        selection.move(1); self.assertEqual(selection.index, 0)
        self.assertEqual(selection.result(), ['a'])
        one = menu.Selection([('a','A')])
        for delta in (-1, 1):
            one.move(delta); self.assertEqual(one.index, 0)
