import copy
import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

from mas.core import Error, MANAGED
from mas.gpu import GPU, KEY, CONF, CONTENT, devices
from mas.terminal_ui import UI

CAP = {'available': True, 'backend': 'wsl-nvidia', 'gpus': [{'name': 'NVIDIA test', 'uuid': 'GPU-test'}], 'driver_paths': ['/usr/lib/wsl/drivers/nvidia-test']}
NONE = {'available': False, 'backend': None, 'gpus': []}


class GPUTests(unittest.TestCase):
    def setUp(self):
        self.item = {'name': 'test-unit', 'type': 'container', 'status': 'Stopped',
                     'config': {MANAGED: 'true'}, 'devices': {'root': {'type': 'disk', 'path': '/', 'pool': 'default'}}}
        self.manager = Mock()
        self.manager.lxd.timeout = 600
        self.manager.lxd.project = 'default'
        self.manager.require.side_effect = self.require
        self.manager.filesystems.locked.side_effect = contextlib.nullcontext
        self.manager.lxd.command.side_effect = self.command
        self.file = None
        self.edits = []
        self.gpu = GPU(self.manager)
        p = patch('mas.gpu.detect', return_value=CAP)
        p.start();self.addCleanup(p.stop)

    def require(self, target, stopped=False):
        if self.item['config'].get(MANAGED) != 'true': raise Error('unmanaged')
        if stopped and self.item['status'] != 'Stopped': raise Error('running')
        return copy.deepcopy(self.item)

    def command(self, args, input_data=None):
        if args[0] == 'query' and '/files?' not in args[1]:
            return json.dumps({k: self.item[k] for k in ('config','devices')})
        if args[:2] == ['config', 'edit']:
            self.edits.append(json.loads(input_data)); self.item.update(self.edits[-1]);return ''
        if args[0] == 'query': return json.dumps(['mas-gpu.conf'] if self.file is not None else [])
        if args[:2] == ['file','pull']: return self.file
        if args[:2] == ['file','delete']: self.file = None;return ''
        raise AssertionError(args)

    def test_default_enable_disable_and_preserve_other_devices(self):
        self.gpu.ensure('test-unit')
        status = self.gpu.status('test-unit')
        self.assertTrue(status['enabled']);self.assertTrue(status['configured'])
        self.assertEqual(status['resources']['devices'], devices('wsl-nvidia', CAP['driver_paths']))
        self.file = CONTENT
        self.gpu.set('test-unit',False)
        self.assertIsNone(self.file)
        self.assertEqual(set(self.item['devices']), {'root'})
        self.gpu.ensure('test-unit')
        self.assertFalse(self.gpu.status('test-unit')['enabled'])
        self.assertEqual(len(self.edits), 2)

    def test_no_hardware_has_no_side_effect_and_rejects_enable(self):
        with patch('mas.gpu.detect',return_value=NONE):
            self.gpu.ensure('test-unit')
            self.assertFalse(self.gpu.status('test-unit')['available'])
            with self.assertRaises(Error): self.gpu.set('test-unit',True)
        self.assertEqual(self.edits, [])

    def test_running_and_unmanaged_rejected(self):
        self.item['status']='Running'
        with self.assertRaises(Error): self.gpu.set('test-unit',True)
        self.item['config'][MANAGED]='false'
        with self.assertRaises(Error): self.gpu.status('test-unit')
        self.assertEqual(self.edits, [])

    def test_conflicts_and_corrupt_records_preserved(self):
        for definition in ({'type':'gpu'}, {'type':'disk','path':'/usr/lib/wsl'},
                           {'type':'unix-char','path':'/dev/dxg'}):
            self.item['expanded_devices']={'foreign':definition}
            with self.assertRaises(Error): self.gpu.set('test-unit',True)
        self.item.pop('expanded_devices')
        self.item['config'][KEY]='{corrupt'
        with self.assertRaises(Error): self.gpu.ensure('test-unit')
        self.assertEqual(self.edits, [])

    def test_device_drift_and_foreign_runtime_file_preserved(self):
        self.gpu.set('test-unit',True)
        self.item['devices']['mas-gpu-lib']['readonly']='false'
        with self.assertRaises(Error): self.gpu.set('test-unit',False)
        self.item['devices']['mas-gpu-lib']['readonly']='true'
        self.file='foreign'
        with self.assertRaises(Error): self.gpu.set('test-unit',False)
        self.assertEqual(self.file,'foreign')
        self.assertEqual(len(self.edits),1)

    def test_failed_atomic_edit_does_not_publish_success(self):
        original=self.command
        def fail(args, **kw):
            if args[:2]==['config','edit']:raise Error('native failure')
            return original(args,**kw)
        self.manager.lxd.command.side_effect=fail
        with self.assertRaises(Error):self.gpu.set('test-unit',True)
        self.assertNotIn(KEY,self.item['config'])
        self.manager.emit.assert_not_called()

    def test_missing_host_gpu_still_allows_owned_cleanup(self):
        self.gpu.set('test-unit',True)
        with patch('mas.gpu.detect',return_value=NONE):
            with self.assertRaises(Error):self.gpu.ensure('test-unit')
            self.gpu.set('test-unit',False)
        self.assertFalse(self.gpu.record(self.item)['enabled'])

    def test_repeat_and_runtime_preparation(self):
        self.gpu.set('test-unit',True);self.gpu.set('test-unit',True)
        self.gpu.prepare('test-unit')
        args=self.manager._run_lxd_until_state.call_args.args
        self.assertEqual(args[0],'gpu-runtime')
        self.assertIn('ldconfig',args[2][-1])
        self.assertEqual(len(self.item['devices']),4)

    def test_menu_switch_reuses_manager_and_no_gpu_has_only_back(self):
        for available in (True,False):
            view, manager=Mock(),Mock()
            manager.hardware.return_value={'available':available,'enabled':True}
            view.choose.side_effect=['gpu',False,None,None] if available else [None]
            with patch('mas.terminal_ui.sys.stdout',io.StringIO()):UI(view,manager).hardware('test-unit')
            choices=view.choose.call_args_list[0].args[1]
            self.assertEqual(len(choices),2 if available else 1)
            if available: self.assertIn(unittest.mock.call('test-unit',False), manager.hardware.call_args_list)

    def test_driver_refresh_reuses_atomic_set(self):
        self.gpu.ensure('test-unit')
        changed = {**CAP, 'driver_paths': ['/usr/lib/wsl/drivers/nvidia-updated']}
        with patch('mas.gpu.detect', return_value=changed):
            self.gpu.ensure('test-unit')
        record = self.gpu.record(self.item)
        self.assertEqual(record['driver_paths'], changed['driver_paths'])
        self.assertEqual(len(self.edits), 2)

    def test_cleanup_does_not_depend_on_working_host_discovery(self):
        self.gpu.set('test-unit', True)
        with patch('mas.gpu.detect', side_effect=Error('driver broken')):
            self.gpu.set('test-unit', False)
        self.assertFalse(self.gpu.record(self.item)['enabled'])

    def test_bad_driver_paths_cannot_authorize_host_files(self):
        self.gpu.set('test-unit', True)
        record = self.gpu.record(self.item)
        for path in ['/etc', '/usr/lib/wsl/drivers/..', '/usr/lib/wsl/drivers/x/../../etc']:
            bad = {**record, 'driver_paths': [path]}
            self.item['config'][KEY] = json.dumps(bad)
            with self.assertRaises(Error): self.gpu.record(self.item)

    def test_gpu_prepare_failure_prevents_start_completion(self):
        from mas.core import Manager
        manager = Manager(Mock(timeout=600))
        manager.gpu = Mock()
        manager.gpu.prepare.side_effect = Error('runtime failure')
        manager._prepare_user = Mock(return_value={})
        manager._completed = Mock()
        with self.assertRaises(Error):
            manager._execute_lifecycle('test-unit', 'start', {'status': 'Running'})
        manager._completed.assert_not_called()

    def test_unrecorded_runtime_file_is_not_overwritten(self):
        self.file = 'foreign configuration'
        with self.assertRaises(Error): self.gpu.set('test-unit', True)
        self.assertEqual(self.file, 'foreign configuration')
        self.assertEqual(self.edits, [])

    def test_runtime_removal_is_observed_before_config_publication(self):
        self.gpu.set('test-unit', True)
        self.file = CONTENT
        original = self.command
        def delay(args, **kw):
            if args[:2] == ['file', 'delete']: return ''
            return original(args, **kw)
        self.manager.lxd.command.side_effect = delay
        with patch('mas.gpu.time.sleep', side_effect=lambda _: setattr(self, 'file', None)) as wait:
            self.gpu.set('test-unit', False)
        wait.assert_called_once_with(1)
        self.assertIsNone(self.file)
