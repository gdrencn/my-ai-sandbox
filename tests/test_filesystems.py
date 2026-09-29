"""Mount ownership/path safeguards and recovery without changing container modes."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mas.core import Error
from mas.filesystems import Filesystems, normalized, overlaps, process_identity


class FilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.manager = Mock(lxd=SimpleNamespace(project='default', timeout=300, command=Mock()))
        self.manager.emit = self.manager.report
        self.fs = Filesystems(self.manager, self.base/'root', self.base/'state')

    def test_path_identity_and_overlap(self):
        self.assertEqual(normalized('//home/./sandbox/'), '/home/sandbox')
        for value in ('relative', '~', '/a/../b', '/a\n', '/a\0'):
            with self.assertRaises(Error): normalized(value)
        for a,b in (('/', '/home'), ('/home','/home/u'), ('/home','/home')):
            self.assertTrue(overlaps(a,b))
        self.assertFalse(overlaps('/home','/homepage'))

    def test_existing_leaf_empty_directory_file_or_symlink_preserved(self):
        with self.fs.locked() as data:
            root=self.fs.root
            root.mkdir();data['directories'][str(root)]=self.fs._identity(root)
            for kind in ('dir','file','symlink'):
                path=root/kind
                if kind=='dir': path.mkdir()
                elif kind=='file': path.write_text('preserve')
                else: path.symlink_to(root/'missing')
                with self.assertRaises(Error): self.fs._make(data,path)
                self.assertTrue(os.path.lexists(path))

    def test_untracked_parent_and_parent_symlink_refused(self):
        with self.fs.locked() as data:
            self.fs.root.mkdir()
            with self.assertRaises(Error): self.fs._make(data,self.fs.root/'demo'/'home')
            self.fs.root.rmdir();self.fs.root.symlink_to(self.base,target_is_directory=True)
            with self.assertRaises(Error): self.fs._make(data,self.fs.root/'demo'/'home')
        self.assertFalse((self.base/'demo').exists())

    def test_cleanup_preserves_other_mount_parents_and_nonempty_leaf(self):
        with self.fs.locked() as data:
            first=self.fs.root/'demo'/'a';second=self.fs.root/'demo'/'b'
            self.fs._make(data,first);self.fs._make(data,second)
            self.fs._reclaim(data,first)
            self.assertTrue(second.is_dir())
            (second/'user-file').write_text('keep')
            with self.assertRaises(Error): self.fs._reclaim(data,second)
            self.assertEqual((second/'user-file').read_text(),'keep')
            (second/'user-file').unlink();self.fs._reclaim(data,second)
            self.assertFalse(self.fs.root.exists())

    def test_replaced_mountpoint_never_reclaimed(self):
        with self.fs.locked() as data:
            path=self.fs.root/'demo';self.fs._make(data,path)
            path.rename(self.fs.root/'old');path.mkdir()
            with self.assertRaises(Error): self.fs._reclaim(data,path)
            self.assertTrue(path.exists())

    def test_corrupt_record_not_replaced(self):
        self.fs._private();path=self.fs.state/'mounts.json';path.write_text('{}')
        with self.assertRaises(Error):
            with self.fs.locked(): pass
        self.assertEqual(path.read_text(),'{}')

    def test_precise_unmount_refuses_child_without_cleanup(self):
        with self.fs.locked() as data:
            data['mounts'].append(self.entry('/'))
            self.fs._save(data)
        with patch.object(self.fs,'_remove') as remove:
            with self.assertRaises(Error): self.fs.unmount('demo','/var/log')
            remove.assert_not_called()

    def entry(self,path='/home/sandbox'):
        return dict(id='a'*32,target='demo',project='default',path=path,destination=str(self.fs.root/'demo'/path.lstrip('/')),source='mas-'+'a'*32+'@127.0.0.1:'+path,default=True)

    def test_default_unmount_uses_original_recorded_home(self):
        entry=self.entry('/old/home')
        with self.fs.locked() as data:
            data['mounts'].append(entry);self.fs._save(data)
        with patch.object(self.fs,'_home',side_effect=AssertionError('must use record')), patch.object(self.fs,'_remove') as remove:
            self.fs.unmount('demo')
            self.assertEqual(remove.call_args.args[1]['path'],'/old/home')

    def test_mount_table_identity_checks(self):
        entry=self.entry();actual=dict(id=42,kind='fuse.sshfs',source=entry['source'])
        self.assertTrue(self.fs._matching(entry,[actual]))
        self.assertFalse(self.fs._matching(entry,[actual,actual]))
        self.assertFalse(self.fs._matching(entry,[{**actual,'source':'foreign'}]))
        entry['mount_id']=43
        self.assertFalse(self.fs._matching(entry,[actual]))

    def test_process_identity_prevents_pid_reuse_signal(self):
        identity=process_identity(os.getpid())
        self.assertEqual(identity['pid'],os.getpid())
        identity['start']='not-the-same-process'
        with patch('mas.filesystems.os.kill') as kill:
            self.fs._terminate(identity)
            kill.assert_not_called()

    def test_missing_default_user_and_symlink_directory_are_rejected(self):
        self.manager.lxd.command.return_value='root:x:0:0:root:/root:/bin/bash\n'
        with self.assertRaises(Error):self.fs._home('demo')
        self.manager.lxd.command.return_value='/somewhere'
        with self.assertRaises(Error):self.fs._directory('demo','/link')

    def test_unmount_conflict_retains_records_and_does_not_signal(self):
        entry=self.entry()
        with self.fs.locked() as data:
            data['mounts'].append(entry);self.fs._save(data)
            with patch.object(self.fs,'_actual',return_value=[dict(kind='tmpfs',source='foreign',id=2)]), patch.object(self.fs,'_terminate') as terminate:
                with self.assertRaises(Error):self.fs._remove(data,entry)
                terminate.assert_not_called()
                self.assertIn(entry,data['mounts'])

    def test_state_transition_guard_leaves_mounts_untouched(self):
        with patch.object(self.fs, 'list', return_value=[dict(path='/')]), patch.object(self.fs, '_remove') as remove:
            with self.assertRaises(Error): self.fs.require_no_mounts('demo')
            with self.assertRaises(Error): self.fs.guard_delete('demo')
            remove.assert_not_called()

    def test_failed_attempt_cannot_reclaim_preexisting_tracked_destination(self):
        entry=self.entry()
        with self.fs.locked() as data:
            dest=Path(entry['destination']);self.fs._make(data,dest)
            data['mounts'].append(entry);self.fs._save(data)
            with patch.object(self.fs,'_actual',return_value=[]):self.fs._remove(data,entry)
            self.assertTrue(dest.is_dir())

    def test_existing_lxd_uses_shared_dependency_preparation_without_preauth(self):
        from mas.install import prepare_system
        original=Path.read_text
        def read(path,*args,**kwargs):
            if str(path)=='/etc/os-release': return 'ID=ubuntu\n'
            if str(path)=='/proc/1/comm': return 'systemd\n'
            return original(path,*args,**kwargs)
        with patch('mas.install.prepare_dependencies') as dependencies, patch('mas.install.prepare_fuse_access'), patch.object(Path,'read_text',read), patch('mas.install.shutil.which',side_effect=lambda name: None if name=='sshfs' else '/snap/bin/'+name), patch('mas.install.os.geteuid',return_value=1000), patch('mas.install.os.getgid',return_value=1000), patch('mas.install.os.getgroups',return_value=[986]), patch('mas.install.pwd.getpwuid',return_value=SimpleNamespace(pw_name='tester')), patch('mas.install.grp.getgrnam',return_value=SimpleNamespace(gr_gid=986,gr_mem=['tester'])), patch('mas.install.run') as run:
            self.assertFalse(prepare_system())
        dependencies.assert_called_once_with()
        run.assert_not_called()

    def test_schema_damage_preserves_original_file(self):
        import copy
        self.fs._private()
        base = dict(version=1, directories={}, mounts=[self.entry()])
        changes = [lambda d: d['mounts'][0].update(listener={'pid': os.getpid()}),
                   lambda d: d['mounts'][0].update(default='yes'),
                   lambda d: d['mounts'][0].update(source='foreign'),
                   lambda d: d['mounts'][0].update(created=['/tmp/foreign']),
                   lambda d: d['directories'].update({'/tmp/foreign': [1, 2]}),
                   lambda d: d['mounts'].append(d['mounts'][0].copy())]
        for change in changes:
            data=copy.deepcopy(base);change(data)
            raw=json.dumps(data);(self.fs.state/'mounts.json').write_text(raw)
            with self.assertRaises(Error): self.fs.list('demo')
            self.assertEqual((self.fs.state/'mounts.json').read_text(),raw)

    def test_recovery_never_queries_replacement_container(self):
        with self.fs.locked() as data:
            data['mounts'].append(self.entry());self.fs._save(data)
        self.manager.find.side_effect=AssertionError('replacement must not be accessed')
        self.manager.require.side_effect=AssertionError('replacement must not be accessed')
        with patch.object(self.fs,'_actual',return_value=[]):
            self.assertEqual(self.fs.list('demo')[0]['status'],'residual')
            self.fs.unmount('demo')
        self.assertEqual(self.fs.list('demo'),[])

    def test_directory_identity_uses_filesystem_not_boot_device_number(self):
        path=self.base/'identity';path.mkdir()
        identity=self.fs._identity(path)
        with patch.object(Path,'lstat',return_value=SimpleNamespace(st_mode=0o40700,st_uid=os.getuid(),st_ino=identity['inode'],st_dev=99999)):
            self.assertTrue(self.fs._same_directory(path,identity))
            self.assertFalse(self.fs._same_directory(path,[1,identity['inode']]))
        self.assertFalse(self.fs._same_directory(path,{**identity,'fsid':identity['fsid']+1}))

    def test_transition_holds_real_lock_and_refuses_records(self):
        import fcntl
        with self.fs.deletion_guard('demo'):
            with (self.fs.state/'lock').open('rb') as other:
                with self.assertRaises(BlockingIOError):fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with self.fs.locked() as data:
            data['mounts'].append(self.entry());self.fs._save(data)
        with self.assertRaises(Error):
            with self.fs.deletion_guard('demo'):self.fail('must refuse')

    def test_mount_rechecks_owner_after_lock(self):
        self.manager.require.side_effect=[{},Error('replaced')]
        with patch('mas.filesystems.fuse_access_ready',return_value=True), patch('mas.filesystems.shutil.which',return_value='/usr/bin/native'),patch.object(self.fs,'_directory'):
            with self.assertRaisesRegex(Error,'replaced'):self.fs.mount('demo','/var/log')
        with self.fs.locked() as data:self.assertEqual(data['mounts'],[])

    def test_unmount_timeout_and_cleanup_failure_never_report_success(self):
        import subprocess
        entry=self.entry()
        with self.fs.locked() as data:
            data['mounts'].append(entry);self.fs._save(data)
            actual=[dict(kind='fuse.sshfs',source=entry['source'],id=42)]
            with patch.object(self.fs,'_actual',return_value=actual),patch('mas.filesystems.subprocess.run',side_effect=subprocess.TimeoutExpired('fusermount3',300)):
                with self.assertRaises(Error):self.fs._remove(data,entry)
            self.assertIn(entry,data['mounts'])
            self.assertEqual(self.manager.report.call_args.args[0]['status'],'error')
            entry['prepared']=True
            with patch.object(self.fs,'_actual',return_value=[]),patch.object(self.fs,'_reclaim',side_effect=Error('nonempty')):
                with self.assertRaises(Error):self.fs._remove(data,entry)
            self.assertEqual(self.manager.report.call_args.args[0]['status'],'error')

    def test_valid_token_for_unrelated_process_is_not_authority(self):
        entry=self.entry();entry['listener']=process_identity(os.getpid())
        with patch('mas.filesystems.os.kill') as kill:
            with self.assertRaises(Error):self.fs._helpers(entry,'listener')
            kill.assert_not_called()

    def test_atomic_installer_preserves_product_on_copy_failure(self):
        from mas.install import install_file
        source=self.base/'source';source.write_text('new')
        target=self.base/'mas';target.write_text('old')
        with patch('mas.install.shutil.copyfileobj',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):install_file(source,target)
        self.assertEqual(target.read_text(),'old')
        self.assertEqual(sorted(p.name for p in self.base.iterdir()),['mas','source'])
        install_file(source,target)
        self.assertEqual(target.read_text(),'new')
        self.assertEqual(target.stat().st_mode & 0o777,0o755)

    def test_concurrent_installers_publish_complete_files(self):
        from concurrent.futures import ThreadPoolExecutor
        from mas.install import install_file
        sources=[self.base/'a',self.base/'b']
        contents=[b'a'*200000,b'b'*200000]
        for source,content in zip(sources,contents):source.write_bytes(content)
        target=self.base/'mas'
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda source: install_file(source,target),sources))
        self.assertIn(target.read_bytes(),contents)
        self.assertFalse(list(self.base.glob('.mas.*')))
