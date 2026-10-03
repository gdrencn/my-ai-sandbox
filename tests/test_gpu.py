import copy
import contextlib
import io
import json
import unittest
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from unittest.mock import Mock, patch

from mas.core import Error, MANAGED
from mas.gpu import GPU, KEY, CONF, CONTENT, PROFILE, PROFILE_CONTENT, devices
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
        self.manager.lxd.configuration.read.side_effect = self.read_config
        self.manager.lxd.configuration.write.side_effect = self.write_config
        self.profile = None
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
        if args[0] == 'query':
            parent = parse_qs(urlparse(args[1]).query)['path'][0]
            value, name = (self.file, 'mas-gpu.conf') if parent.endswith('ld.so.conf.d') else (self.profile, 'mas-gpu.sh')
            return json.dumps([name] if value is not None else [])
        if args[:2] == ['file','pull']:
            value = self.profile if args[2].endswith(PROFILE) else self.file
            Path(args[3]).write_text(value)
            return ''
        if args[:2] == ['file','delete']:
            if args[2].endswith(PROFILE): self.profile = None
            else: self.file = None
            return ''
        raise AssertionError(args)

    def config_etag(self):
        return json.dumps(self.item, sort_keys=True)

    def read_config(self, target):
        return copy.deepcopy(self.item), self.config_etag()

    def write_config(self, target, value, etag, **kwargs):
        if etag != self.config_etag():
            raise Error('configuration changed')
        self.edits.append(copy.deepcopy(value))
        self.item.update(self.edits[-1])

    def test_profile_cleanup_and_legacy_upgrade(self):
        self.gpu.set('test-unit', True)
        record = self.gpu.record(self.item)
        record.pop('runtime_profile')
        self.item['config'][KEY] = json.dumps(record)
        self.gpu.ensure('test-unit')
        self.assertEqual(self.gpu.record(self.item)['runtime_profile'], PROFILE)
        self.file, self.profile = CONTENT, PROFILE_CONTENT
        self.gpu.set('test-unit', False)
        self.assertIsNone(self.file)
        self.assertIsNone(self.profile)
        self.assertIsNone(self.gpu.record(self.item)['runtime_profile'])

    def test_foreign_profile_and_symlink_preserved_before_cleanup(self):
        self.gpu.set('test-unit', True)
        self.file, self.profile = CONTENT, 'user-owned profile'
        with self.assertRaises(Error): self.gpu.set('test-unit', False)
        self.assertEqual(self.file, CONTENT)
        self.assertEqual(self.profile, 'user-owned profile')
        original = self.command
        def symlink(args, **kw):
            if args[:2] == ['file', 'pull'] and args[2].endswith(PROFILE):
                Path(args[3]).symlink_to('/not-a-managed-file')
                return ''
            return original(args, **kw)
        self.manager.lxd.command.side_effect = symlink
        with self.assertRaises(Error): self.gpu.set('test-unit', False)
        self.assertEqual(self.file, CONTENT)

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
        self.manager.lxd.configuration.write.side_effect=Error('native failure')
        with self.assertRaises(Error):self.gpu.set('test-unit',True)
        self.assertNotIn(KEY,self.item['config'])
        self.manager.emit.assert_not_called()

    def test_concurrent_non_gpu_changes_are_preserved_without_success(self):
        original = self.write_config
        def concurrent(target, value, etag, **kwargs):
            self.item['config']['limits.memory'] = '16GiB'
            self.item['devices']['external'] = {'type': 'none'}
            return original(target, value, etag)
        self.manager.lxd.configuration.write.side_effect = concurrent
        with self.assertRaisesRegex(Error, 'configuration changed'):
            self.gpu.set('test-unit', True)
        self.assertEqual(self.item['config']['limits.memory'], '16GiB')
        self.assertEqual(self.item['devices']['external'], {'type': 'none'})
        self.assertNotIn(KEY, self.item['config'])
        self.assertEqual(self.edits, [])
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

    def test_menu_switch_reuses_manager_and_network_remains_without_gpu(self):
        for available in (True,False):
            view, manager=Mock(),Mock()
            manager.hardware.return_value={'available':available,'enabled':True}
            view.choose.side_effect=['gpu',False,None,None] if available else [None]
            with patch('mas.terminal_ui.sys.stdout',io.StringIO()):UI(view,manager).hardware('test-unit')
            choices=view.choose.call_args_list[0].args[1]
            self.assertEqual(len(choices),3 if available else 2)
            if available: self.assertIn(unittest.mock.call('test-unit',False, capability={'available':True,'enabled':True}), manager.hardware.call_args_list)

    def test_menu_reuses_discovery_for_switches_and_refresh(self):
        self.gpu.ensure('test-unit')
        from mas.core import Manager
        self.manager.gpu = self.gpu
        self.manager.network.status.return_value = {'enabled': True}
        self.manager.hardware.side_effect = lambda *a, **kw: Manager.hardware(self.manager, *a, **kw)
        view = Mock()
        view.choose.side_effect = ['gpu', False, None, 'gpu', True, None, None]
        with patch('mas.gpu.detect', return_value=CAP) as detect, contextlib.redirect_stdout(io.StringIO()):
            UI(view, self.manager).hardware('test-unit')
        self.assertEqual(detect.call_count, 1)
        defaults = [c.kwargs['default'] for c in view.choose.call_args_list if c.kwargs.get('radio')]
        self.assertEqual(defaults, [True, False])
        self.assertTrue(self.gpu.record(self.item)['enabled'])

    def test_menu_failure_reads_actual_configuration_without_discovery(self):
        self.gpu.ensure('test-unit')
        from mas.core import Manager
        self.manager.gpu = self.gpu
        self.manager.network.status.return_value = {'enabled': True}
        def hardware(target, enabled=None, **kwargs):
            result = Manager.hardware(self.manager, target, enabled, **kwargs)
            if enabled is not None:
                raise Error('failure after configuration changed')
            return result
        self.manager.hardware.side_effect = hardware
        view = Mock()
        view.choose.side_effect = ['gpu', False, None, 'gpu', True, None, None]
        with patch('mas.gpu.detect', return_value=CAP) as detect, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            UI(view, self.manager).hardware('test-unit')
        self.assertEqual(detect.call_count, 1)
        defaults = [c.kwargs['default'] for c in view.choose.call_args_list if c.kwargs.get('radio')]
        self.assertEqual(defaults, [True, False])
        self.assertIn('failure after configuration changed', err.getvalue())

    def test_driver_refresh_reuses_atomic_set(self):
        self.gpu.ensure('test-unit')
        changed = {**CAP, 'driver_paths': ['/usr/lib/wsl/drivers/nvidia-updated']}
        with patch('mas.gpu.detect', return_value=changed):
            self.gpu.ensure('test-unit')
        record = self.gpu.record(self.item)
        self.assertEqual(record['driver_paths'], changed['driver_paths'])
        self.assertEqual(len(self.edits), 2)
        self.assertNotIn(CAP['driver_paths'][0], str(self.item['devices']))

    def test_discovery_failure_preserves_record_and_off_bypasses_discovery(self):
        self.gpu.ensure('test-unit')
        before = copy.deepcopy(self.item)
        with patch('mas.gpu.detect', side_effect=Error('official query failed')) as query:
            with self.assertRaises(Error): self.gpu.ensure('test-unit')
            self.assertEqual(self.item, before)
            self.gpu.set('test-unit', False)
            query.reset_mock()
            self.gpu.ensure('test-unit')
            query.assert_not_called()

    def test_legacy_multiple_directories_are_replaced_by_official_selection(self):
        old = {**CAP, 'driver_paths': CAP['driver_paths'] + ['/usr/lib/wsl/drivers/old']}
        self.gpu.set('test-unit', True, capability=old)
        self.assertIn('mas-gpu-driver-1', self.item['devices'])
        self.gpu.ensure('test-unit')
        self.assertEqual(self.gpu.record(self.item)['driver_paths'], CAP['driver_paths'])
        self.assertNotIn('mas-gpu-driver-1', self.item['devices'])

    def test_discovery_failure_prevents_native_start_and_post_processing(self):
        from mas.core import Manager
        manager = Manager(Mock(timeout=600), isolation=Mock())
        manager.require = Mock(return_value=self.item)
        manager.filesystems.locked = Mock(side_effect=contextlib.nullcontext)
        manager.mountedfs = Mock(return_value=[])
        manager.gpu.ensure = Mock(side_effect=Error('official query failed'))
        manager._execute_lifecycle = Mock()
        manager._after_lifecycle = Mock()
        with self.assertRaises(Error): manager.start('test-unit')
        manager._execute_lifecycle.assert_not_called()
        manager._after_lifecycle.assert_not_called()

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
        manager = Manager(Mock(timeout=600), isolation=Mock())
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
