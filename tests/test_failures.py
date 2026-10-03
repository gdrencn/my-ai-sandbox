"""Fault injection for lifecycle guarantees that should not damage a real host."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import sys
import time
import unittest
from unittest.mock import Mock, patch
from mas.core import Error, LXD, MANAGED, Manager


def instance(status='Stopped', owned=True, kind='container'):
    return dict(name='test-fault', status=status, type=kind,
                config={MANAGED: 'true'} if owned else {})


class FailureTests(unittest.TestCase):
    def setUp(self):
        language = patch('mas.config.language', return_value='en_us')
        language.start()
        self.addCleanup(language.stop)

    def manager(self, item=None):
        lxd = Mock(prefix=['lxc', '--project', 'test-isolated'], timeout=300)
        lxd.instances.return_value = [item or instance()]
        manager = Manager(lxd, Mock(), isolation=Mock())
        # Import orchestration has its own tests. These cases exercise the
        # foundation's marking and completion boundary after a native result.
        manager.imports = Mock()
        manager.imports.restore.side_effect = lambda target, path: manager._run_lxd_until_state(
            'import', target, ['import', 'local:', str(path), target], 'Stopped', require_marker=False)
        return manager

    def operation(self, observations, codes, expected='Running', error=None):
        manager = self.manager()
        manager.find = Mock(side_effect=observations)
        process = Mock()
        process.poll.side_effect = codes
        clock = [0]
        with patch('mas.core.subprocess.Popen', return_value=process), \
                patch('mas.core.time.monotonic', side_effect=lambda: clock[0]), \
                patch('mas.core.time.sleep', side_effect=lambda delay: clock.__setitem__(0, clock[0]+delay)):
            if error:
                with self.assertRaises(error):
                    manager._run_lxd_until_state('start', 'test-fault', ['start', 'local:test-fault'], expected)
            else:
                manager._run_lxd_until_state('start', 'test-fault', ['start', 'local:test-fault'], expected)
        return manager, process, clock[0]

    def test_state_success_still_waits_for_native_completion(self):
        manager, process, elapsed = self.operation([instance('Running')]*3, [None,None,0,0])
        self.assertEqual(elapsed, 2)
        self.assertEqual(manager.report.call_args.args[0]['status'], 'ok')
        process.kill.assert_not_called()

    def test_live_output_arrives_between_state_queries_without_query_flooding(self):
        manager=self.manager(); manager.lxd.prefix=[sys.executable]; manager.lxd.timeout=3
        manager.find=Mock(return_value=instance('Running'))
        seen=[]
        manager.report=lambda event: seen.append((time.monotonic(),event.copy()))
        source="import time;print('FIRST installation output',flush=True);time.sleep(.15);print('SECOND installation output',flush=True);time.sleep(.3)"
        manager._run_lxd_until_state('prepare-user','test-fault',['-c',source],'Running',live_output=True)
        first=next(moment for moment,event in seen if event.get('live_lines')==['FIRST installation output'])
        second=next(moment for moment,event in seen if event.get('live_lines')==['SECOND installation output'])
        self.assertLess(second-first,.75)
        self.assertEqual(manager.find.call_count,2)  # Initial state and native completion.
        self.assertIn('FIRST installation output',seen[-1][1]['native_stdout'])
        self.assertIn('SECOND installation output',seen[-1][1]['native_stdout'])
        self.assertEqual(seen[-1][1]['status'],'ok')

    def test_native_failure_wins_over_apparent_success(self):
        manager, process, elapsed = self.operation([instance('Running')], [7,7], error=Error)
        manager.find.assert_not_called()
        self.assertEqual(elapsed, 0)
        self.assertTrue(manager.report.call_args.args[0]['native_failure'])
        process.kill.assert_not_called()

    def test_error_state_and_failed_query_stop_live_client(self):
        for observed in (instance('Error'), Error('lost query')):
            with self.subTest(observed=observed):
                manager, process, elapsed = self.operation([observed], [None,None], error=Error)
                process.kill.assert_called_once()
                process.wait.assert_called_once()
                self.assertEqual(elapsed, 0)
                self.assertEqual(manager.report.call_args.args[0]['status'], 'error')

    def test_interrupt_stops_client_and_retains_failure_event(self):
        manager, process, _ = self.operation([KeyboardInterrupt()], [None,None], error=KeyboardInterrupt)
        process.kill.assert_called_once()
        process.wait.assert_called_once()
        self.assertEqual(manager.report.call_args.args[0]['status'], 'error')

    def test_success_requires_instance_local_marker(self):
        manager, _, elapsed = self.operation([instance('Running',False),instance('Running')], [0,0,0])
        self.assertEqual(elapsed, 1)
        self.assertEqual(manager.find.call_count, 2)

    def test_structurally_invalid_list_data_is_an_explicit_error(self):
        client = LXD.__new__(LXD)
        for value in ({}, None, [None], [{}], [dict(name='test-fault',type='container',status='Stopped',config=[])],
                      [dict(name=1,type='container',status='Stopped',config={})]):
            client.command = Mock(return_value=json.dumps(value))
            with self.subTest(value=value), self.assertRaisesRegex(Error, 'invalid instance data'):
                Manager(client, isolation=Mock()).absent('test-fault')

    def test_query_timeout_and_nonzero_exit_are_explicit_errors(self):
        client = LXD.__new__(LXD)
        client.prefix, client.timeout = ['lxc'], 300
        for result in (subprocess.TimeoutExpired(['lxc'],300), subprocess.CompletedProcess(['lxc'],1,'','permission denied')):
            with self.subTest(result=result), patch('mas.core.subprocess.run', side_effect=result if isinstance(result,Exception) else None,
                                                   return_value=result), self.assertRaises(Error):
                client.instances()

    def test_running_start_prepares_user_but_does_not_restart(self):
        manager = self.manager(instance('Running'))
        manager._run_lxd_until_state = Mock()
        manager.start('test-fault')
        self.assertEqual([call.args[0] for call in manager._run_lxd_until_state.call_args_list], ['prepare-user'])

    def test_stopped_stop_is_noop_and_transitional_states_are_rejected(self):
        manager = self.manager()
        manager._run_lxd_until_state = Mock()
        manager.stop('test-fault')
        manager._run_lxd_until_state.assert_not_called()
        for state in ('Frozen', 'Starting', 'Stopping', 'Error'):
            manager.lxd.instances.return_value = [instance(state)]
            for method in (manager.start, manager.stop):
                with self.subTest(state=state,method=method.__name__), self.assertRaises(Error):
                    method('test-fault')
        manager._run_lxd_until_state.assert_not_called()

    def test_stop_all_continues_and_aggregates_failures(self):
        manager = self.manager()
        manager.list = Mock(return_value=[dict(name='test-first'),dict(name='test-second'),dict(name='test-third')])
        manager.stop = Mock(side_effect=[Error('first failure'),None,Error('third failure')])
        with self.assertRaisesRegex(Error, r'first failure[\s\S]*third failure'):
            manager.stop_all()
        self.assertEqual([call.args[0] for call in manager.stop.call_args_list], ['test-first','test-second','test-third'])

    def test_list_sorts_and_rejects_vm_and_profile_only_marker(self):
        manager = self.manager()
        first, last = instance(), instance()
        first['name'],last['name']='test-a','test-z'
        inherited = instance(owned=False)
        inherited['expanded_config']={MANAGED:'true'}
        manager.lxd.instances.return_value=[last,instance(kind='virtual-machine'),inherited,first]
        self.assertEqual([item['name'] for item in manager.list()], ['test-a','test-z'])

    def test_enter_start_failure_prevents_shell_and_exit_handler(self):
        manager = self.manager()
        manager.start = Mock(side_effect=Error('prepare failed'))
        manager.on_exit = Mock()
        with patch('mas.core.subprocess.call') as shell, self.assertRaises(Error):
            manager.enter('test-fault')
        shell.assert_not_called()
        manager.on_exit.assert_not_called()

    def test_shell_failure_still_runs_exit_handler_before_reporting(self):
        manager = self.manager()
        manager.start,manager.stop = Mock(),Mock()
        with patch('mas.core.subprocess.call', return_value=9), self.assertRaisesRegex(Error, 'status 9'):
            manager.enter('test-fault',lambda _:True)
        manager.stop.assert_called_once_with('test-fault')

    def test_import_failure_or_vm_never_adds_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            backup=Path(directory)/'backup';backup.write_bytes(b'fixture')
            for result in (Error('import failed'), instance(kind='virtual-machine')):
                manager=self.manager();manager.lxd.instances.return_value=[]
                manager._run_lxd_until_state=Mock(side_effect=result if isinstance(result,Exception) else None,return_value=result)
                with self.subTest(result=result),self.assertRaises(Error):
                    manager.import_container('test-fault',backup)
                self.assertEqual(manager._run_lxd_until_state.call_count,1)

    def test_import_marks_only_after_success_and_checks_final_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            backup=Path(directory)/'backup';backup.touch()
            manager=self.manager();manager.lxd.instances.return_value=[]
            manager._run_lxd_until_state=Mock(side_effect=[instance(owned=False),Error('mark failed')])
            with self.assertRaisesRegex(Error,'mark failed'):
                manager.import_container('test-fault',backup)
            calls=manager._run_lxd_until_state.call_args_list
            self.assertEqual([call.args[0] for call in calls],['import','mark-import'])
            self.assertFalse(calls[0].kwargs['require_marker'])
            self.assertNotIn('require_marker',calls[1].kwargs)

    def archive(self,path,metadata=True):
        with tarfile.open(path,'w:gz') as archive:
            info=tarfile.TarInfo('backup/index.yaml' if metadata else 'unrelated.txt')
            info.size=1
            archive.addfile(info,io.BytesIO(b'x'))

    def test_export_failures_preserve_destination_and_remove_temporary_files(self):
        for failure in ('native','corrupt','metadata','publish'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory:
                destination=Path(directory)/'backup';destination.write_bytes(b'original')
                manager=self.manager()
                def export(action,target,args,expected):
                    backup=Path(args[-1])
                    if failure=='native':
                        backup.write_bytes(b'partial');raise Error('native failed')
                    if failure=='corrupt':backup.write_bytes(b'not an archive')
                    else:self.archive(backup,metadata=failure!='metadata')
                manager._run_lxd_until_state=Mock(side_effect=export)
                with patch('mas.core.os.replace',side_effect=OSError('publish failed')) if failure=='publish' else contextlib.nullcontext():
                    with self.assertRaises(Error):manager.export('test-fault',destination,lambda _:True)
                self.assertEqual(destination.read_bytes(),b'original')
                self.assertEqual(list(Path(directory).iterdir()),[destination])

    def test_export_does_not_overwrite_file_created_during_export(self):
        with tempfile.TemporaryDirectory() as directory:
            destination=Path(directory)/'backup'
            manager=self.manager()
            def export(action,target,args,expected):
                self.archive(Path(args[-1]));destination.write_bytes(b'concurrent file')
            manager._run_lxd_until_state=Mock(side_effect=export)
            with self.assertRaises(Error):manager.export('test-fault',destination)
            self.assertEqual(destination.read_bytes(),b'concurrent file')
            self.assertEqual(list(Path(directory).iterdir()),[destination])

    def test_export_rechecks_state_and_rejects_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);destination=root/'backup';destination.write_bytes(b'original')
            manager=self.manager();manager._run_lxd_until_state=Mock()
            def confirm(_):manager.lxd.instances.return_value=[instance('Running')];return True
            with self.assertRaises(Error):manager.export('test-fault',destination,confirm)
            manager.lxd.instances.return_value=[instance()]
            link=root/'link';link.symlink_to(destination)
            for path in (root,link,root/'missing'/'backup'):
                with self.subTest(path=path),self.assertRaises(Error):manager.export('test-fault',path,lambda _:True)
            manager._run_lxd_until_state.assert_not_called()
            self.assertEqual(destination.read_bytes(),b'original')
