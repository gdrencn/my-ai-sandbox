"""Mas completion, external coordination and owned-resource failure boundaries."""
import contextlib
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from mas.core import Error, Manager, ShellExitError, confirm
from mas.diagnostics import cleanup_scope
from mas.i18n import progress_text
from tests.test_failures import instance
from tests import test_filesystems


class StageTests(unittest.TestCase):
    def setUp(self):
        language = patch('mas.config.language', return_value='en_us')
        language.start(); self.addCleanup(language.stop)
        self.events = []
        self.manager = Manager(Mock(timeout=300, prefix=['lxc']), self.events.append)
        self.manager.gpu = Mock()  # GPU behavior has independent unit/native coverage.
        self.manager.require = Mock(return_value=instance('Running'))

    def test_user_preparation_failure_has_no_function_completion_or_external_post(self):
        failure = Error('user preparation failed')
        self.manager._prepare_user = Mock(side_effect=failure)
        self.manager._after_lifecycle = Mock()
        with self.assertRaises(Error) as caught:
            self.manager.start('test-fault')
        self.assertIs(caught.exception, failure)
        self.assertEqual(self.events, [])
        self.manager._after_lifecycle.assert_not_called()

    def test_internal_start_completion_follows_user_preparation(self):
        def prepare(target):
            self.assertEqual(self.events, [])
            return instance('Running')
        self.manager._prepare_user = Mock(side_effect=prepare)
        self.manager.start('test-fault')
        self.assertEqual([(e['action'], e['scope'], e['status']) for e in self.events],
                         [('start', 'function', 'ok')])

    def test_native_and_function_success_are_distinct_in_both_languages(self):
        event = dict(action='start', target='demo', status='ok', observation='Running', elapsed=1)
        for language, label in [('en_us', 'Native step complete'), ('zh_cn', '原生步骤完成')]:
            with patch('mas.config.language', return_value=language):
                self.assertIn(label, progress_text({**event, 'scope':'native'}))
                self.assertNotIn(label, progress_text({**event, 'scope':'function'}))
                self.assertIn('警告' if language=='zh_cn' else 'Warning',
                              progress_text({**event, 'status':'warning'}))

    def test_redirected_progress_retains_function_success_and_native_warning_only(self):
        from mas.presentation import Progress
        stream = io.StringIO(); progress = Progress(stream)
        event = dict(action='start', target='demo', status='ok', observation='Running', elapsed=1)
        progress({**event, 'scope':'native', 'native_stderr':'Warning: native detail'})
        progress({**event, 'scope':'function'})
        self.assertNotIn('Native step complete', stream.getvalue())
        self.assertIn('Warning: native detail', stream.getvalue())
        self.assertEqual(stream.getvalue().count('[ok]'), 1)

    def test_import_mark_failure_never_reports_full_import_success(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)/'backup'; archive.touch()
            self.manager.absent = Mock()
            failure = Error('mark failed')
            self.manager._run_lxd_until_state = Mock(side_effect=[instance(owned=False), failure])
            with self.assertRaises(Error) as caught:
                self.manager.import_container('test-fault', archive)
            self.assertIs(caught.exception, failure)
            self.assertEqual(self.events, [])

    def test_stop_all_continues_after_os_error_and_names_failed_target(self):
        self.manager.list = Mock(return_value=[dict(name='first'), dict(name='second')])
        self.manager.stop = Mock(side_effect=[OSError('disk'), None])
        with self.assertRaisesRegex(Error, 'first: disk'):
            self.manager.stop_all()
        self.assertEqual(self.manager.stop.call_count, 2)

    def test_enter_preserves_shell_and_exit_handler_failures(self):
        self.manager.start = Mock()
        failure = Error('stop failed')
        self.manager.on_exit = Mock(side_effect=failure)
        with patch('mas.core.subprocess.call', return_value=9), self.assertRaises(ShellExitError) as caught:
            self.manager.enter('test-fault')
        self.assertIn('status 9', str(caught.exception))
        self.assertIn('stop failed', str(caught.exception))
        self.assertIs(caught.exception.__cause__, failure)

    def test_no_confirmation_provider_declines_without_loading_menu(self):
        with patch.dict('sys.modules', {'mas.menu':None}):
            self.assertFalse(confirm('delete?'))

    def test_reporting_failure_does_not_replace_operation_failure(self):
        failure = Error('primary')
        self.manager.report = Mock(side_effect=OSError('output closed'))
        self.manager.find = Mock(side_effect=failure)
        child = Mock(); child.poll.return_value = None
        with patch('mas.core.subprocess.Popen', return_value=child), contextlib.redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(Error) as caught:
                self.manager._run_lxd_until_state('start', 'test-fault', ['start'], 'Running')
        self.assertIs(caught.exception, failure)
        child.kill.assert_called_once()
        self.assertIn('reporting failed', output.getvalue())

    def test_client_cleanup_failure_keeps_original_error_and_reports_secondary(self):
        failure = Error('query failed')
        self.manager.find = Mock(side_effect=failure)
        child = Mock(); child.poll.return_value = None
        child.kill.side_effect = OSError('kill failed')
        with patch('mas.core.subprocess.Popen', return_value=child), self.assertRaises(Error) as caught:
            self.manager._run_lxd_until_state('start', 'test-fault', ['start'], 'Running')
        self.assertIs(caught.exception, failure)
        self.assertEqual(self.events[-1]['status'], 'warning')
        self.assertIn('kill failed', self.events[-1]['native_stderr'])

    def test_cleanup_preserves_primary_and_interrupt_but_propagates_standalone_failure(self):
        for primary in (Error('primary'), KeyboardInterrupt()):
            secondary = OSError('cleanup')
            report = Mock()
            with self.assertRaises(type(primary)) as caught:
                with cleanup_scope(Mock(side_effect=secondary), report):
                    raise primary
            self.assertIs(caught.exception, primary)
            report.assert_called_once_with(secondary)
        with self.assertRaisesRegex(OSError, 'cleanup'):
            with cleanup_scope(Mock(side_effect=OSError('cleanup'))):
                pass


class MountBoundaryTests(unittest.TestCase):
    def setUp(self):
        test_filesystems.FilesystemTests.setUp(self)
        self.manager.lxd.prefix = ["lxc"]
    entry = test_filesystems.FilesystemTests.entry

    def mount_environment(self):
        stack = contextlib.ExitStack()
        stack.enter_context(patch('mas.filesystems.fuse_access_ready', return_value=True))
        stack.enter_context(patch('mas.filesystems.shutil.which', return_value='/usr/bin/native'))
        stack.enter_context(patch.object(self.fs, '_directory'))
        stack.enter_context(patch('mas.filesystems.mounts', return_value=[]))
        stack.enter_context(patch.object(self.fs, '_helpers', return_value=[]))
        stack.enter_context(patch.object(self.fs, '_actual', return_value=[]))
        return stack

    def test_initial_journal_failure_is_inside_cleanup_boundary(self):
        original = self.fs._save
        calls = 0
        failure = OSError('first journal write')
        def save(data):
            nonlocal calls
            calls += 1
            if calls == 1: raise failure
            return original(data)
        with self.mount_environment(), patch.object(self.fs, '_save', side_effect=save), self.assertRaises(OSError) as caught:
            self.fs.mount('demo', '/home/sandbox')
        self.assertIs(caught.exception, failure)
        with self.fs.locked() as data:
            self.assertEqual(data['mounts'], [])
        self.assertFalse(self.fs.root.exists())

    def test_listener_launch_failure_reclaims_prepared_directories(self):
        failure = OSError('spawn failed')
        with self.mount_environment(), patch.object(self.fs, '_spawn', side_effect=failure), self.assertRaises(OSError) as caught:
            self.fs.mount('demo', '/home/sandbox')
        self.assertIs(caught.exception, failure)
        with self.fs.locked() as data:
            self.assertEqual(data['mounts'], [])
            self.assertEqual(data['directories'], {})
        self.assertFalse(self.fs.root.exists())

    def test_preexisting_work_directory_is_preserved_with_recovery_record(self):
        self.fs._private()
        work = self.fs.state/('a'*32); work.mkdir()
        (work/'known_hosts').write_text('keep')
        with self.mount_environment(), patch('mas.filesystems.uuid.uuid4', return_value=Mock(hex='a'*32)):
            with self.assertRaises(FileExistsError): self.fs.mount('demo', '/home/sandbox')
        self.assertEqual((work/'known_hosts').read_text(), 'keep')
        with self.fs.locked() as data:
            self.assertFalse(data['mounts'][0]['work_created'])

    def test_probes_only_observe_without_launching_or_publishing(self):
        work = self.base/'work'; work.mkdir()
        (work/'listener.out').write_text('SSH SFTP listening on 127.0.0.1:1234 password "secret"')
        listener = Mock(); listener.poll.return_value = None
        sshfs = Mock(); sshfs.poll.return_value = None
        entry = self.entry(); before = copy.deepcopy(entry)
        actual = dict(id=42, kind='fuse.sshfs', source=entry['source'])
        with patch.object(self.fs, '_spawn') as spawn, patch.object(self.fs, '_save') as save, patch.object(self.fs, '_actual', return_value=[actual]):
            self.assertEqual(self.fs._listener_details(listener, work), ('1234', 'secret'))
            self.assertEqual(self.fs._mount_observation(entry, listener, sshfs, work), actual)
            spawn.assert_not_called(); save.assert_not_called()
        self.assertEqual(entry, before)

    def test_mount_readiness_uses_one_deadline_and_publishes_before_success(self):
        calls = []
        def wait(*args, **kwargs):
            calls.append(kwargs)
            return ('1234','secret') if len(calls)==1 else dict(id=42)
        with self.mount_environment(), patch.object(self.fs, '_start_listener'), patch.object(self.fs, '_start_sshfs'), patch.object(self.fs, '_wait', side_effect=wait):
            self.fs.mount('demo', '/home/sandbox')
        self.assertEqual(calls[0]['deadline'], calls[1]['deadline'])
        self.assertEqual(calls[0]['started'], calls[1]['started'])
        with self.fs.locked() as data:
            self.assertEqual(data['mounts'][0]['mount_id'], 42)
        self.assertEqual(self.manager.emit.call_args.args[0]['scope'], 'function')
