"""Follow-up regressions for final output, cleanup and native failure data."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from mas import testing
from mas.core import Error, Manager, finish_client
from mas.diagnostics import cleanup_scope
from mas.filesystems import Filesystems
from mas.testing import Terminal, python_command


class TerminalReviewTests(unittest.TestCase):
    def terminal(self, directory, source):
        terminal = Terminal(python_command(source), 300, Path(directory)/'terminal.log')
        self.addCleanup(terminal.close)
        return terminal

    def exited_without_reaping(self, terminal):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if os.waitid(os.P_PID, terminal.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT):
                return
            time.sleep(.01)
        self.fail('fixture did not exit')

    def test_exited_child_tail_is_available_to_expect_finish_and_observer(self):
        payload = b'x'*5000 + b'\nFINAL_MARK\nWarning: final detail\n'
        for operation in ('expect', 'finish'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                terminal = self.terminal(directory, 'import os;os.write(1,'+repr(payload)+')')
                self.exited_without_reaping(terminal)
                seen = []
                terminal.on_read = lambda: seen.append(terminal.buffer)
                original = os.read
                # Force several PTY reads independently of kernel chunk sizing.
                with patch('mas.testing.os.read', side_effect=lambda fd, size: original(fd, min(size, 512))):
                    if operation == 'expect':
                        terminal.expect('FINAL_MARK')
                    terminal.finish()
                self.assertEqual(terminal.status, 0)
                self.assertIn(b'Warning: final detail', terminal.buffer)
                self.assertIn(b'Warning: final detail', seen[-1])
                terminal.close()
                self.assertIn(b'FINAL_MARK', (Path(directory)/'terminal.log').read_bytes())

    def test_cleanup_disables_output_observers_and_reaps_live_child(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = self.terminal(directory, "import signal,time;signal.signal(signal.SIGHUP,signal.SIG_IGN);print('READY',flush=True);time.sleep(60)")
            terminal.expect('READY')
            observer = Mock(side_effect=BrokenPipeError('closed progress output'))
            terminal.on_wait = terminal.on_read = observer
            terminal.last_update -= 2
            terminal.close()
            observer.assert_not_called()
            self.assertEqual(terminal.status, -signal.SIGTERM)
            self.assertIsNone(terminal.fd)
            self.assertTrue(terminal.transcript.closed)
            with self.assertRaises(ChildProcessError):os.waitpid(terminal.pid, os.WNOHANG)

    def test_transcript_write_failure_still_terminates_reaps_and_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = self.terminal(directory, "import time;print('READY',flush=True);input();print('TAIL',flush=True);time.sleep(60)")
            terminal.expect('READY')
            transcript = terminal.transcript
            terminal.transcript = Mock(wraps=transcript)
            terminal.transcript.write.side_effect = BrokenPipeError('transcript failed')
            terminal.send('continue\n')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(BrokenPipeError, 'transcript failed'):
                terminal.close()
            self.assertIsNotNone(terminal.status)
            self.assertIsNone(terminal.fd)
            self.assertTrue(transcript.closed)

    def test_continuously_readable_tail_has_a_deadline(self):
        terminal = Terminal.__new__(Terminal)
        terminal.timeout = 600
        terminal._receive = Mock(return_value=True)
        with patch('mas.testing.time.monotonic', side_effect=[0, 599, 600]):
            with self.assertRaises(Error):terminal._drain()
        self.assertEqual(terminal._receive.call_count, 2)

    def test_closed_terminal_with_live_child_keeps_polling_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = self.terminal(directory, "import os,time;print('READY',flush=True);os.close(0);os.close(1);os.close(2);time.sleep(60)")
            terminal.expect('READY')
            deadline = time.monotonic() + 300
            while not terminal.eof and terminal.status is None and time.monotonic() < deadline:
                terminal.read()
            self.assertTrue(terminal.eof)
            self.assertIsNone(terminal.status)
            with patch('mas.testing.time.sleep') as pause:
                terminal.read()
            pause.assert_called_once_with(.1)
            terminal.close()

    def test_cleanup_can_signal_child_before_its_group_is_available(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = self.terminal(directory, "import time;print('READY',flush=True);time.sleep(60)")
            terminal.expect('READY')
            with patch('mas.testing.os.killpg', side_effect=ProcessLookupError), patch('mas.testing.os.kill', wraps=os.kill) as kill:
                terminal.close()
            kill.assert_called_once_with(terminal.pid, signal.SIGTERM)
            self.assertEqual(terminal.status, -signal.SIGTERM)


class CleanupReviewTests(unittest.TestCase):
    def test_client_reaping_is_bounded_and_timeout_is_actionable(self):
        process = Mock(pid=1234)
        process.poll.return_value = None
        finish_client(process, 600)
        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=600)
        process.wait.side_effect = subprocess.TimeoutExpired('fixture', 600)
        with self.assertRaises(Error) as caught:finish_client(process, 600)
        self.assertIn('1234', str(caught.exception))

    def test_tester_finalization_attempts_all_steps_when_output_fails(self):
        suite = testing.Suite.__new__(testing.Suite)
        suite.cleanup_errors = []
        suite.output = Mock()
        suite.output.keep.side_effect = BrokenPipeError('output closed')
        last = Mock()
        primary = Error('primary operation failure')
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(Error) as caught:
            with cleanup_scope(lambda: suite._finalize(Mock(side_effect=OSError('cleanup failed')), last), lambda exc: None):
                raise primary
        self.assertIs(caught.exception, primary)
        last.assert_called_once_with()
        self.assertEqual(suite.cleanup_errors, ['cleanup failed'])

    def test_cli_poll_failure_keeps_primary_and_reaps_before_final_events(self):
        with tempfile.TemporaryDirectory() as directory:
            suite = testing.Suite(Path(directory)/'report', 600)
            self.addCleanup(suite.workspace.cleanup)
            process = Mock(pid=1234, returncode=None)
            process.poll.return_value = None
            primary = Error('event read failed')
            final = []
            def events(*args, **kwargs):
                if not final:
                    final.append(True)
                    raise primary
                process.wait.assert_called_once_with(timeout=600)
                return []
            suite.read_events = Mock(side_effect=events)
            with patch('mas.testing.subprocess.Popen', return_value=process), self.assertRaises(Error) as caught:
                suite.cli('list')
            self.assertIs(caught.exception, primary)
            process.kill.assert_called_once_with()
            self.assertEqual(suite.read_events.call_count, 2)

    def test_cli_cleanup_timeout_is_recorded_without_replacing_primary(self):
        with tempfile.TemporaryDirectory() as directory:
            suite = testing.Suite(Path(directory)/'report', 600)
            self.addCleanup(suite.workspace.cleanup)
            process = Mock(pid=1234, returncode=None)
            process.poll.return_value = None
            process.wait.side_effect = subprocess.TimeoutExpired('fixture', 600)
            primary = Error('event read failed')
            suite.read_events = Mock(side_effect=[primary, []])
            suite.output = Mock()
            with patch('mas.testing.subprocess.Popen', return_value=process), self.assertRaises(Error) as caught:
                suite.cli('list')
            self.assertIs(caught.exception, primary)
            self.assertIn('1234', suite.cleanup_errors[0])
            self.assertEqual(suite.read_events.call_count, 2)
            suite.output.diagnostics.assert_called_once()


class GPUFileReviewTests(unittest.TestCase):
    def setUp(self):
        from tests.test_gpu import GPUTests
        self.fixture = GPUTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.gpu.set('test-unit', True)

    def test_invalid_runtime_queries_cannot_publish_or_remove_files(self):
        fixture = self.fixture
        before = copy.deepcopy(fixture.item)
        for raw in ('{broken', 'null', '42', '"mas-gpu.conf"', '{}', '[1]', '[null]'):
            with self.subTest(raw=raw):
                fixture.manager.lxd.command.side_effect = None
                fixture.manager.lxd.command.return_value = raw
                fixture.manager.lxd.command.reset_mock()
                with self.assertRaises(Error):fixture.gpu.set('test-unit', False)
                self.assertEqual(fixture.item, before)
                self.assertTrue(all(call.args[0][0] == 'query' for call in fixture.manager.lxd.command.call_args_list))

    def test_binary_foreign_runtime_files_are_conflicts_without_changes(self):
        from mas.gpu import PROFILE
        fixture = self.fixture
        before = copy.deepcopy(fixture.item)
        fixture.file = fixture.profile = 'foreign bytes'
        original = fixture.command
        def command(args, **kwargs):
            if args[:2] == ['file', 'pull']:
                Path(args[3]).write_bytes(b'\xff\xfe')
                return ''
            return original(args, **kwargs)
        fixture.manager.lxd.command.side_effect = command
        with self.assertRaises(Error):fixture.gpu.set('test-unit', False)
        with self.assertRaises(Error):fixture.gpu._runtime_file('test-unit', PROFILE)
        self.assertEqual(fixture.item, before)
        self.assertEqual((fixture.file, fixture.profile), ('foreign bytes', 'foreign bytes'))
        self.assertFalse(any(call.args[0][:2] == ['file', 'delete'] for call in fixture.manager.lxd.command.call_args_list))


class NativeFailureReviewTests(unittest.TestCase):
    def test_mutating_lxd_failure_keeps_stream_boundaries(self):
        manager = Manager(Mock(prefix=python_command("import sys;sys.stdout.write('stdout detail');sys.stderr.write('stderr detail');sys.exit(1)"), timeout=300))
        manager.find = Mock(return_value=None)
        with self.assertRaisesRegex(Error, 'stdout detail\nstderr detail'):
            manager._run_lxd_until_state('new', 'test-fault', [], 'Stopped')

    def test_directory_query_keeps_native_cause_and_operation_context(self):
        fs = Filesystems(Mock())
        fs.manager.lxd.command.side_effect = Error('native socket permission denied')
        with self.assertRaises(Error) as caught:fs._directory('test-fault', '/home')
        self.assertIn('native socket permission denied', str(caught.exception))
        self.assertIn('/', str(caught.exception))
        from mas.i18n import t
        self.assertIn(t('fs_directory_query', path='/'), str(caught.exception))

    def test_listener_and_sshfs_failures_keep_both_streams(self):
        fs = Filesystems(Mock())
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for name in ('listener', 'sshfs'):
                (work/(name+'.out')).write_text('stdout detail')
                (work/(name+'.err')).write_text('stderr detail')
            with self.assertRaisesRegex(Error, 'stdout detail\nstderr detail'):
                fs._listener_details(Mock(poll=Mock(return_value=1)), work)
            with self.assertRaisesRegex(Error, 'stdout detail\nstderr detail'):
                fs._mount_observation({}, Mock(poll=Mock(return_value=None)), Mock(poll=Mock(return_value=1)), work)

    def test_unmount_failure_keeps_stdout_and_stderr(self):
        fs = Filesystems(Mock())
        fs._helpers = Mock(return_value=[])
        fs._actual = Mock(return_value=[{}])
        fs._matching = Mock(return_value=True)
        result = subprocess.CompletedProcess([], 1, 'stdout detail', 'stderr detail')
        with patch('mas.filesystems.subprocess.run', return_value=result):
            with self.assertRaisesRegex(Error, 'stdout detail\nstderr detail'):
                fs._cleanup({}, {'destination':'/unused'}, 0)


class TestArgumentReviewTests(unittest.TestCase):
    def test_invalid_timeout_never_installs_or_creates_suite(self):
        for arguments in ([], ['--install','/unused/installer','--product','/unused/product']):
            with self.subTest(arguments=arguments), patch.object(testing,'Suite') as suite, patch.object(testing,'install_and_test') as install:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    testing.main(['--timeout','299',*arguments])
                self.assertEqual(caught.exception.code, 2)
                suite.assert_not_called()
                install.assert_not_called()

    def test_valid_minimum_reaches_the_installer(self):
        with patch.object(testing, 'install_and_test', return_value=0) as install:
            self.assertEqual(testing.main(['--timeout','300','--install','/unused/installer','--product','/unused/product']), 0)
        self.assertEqual(install.call_args.args[0].timeout, 300)
