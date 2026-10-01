"""Policy boundaries without guest execution; native enforcement is tested separately."""
import copy
import contextlib
import json
import unittest
from unittest.mock import Mock, patch

from mas.core import Error, MANAGED, Manager
from mas.gpu import GPU, KEY as GPU_KEY, devices as gpu_devices
from mas.isolation import BASE_CONFIG, BASE_PROJECT, Isolation, KEY, PROFILE, PROFILE_KEY
from mas.terminal_ui import UI


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.language = patch('mas.config.language', return_value='en_us')
        self.language.start(); self.addCleanup(self.language.stop)
        self.manager = Mock()
        self.manager.lxd.project = 'mas'
        self.manager.gpu = GPU(self.manager)
        self.policy = Isolation(self.manager)
        self.record = {'version': 1, 'pool': 'default', 'network': 'lxdbr0', 'backends': [], 'driver_paths': []}
        self.project = {'config': self.policy.project_config(self.record)}
        self.profile = {'config': {**BASE_CONFIG, PROFILE_KEY: '1'}, 'devices': self.policy.devices(self.record)}
        self.item = {'name': 'test-policy', 'type': 'container', 'status': 'Stopped', 'profiles': [PROFILE],
                     'config': {MANAGED: 'true'}, 'devices': {},
                     'expanded_config': {**BASE_CONFIG, MANAGED: 'true'},
                     'expanded_devices': self.policy.devices(self.record)}
        self.policy.resource = Mock(side_effect=self.resource)
        self.policy.check_network = Mock()

    def resource(self, kind, name):
        return copy.deepcopy(self.project if kind == 'projects' else self.profile), '"etag"', '/fixture'

    def audit(self, item=None, **kwargs):
        return self.policy.audit(item or self.item, **kwargs)

    def test_baseline_is_observed_without_writes(self):
        self.audit()
        self.policy.api.request.assert_not_called()
        self.policy.api.update.assert_not_called()

    def test_project_restrictions_and_idmap_exceptions_are_not_repaired(self):
        for key in BASE_PROJECT:
            with self.subTest(key=key):
                original = self.project['config'][key]
                self.project['config'][key] = 'block' if original == 'allow' else 'allow'
                with self.assertRaises(Error): self.policy.check()
                self.assertNotEqual(self.project['config'][key], original)
                self.project['config'][key] = original
        self.project['config']['restricted.idmap.uid'] = '1000'
        with self.assertRaises(Error): self.policy.check()
        self.policy.api.update.assert_not_called()

    def test_profile_config_or_device_drift_is_refused(self):
        self.profile['config']['security.syscalls.deny_default'] = 'false'
        with self.assertRaises(Error): self.policy.check()
        self.profile['config'].pop('security.syscalls.deny_default')
        with self.assertRaises(Error): self.policy.check()
        self.profile['config'] = {**BASE_CONFIG, PROFILE_KEY: '1'}
        self.profile['devices']['secret'] = {'type': 'disk', 'source': '/home', 'path': '/host'}
        with self.assertRaises(Error): self.policy.check()
        self.policy.api.update.assert_not_called()

    def test_local_security_overrides_prevent_start_before_unmount(self):
        manager = Manager(Mock(), isolation=self.policy)
        manager.require = Mock(return_value=self.item)
        manager.filesystems = Mock()
        self.item['expanded_config']['security.syscalls.deny_default'] = 'false'
        with self.assertRaises(Error): manager.start('test-policy')
        manager.filesystems.locked.assert_not_called()
        manager.lxd.command.assert_not_called()

    def test_absent_lowlevel_keys_are_not_replaced_by_false(self):
        for key in ('raw.seccomp', 'raw.idmap', 'linux.kernel_modules', 'security.delegate_bpf',
                    'security.delegate_bpf.cmd_types', 'security.devlxd.images', 'security.syscalls.allow'):
            with self.subTest(key=key):
                self.item['expanded_config'][key] = 'false'
                with self.assertRaises(Error): self.audit()
                self.item['expanded_config'].pop(key)

    def test_unexpected_device_categories_and_pool_volumes_are_refused(self):
        for definition in ({'type':'unix-char','source':'/dev/null','path':'/extra'},
                           {'type':'disk','pool':'default','source':'extra-volume','path':'/data'},
                           {'type':'disk','source':'/etc','path':'/host','readonly':'true'},
                           {'type':'usb','vendorid':'1234'}, {'type':'tpm','path':'/dev/tpm0'}):
            with self.subTest(definition=definition):
                self.item['expanded_devices']['extra'] = definition
                with self.assertRaises(Error): self.audit()
        self.item['expanded_devices'].pop('extra')
        self.audit()

    def test_gpu_allowlist_requires_record_exact_paths_and_readonly(self):
        paths = ['/usr/lib/wsl/drivers/nvidia-test']
        definitions = gpu_devices('wsl-nvidia', paths)
        record = {'version':1, 'enabled':True, 'backend':'wsl-nvidia', 'driver_paths':paths,
                  'devices':definitions, 'runtime_file':'/etc/ld.so.conf.d/mas-gpu.conf',
                  'runtime_profile':'/etc/profile.d/mas-gpu.sh'}
        self.record['backends'] = ['wsl-nvidia']
        self.record['driver_paths'] = paths
        self.project['config'] = self.policy.project_config(self.record)
        self.item['config'][GPU_KEY] = json.dumps(record)
        self.item['devices'].update(copy.deepcopy(definitions))
        self.item['expanded_devices'].update(copy.deepcopy(definitions))
        self.audit()
        self.item['expanded_devices']['mas-gpu-lib']['readonly'] = 'false'
        with self.assertRaises(Error): self.audit()
        self.item['expanded_devices']['mas-gpu-lib']['readonly'] = 'true'
        self.item['config'].pop(GPU_KEY)
        with self.assertRaises(Error): self.audit()

    def test_legacy_mapping_default_is_accepted_but_explicit_override_is_not(self):
        self.item['profiles'] = ['default']
        self.item['expanded_config'].pop('security.idmap.isolated')
        self.item['expanded_devices']['eth0'] = {'type':'nic','name':'eth0','nictype':'bridged','parent':'lxdbr0'}
        self.audit(legacy=True)
        with self.assertRaises(Error): self.audit()
        self.item['config']['security.idmap.isolated'] = 'false'
        with self.assertRaises(Error): self.audit(legacy=True)

    def test_records_cannot_expand_host_resource_paths_or_change_backend(self):
        for key, value in [('pool','../host'), ('network','/host'), ('backends',['other']),
                           ('backends',['wsl-nvidia']), ('driver_paths',['/home/gordon']), ('version',True)]:
            with self.subTest(key=key):
                record = {**self.record, key:value}
                with self.assertRaises(Error): self.policy.record({'config':{KEY:json.dumps(record)}})

    def test_malformed_effective_configuration_fails_explicitly(self):
        self.item['expanded_config']['security.privileged'] = False
        with self.assertRaises(Error): self.audit()
        self.item['expanded_config'] = []
        with self.assertRaises(Error): self.audit()

    def test_migration_decline_and_failure_preserve_source(self):
        policy, legacy = Mock(), Mock()
        legacy.require.return_value = self.item
        legacy.filesystems.deletion_guard.side_effect = contextlib.nullcontext
        manager = Manager(Mock(timeout=300), isolation=policy)
        manager.legacy = legacy
        manager.absent = Mock()
        manager.gpu = Mock()
        manager.gpu.record.return_value = None
        manager._run_lxd_until_state = Mock(side_effect=Error('native failure'))
        self.assertFalse(manager.migrate('test-policy', lambda _:False))
        manager._run_lxd_until_state.assert_not_called()
        with self.assertRaisesRegex(Error,'native failure'):
            manager.migrate('test-policy', lambda _:True)
        legacy.delete.assert_not_called()
        legacy.lxd.command.assert_not_called()

    def test_menu_migration_uses_shared_operation_and_confirmation(self):
        view, manager = Mock(), Mock()
        manager.legacy_list.return_value = [self.item]
        view.choose.side_effect = ['test-policy', None]
        UI(view, manager).migration()
        manager.migrate.assert_called_once_with('test-policy', view.confirm)

    def test_safe_stop_does_not_require_a_valid_startup_policy(self):
        manager = Manager(Mock(), isolation=Mock(side_effect=Error('unsafe')))
        manager.require = Mock(return_value={**self.item, 'status':'Stopped'})
        manager.stop('test-policy')
        manager.isolation.audit.assert_not_called()

    def test_malformed_local_config_and_device_fields_are_errors(self):
        for field, value in [('config', None), ('config', {MANAGED: True}),
                             ('expanded_devices', {'root': {'type': 'disk', 'path': None}})]:
            with self.subTest(field=field, value=value):
                item = copy.deepcopy(self.item)
                item[field] = value
                with self.assertRaises(Error): self.audit(item)

    def test_gpu_permission_refresh_is_conditional_and_preserves_unrelated_fields(self):
        self.project['config']['user.notes'] = 'keep'
        capability = {'available':True, 'backend':'wsl-nvidia',
                      'driver_paths':['/usr/lib/wsl/drivers/nvidia-test']}
        self.policy.check = Mock(side_effect=[self.record, {**self.record,
            'backends':['wsl-nvidia'], 'driver_paths':capability['driver_paths']}])
        self.policy.allow_gpu(capability)
        args = self.policy.api.update.call_args.args
        self.assertEqual(args[2], '"etag"')
        self.assertEqual(args[1]['config']['user.notes'], 'keep')
        self.assertEqual(args[1]['config']['restricted.devices.disk'], 'allow')
        self.assertNotIn('/usr/lib/wsl/drivers,', args[1]['config']['restricted.devices.disk.paths'])

    def test_gpu_permission_refresh_never_repairs_concurrent_policy_drift(self):
        self.policy.check = Mock(return_value=self.record)
        self.project['config']['restricted.containers.privilege'] = 'allow'
        with self.assertRaises(Error):
            self.policy.allow_gpu({'available':True,'backend':'wsl-nvidia',
                                   'driver_paths':['/usr/lib/wsl/drivers/nvidia-test']})
        self.policy.api.update.assert_not_called()

    def test_rejected_import_preserves_data_and_unsets_only_known_marker(self):
        policy = Mock()
        policy.audit.side_effect = Error('unsafe')
        manager = Manager(Mock(project='mas'), isolation=policy)
        manager.absent = Mock()
        manager.imports = Mock()
        manager.imports.restore.return_value = self.item
        manager._run_lxd_until_state = Mock(return_value=self.item)
        manager.delete = Mock()
        with patch('mas.core.Path.is_file', return_value=True), self.assertRaisesRegex(Error,'unsafe'):
            manager.import_container('test-policy','backup.tar.gz')
        calls = manager._run_lxd_until_state.call_args_list
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[2], ['config','unset','local:test-policy',MANAGED])
        manager.delete.assert_not_called()

    def test_quarantine_failure_preserves_primary_import_error(self):
        manager = Manager(Mock(project='mas'), isolation=Mock())
        manager.isolation.audit.side_effect = Error('unsafe import')
        manager.absent = Mock()
        manager.imports = Mock()
        manager.imports.restore.return_value = self.item
        manager._run_lxd_until_state = Mock(side_effect=Error('quarantine failed'))
        manager._cleanup_warning = Mock()
        with patch('mas.core.Path.is_file', return_value=True), self.assertRaisesRegex(Error,'unsafe import'):
            manager.import_container('test-policy','backup.tar.gz')
        manager._cleanup_warning.assert_called_once()

    def test_migration_preserves_safe_inherited_settings_with_native_overrides(self):
        item = copy.deepcopy(self.item)
        item['expanded_config']['limits.memory'] = '2GiB'
        item['expanded_config']['user.notes'] = 'safe inherited value'
        legacy = Mock()
        legacy.require.return_value = item
        legacy.filesystems.deletion_guard.side_effect = contextlib.nullcontext
        manager = Manager(Mock(timeout=300), isolation=Mock())
        manager.legacy = legacy
        manager.absent = Mock()
        manager._run_lxd_until_state = Mock(return_value=self.item)
        self.assertTrue(manager.migrate('test-policy', lambda _:True))
        args = manager._run_lxd_until_state.call_args.args[2]
        self.assertIn('limits.memory=2GiB',args)
        self.assertIn('user.notes=safe inherited value',args)
        self.assertNotIn('security.idmap.isolated=true',args)

    def test_migration_mount_refusal_precedes_confirmation_and_native_move(self):
        manager = Manager(Mock(timeout=300), isolation=Mock())
        manager.legacy = Mock()
        manager.legacy.require.return_value = self.item
        manager.legacy.filesystems.guard_delete.side_effect = Error('mounted')
        manager.absent = Mock()
        manager._run_lxd_until_state = Mock()
        ask = Mock(return_value=True)
        with self.assertRaisesRegex(Error,'mounted'):manager.migrate('test-policy',ask)
        ask.assert_not_called()
        manager._run_lxd_until_state.assert_not_called()

    def test_empty_migration_menu_retains_result_until_return(self):
        view, manager = Mock(), Mock()
        manager.legacy_list.return_value = []
        UI(view,manager).migration()
        view.choose.assert_called_once()
        self.assertEqual(view.choose.call_args.args[1], [(None,'Back')])

    def test_listing_for_safe_stop_remains_available_when_policy_has_drifted(self):
        manager = Manager(Mock(), isolation=Mock())
        manager.isolation.check.side_effect = Error('policy drift')
        manager.lxd.instances.return_value = [self.item]
        self.assertEqual(manager.list(),[self.item])
        manager.isolation.check.assert_not_called()
