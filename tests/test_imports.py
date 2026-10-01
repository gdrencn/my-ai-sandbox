"""Ownership and failure boundaries of native backup staging."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

from mas.core import Error, MANAGED
from mas.imports import Imports, KEY
from mas.isolation import BASE_CONFIG, PROFILE_KEY


class ImportTests(unittest.TestCase):
    def setUp(self):
        language = patch('mas.config.language', return_value='en_us')
        language.start(); self.addCleanup(language.stop)
        self.manager = Mock()
        self.manager.lxd.project = 'mas'
        self.manager.lxd.timeout = 300
        self.record = dict(version=1, pool='default', network='lxdbr0', backends=[], driver_paths=[])
        self.manager.isolation.check.return_value = self.record
        self.item = dict(name='test-import', type='container', status='Stopped',
                         config={MANAGED:'true','boot.autostart':'true'}, devices={})
        self.stage = Mock()
        self.stage.isolation.created = False
        self.stage.isolation.resource.return_value = ({'config':{},'description':'stage'}, '"etag"', '/stage')
        self.stage._run_lxd_until_state.return_value = copy.deepcopy(self.item)
        self.stage.lxd.configuration.read.return_value = (copy.deepcopy(self.item), '"instance"')
        self.stage.find.return_value = copy.deepcopy(self.item)
        self.manager._run_lxd_until_state.return_value = copy.deepcopy(self.item)
        def create(*args, **kwargs): self.stage.isolation.created = True
        self.stage.isolation.create.side_effect = create
        self.patch = patch('mas.imports.Manager', return_value=self.stage)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.cleanup = patch.object(Imports, 'cleanup')
        self.reclaim = self.cleanup.start(); self.addCleanup(self.cleanup.stop)
        self.imports = Imports(self.manager)

    def restore(self): return self.imports.restore('test-import', '/backup.tar.gz')

    def test_native_transfer_audits_before_copy_and_never_starts_guest(self):
        self.restore()
        args, kw = self.stage.isolation.create.call_args
        owner = json.loads(kw['project_extra'][KEY])
        self.assertEqual(owner['destination'], 'mas')
        self.assertEqual(owner['target'], 'test-import')
        self.assertEqual(kw['profile_extra'], {'boot.autostart':'false'})
        published = self.stage.lxd.configuration.write.call_args.args[1]['config']
        self.assertNotIn(MANAGED, published)
        self.assertEqual(published['boot.autostart'], 'false')
        self.assertEqual(self.manager.isolation.audit.call_count, 2)
        copy_args = self.manager._run_lxd_until_state.call_args.args[2]
        self.assertIn('boot.autostart=true', copy_args)
        self.assertIn('--target-project', copy_args)
        self.assertEqual(self.manager._run_lxd_until_state.call_args.kwargs['client'], self.stage.lxd)
        self.assertEqual(self.stage._run_lxd_until_state.call_count, 1)
        self.assertEqual(self.stage._run_lxd_until_state.call_args.args[0], 'import')
        self.stage.enter.assert_not_called(); self.stage.start.assert_not_called()
        self.reclaim.assert_called_once_with(self.manager, owner)

    def test_unsafe_backup_retained_without_destination_copy(self):
        self.manager.isolation.audit.side_effect = Error('unsafe backup')
        with self.assertRaisesRegex(Error, 'unsafe backup'): self.restore()
        self.manager._run_lxd_until_state.assert_not_called()
        self.reclaim.assert_not_called()
        self.assertEqual(self.manager.emit.call_args.args[0]['phase'], 'staging-created')

    def test_failed_native_import_reclaims_only_empty_stage(self):
        self.stage._run_lxd_until_state.side_effect = Error('bad archive')
        for empty in (True, False):
            with self.subTest(empty=empty):
                self.reclaim.reset_mock()
                self.stage.find.return_value = None if empty else self.item
                with self.assertRaisesRegex(Error,'bad archive'): self.restore()
                self.assertEqual(self.reclaim.call_count, int(empty))
        self.manager._run_lxd_until_state.assert_not_called()

    def test_creation_failure_keeps_owner_for_cleanup_and_preserves_primary_error(self):
        def failure(*args, **kwargs):
            self.stage.isolation.created = True
            raise Error('profile setup failed')
        self.stage.isolation.create.side_effect = failure
        self.stage.find.return_value = None
        self.reclaim.side_effect = Error('cleanup failed')
        with self.assertRaisesRegex(Error,'profile setup failed'): self.restore()
        self.manager._cleanup_warning.assert_called_once()
        self.stage._run_lxd_until_state.assert_not_called()
        self.assertEqual(self.manager.emit.call_args.args[0]['phase'],'staging-created')

    def test_cleanup_query_failure_cannot_replace_copy_error(self):
        self.manager._run_lxd_until_state.side_effect = Error('copy failed')
        self.stage.find.side_effect = [self.item, Error('query failed')]
        with self.assertRaisesRegex(Error,'copy failed'): self.restore()
        self.manager._cleanup_warning.assert_called_once()

    def test_successful_copy_cleanup_failure_prevents_function_success(self):
        self.reclaim.side_effect = Error('cleanup failed')
        with self.assertRaisesRegex(Error,'cleanup failed') as caught: self.restore()
        owner = self.manager.emit.call_args.args[0]['owner']
        self.assertIn(owner['project'], str(caught.exception))
        self.manager._completed.assert_not_called()

    def test_profile_conflict_is_checked_before_deleting_staged_data(self):
        self.cleanup.stop()
        owner=dict(version=1,id='a'*32,project='mas-import-'+'a'*32,
                   target='test-import',destination='mas')
        project={'config':{KEY:json.dumps(owner,sort_keys=True)}}
        profile={'config':{'user.foreign':'keep'}, 'devices':{}}
        self.stage.isolation.resource.side_effect=[(project,'"project"','/stage'),(profile,'"profile"','/profile')]
        self.stage.isolation.record.return_value=self.record
        self.stage.lxd.instances.return_value=[dict(name='test-import',status='Stopped')]
        with patch('mas.imports.Isolation.list_objects',return_value=[dict(name='mas')]),self.assertRaises(Error):
            Imports.cleanup(self.manager,owner)
        self.stage._run_lxd_until_state.assert_not_called()
        self.stage.lxd.configuration.request.assert_not_called()

    def test_interruption_records_owner_and_preserves_imported_data(self):
        self.stage._run_lxd_until_state.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): self.restore()
        self.reclaim.assert_not_called()
        self.assertEqual(self.manager.emit.call_args.args[0]['phase'],'staging-created')

    def test_owner_mismatch_prevents_any_cleanup(self):
        self.cleanup.stop()
        for owner in (None, {}, dict(version=1,id='a'*32,project='mas-import-'+'a'*32,
                                    target='test-import',destination='foreign')):
            with self.subTest(owner=owner), self.assertRaises(Error):
                Imports.cleanup(self.manager, owner)
        self.stage._run_lxd_until_state.assert_not_called()

    def test_foreign_project_marker_or_occupant_prevents_deletion(self):
        self.cleanup.stop()
        owner=dict(version=1,id='a'*32,project='mas-import-'+'a'*32,
                   target='test-import',destination='mas')
        for marker, items in (('foreign',[]), (json.dumps(owner,sort_keys=True),[dict(name='other',status='Stopped')]),
                              (json.dumps(owner,sort_keys=True),[dict(name='test-import',status='Running')])):
            with self.subTest(marker=marker,items=items):
                self.stage.isolation.resource.return_value = ({'config':{KEY:marker}}, '"etag"','/stage')
                self.stage.lxd.instances.return_value = items
                with self.assertRaises(Error): Imports.cleanup(self.manager,owner)
        self.stage._run_lxd_until_state.assert_not_called()
        self.stage.lxd.configuration.request.assert_not_called()
