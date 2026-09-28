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
        return dict(id='a'*32,target='demo',project='default',path=path,destination=str(self.fs.root/'demo'/path.lstrip('/')),source='fixture',default=True)

    def test_default_unmount_uses_original_recorded_home(self):
        entry=self.entry('/old/home')
        with self.fs.locked() as data:
            data['mounts'].append(entry);self.fs._save(data)
        with patch.object(self.fs,'_home',side_effect=AssertionError('must use record')), patch.object(self.fs,'_remove') as remove:
            self.fs.unmount('demo')
            self.assertEqual(remove.call_args.args[1]['path'],'/old/home')

    def test_mount_table_identity_checks(self):
        entry=self.entry();actual=dict(id=42,kind='fuse.sshfs',source='fixture')
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
            with self.assertRaises(Error): self.fs.guard_transition('demo')
            with self.assertRaises(Error): self.fs.guard_delete('demo')
            remove.assert_not_called()

    def test_failed_attempt_cannot_reclaim_preexisting_tracked_destination(self):
        entry=self.entry()
        with self.fs.locked() as data:
            dest=Path(entry['destination']);self.fs._make(data,dest)
            data['mounts'].append(entry);self.fs._save(data)
            with patch.object(self.fs,'_actual',return_value=[]):self.fs._remove(data,entry)
            self.assertTrue(dest.is_dir())

    def test_existing_lxd_missing_sshfs_authenticates_once(self):
        from mas.install import prepare_system
        original=Path.read_text
        def read(path,*args,**kwargs):
            if str(path)=='/etc/os-release': return 'ID=ubuntu\n'
            if str(path)=='/proc/1/comm': return 'systemd\n'
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',read), patch('mas.install.shutil.which',side_effect=lambda name: None if name=='sshfs' else '/snap/bin/'+name), patch('mas.install.os.geteuid',return_value=1000), patch('mas.install.os.getgid',return_value=1000), patch('mas.install.os.getgroups',return_value=[986]), patch('mas.install.pwd.getpwuid',return_value=SimpleNamespace(pw_name='tester')), patch('mas.install.grp.getgrnam',return_value=SimpleNamespace(gr_gid=986,gr_mem=['tester'])), patch('mas.install.run') as run:
            self.assertFalse(prepare_system())
        self.assertEqual([c.args[0] for c in run.call_args_list],[['sudo','-v'],['apt-get','update'],['apt-get','install','-y','sshfs']])
