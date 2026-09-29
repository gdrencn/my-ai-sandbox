"""Sequential reuse, native failure propagation and shared registry locking."""
import fcntl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from mas.core import Manager, Error, MANAGED


class LifecycleMountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.instance = dict(name='demo', type='container', status='Stopped', config={MANAGED:'true'})
        self.lxd = Mock(timeout=300, project='default')
        self.lxd.instances.side_effect = lambda *args: [self.instance.copy()]
        self.manager = Manager(self.lxd, fs_root=self.base/'root', fs_state=self.base/'state')
        self.entries = [dict(path='/a',destination=str(self.base/'root/demo/a'),default=True),
                        dict(path='/b',destination=str(self.base/'root/demo/b'),default=False),
                        dict(path='/c',destination=str(self.base/'root/demo/c'),default=False)]
        self.manager.mountedfs = Mock(return_value=self.entries)
        self.trace=[]
        self.manager.unmountfs = Mock(side_effect=lambda target,path:self.trace.append(('unmount',path)))
        self.manager.mountfs = Mock(side_effect=lambda target,path,**kw:self.trace.append(('mount',path,kw)))
        def operation(action,*args,**kwargs):
            self.trace.append((action,))
            if action=='start': self.instance['status']='Running'
            if action=='stop': self.instance['status']='Stopped'
            return self.instance.copy()
        self.manager._run_lxd_until_state = Mock(side_effect=operation)
        self.language=patch('mas.config.language',return_value='en_us');self.language.start();self.addCleanup(self.language.stop)

    def test_success_preserves_order_exact_paths_and_default_flag(self):
        for action,status in [('start','Stopped'),('stop','Running')]:
            self.instance['status']=status;self.trace.clear()
            getattr(self.manager,action)('demo')
            sequence=[x[0] for x in self.trace]
            self.assertEqual(sequence, ['unmount']*3+[action]+(['prepare-user'] if action=='start' else [])+['mount']*3)
            self.assertEqual(self.trace[-3:], [('mount',e['path'],{'default_home':e['default']}) for e in self.entries])

    def test_unmount_failure_stops_immediately_without_lifecycle_or_rollback(self):
        for failure in (0,1):
            self.trace.clear()
            self.manager.unmountfs.reset_mock();self.manager._run_lxd_until_state.reset_mock()
            self.manager.unmountfs.side_effect = [None]*failure+[Error('BUSY')]
            with self.assertRaisesRegex(Error,'BUSY') as caught:self.manager.start('demo')
            self.assertIn(self.entries[failure]['path'],str(caught.exception))
            self.assertEqual(self.manager.unmountfs.call_count,failure+1)
            self.manager._run_lxd_until_state.assert_not_called();self.manager.mountfs.assert_not_called()

    def test_native_failure_is_unchanged_and_does_not_run_suffix(self):
        failure=Error('EXACT_NATIVE_FAILURE')
        self.manager._run_lxd_until_state.side_effect=failure
        with self.assertRaises(Error) as caught:self.manager.start('demo')
        self.assertIs(caught.exception,failure)
        self.assertEqual(self.manager.unmountfs.call_count,3)
        self.manager.mountfs.assert_not_called()

    def test_prepare_failure_uses_original_error_without_restoration(self):
        failure=Error('USER_SETUP_FAILURE')
        self.manager._run_lxd_until_state.side_effect=[None,failure]
        with self.assertRaises(Error) as caught:self.manager.start('demo')
        self.assertIs(caught.exception,failure)
        self.manager.mountfs.assert_not_called()

    def test_restore_failure_attempts_every_remaining_path_and_keeps_state(self):
        self.manager.mountfs.side_effect=[Error('FIRST'),None,Error('LAST')]
        with self.assertRaisesRegex(Error,'Running') as caught:self.manager.start('demo')
        self.assertEqual(self.manager.mountfs.call_count,3)
        self.assertIn('/a → ',str(caught.exception));self.assertIn('/c → ',str(caught.exception))
        self.assertNotIn('/b → ',str(caught.exception))
        self.assertEqual(self.instance['status'],'Running')
        self.assertNotIn(('stop',),self.trace)

    def test_no_state_change_leaves_mounts_alone(self):
        self.instance['status']='Running';self.manager.start('demo')
        self.instance['status']='Stopped';self.manager.stop('demo')
        self.manager.mountedfs.assert_not_called();self.manager.unmountfs.assert_not_called();self.manager.mountfs.assert_not_called()
        self.assertEqual(self.trace,[('prepare-user',)])

    def test_reentrant_lock_reloads_records_and_keeps_outer_exclusivity(self):
        fs=self.manager.filesystems
        self.assertIs(fs,self.manager.filesystems)
        with fs.locked() as initial:
            self.assertEqual(fs.list('demo'),[])
            with fs.locked() as inner:
                fs._save(inner)
            with (fs.state/'lock').open('rb') as competing:
                with self.assertRaises(BlockingIOError):fcntl.flock(competing,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with (fs.state/'lock').open('rb') as competing:
            fcntl.flock(competing,fcntl.LOCK_EX|fcntl.LOCK_NB)

    def test_stop_failure_keeps_original_error_and_skips_restoration(self):
        self.instance['status']='Running'
        failure=Error('STOP_NATIVE_FAILURE')
        self.manager._run_lxd_until_state.side_effect=failure
        with self.assertRaises(Error) as caught:self.manager.stop('demo')
        self.assertIs(caught.exception,failure)
        self.assertEqual(self.manager.unmountfs.call_count,3)
        self.manager.mountfs.assert_not_called()

    def test_state_changed_before_lock_recheck_skips_external_processing(self):
        for action,initial,final in [('start','Stopped','Running'),('stop','Running','Stopped')]:
            with self.subTest(action=action):
                self.manager.require=Mock(side_effect=[{**self.instance,'status':initial},
                                                      {**self.instance,'status':final}])
                self.manager._run_lxd_until_state.reset_mock()
                getattr(self.manager,action)('demo')
                self.manager.mountedfs.assert_not_called()
                self.manager.unmountfs.assert_not_called()
                self.manager.mountfs.assert_not_called()
                self.assertEqual(self.manager._run_lxd_until_state.call_count,1 if action=='start' else 0)

    def test_stop_unmount_failure_prevents_native_call_and_remaining_paths(self):
        self.instance['status']='Running'
        self.manager.unmountfs.side_effect=[None,OSError('BUSY')]
        with self.assertRaisesRegex(Error,'BUSY'):self.manager.stop('demo')
        self.assertEqual(self.manager.unmountfs.call_count,2)
        self.manager._run_lxd_until_state.assert_not_called()
        self.manager.mountfs.assert_not_called()
