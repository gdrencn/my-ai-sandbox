"""Persistent socket permissions without daemon restarts or broad privilege."""
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from mas import socket_access as access
from mas.core import Error


class SocketAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dropin = self.root/'socket.d'/'mas.conf'
        self.socket = self.root/'unix.socket'
        self.group = SimpleNamespace(gr_name='custom-lxd', gr_gid=1234)
        self.values = dict(LoadState='loaded', SocketGroup='custom-lxd', SocketMode='0660', Listen=str(self.socket)+' (Stream)')

    def test_generated_group_is_data_and_defaults(self):
        p=self.root/'config'
        with patch('mas.socket_access.grp.getgrnam', return_value=self.group) as lookup:
            access.daemon_group(p);lookup.assert_called_with('lxd')
            p.write_text("daemon_group='custom-lxd'\n")
            access.daemon_group(p);lookup.assert_called_with('custom-lxd')
            p.write_text('daemon_group=$(touch /tmp/unwanted)\n')
            with self.assertRaises(Error):access.daemon_group(p)

    def test_custom_group_persists_and_repairs_without_restart(self):
        run=Mock()
        infos=[SimpleNamespace(st_gid=0),SimpleNamespace(st_gid=0),SimpleNamespace(st_gid=1234)]
        with patch.object(access,'properties',return_value=self.values), patch.object(access,'socket_info',side_effect=infos), patch.object(access.os,'chown') as chown, patch.object(access.time,'sleep'):
            access.configure(run,group=self.group,dropin=self.dropin,socket=self.socket)
        self.assertEqual(self.dropin.read_text(),access.content('custom-lxd'))
        self.assertEqual(self.dropin.stat().st_mode & 0o777,0o644)
        chown.assert_called_once_with(self.socket,-1,1234,follow_symlinks=False)
        self.assertEqual([c.args[0] for c in run.call_args_list],[['systemctl','daemon-reload'],['systemctl','start',access.UNIT]])

    def test_ready_checks_effective_and_observed_state(self):
        self.dropin.parent.mkdir();self.dropin.write_text(access.content('custom-lxd'))
        with patch.object(access,'socket_info',return_value=SimpleNamespace(st_gid=1234)):
            self.assertTrue(access.ready(self.group,self.values,self.dropin,self.socket))
            self.assertFalse(access.ready(self.group,{**self.values,'SocketGroup':''},self.dropin,self.socket))
        with patch.object(access,'socket_info',return_value=SimpleNamespace(st_gid=0)):
            self.assertFalse(access.ready(self.group,self.values,self.dropin,self.socket))

    def test_ready_installer_does_not_request_privilege(self):
        from mas.install import prepare_socket_access
        with patch.object(access,'daemon_group',return_value=self.group), patch.object(access,'properties'), patch.object(access,'ready',return_value=True), patch('mas.install.run') as run:
            self.assertIs(prepare_socket_access(),self.group)
        run.assert_not_called()

    def test_unready_installer_requires_successful_postcheck(self):
        from mas.install import prepare_socket_access
        with patch.object(access,'daemon_group',return_value=self.group), patch.object(access,'properties'), patch.object(access,'ready',side_effect=[False,False]), patch('mas.install.run') as run, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(Error):prepare_socket_access()
        self.assertTrue(run.call_args.kwargs['privileged'])

    def test_foreign_and_symlink_configuration_preserved(self):
        self.dropin.parent.mkdir();self.dropin.write_text('[Socket]\nSocketGroup=other\n')
        with self.assertRaises(Error):access.check_paths(self.dropin)
        self.assertIn('other',self.dropin.read_text())
        self.dropin.unlink();target=self.root/'owned';target.write_text(access.content('custom-lxd'));self.dropin.symlink_to(target)
        with self.assertRaises(Error):access.check_paths(self.dropin)
        self.assertEqual(target.read_text(),access.content('custom-lxd'))

    def test_conflicting_unit_or_owner_never_mutates(self):
        for changes in ({'Listen':'/other (Stream)'},{'SocketMode':'0666'},{'LoadState':'not-found'}):
            with self.assertRaises(Error):access.check_unit({**self.values,**changes},self.socket)
        with patch.object(access,'properties',return_value=self.values), patch.object(access,'socket_info',return_value=SimpleNamespace(st_gid=9999)):
            with self.assertRaises(Error):access.configure(Mock(),group=self.group,dropin=self.dropin,socket=self.socket)
        self.assertFalse(self.dropin.exists())
        self.socket.write_text('not a socket')
        with self.assertRaises(Error):access.socket_info(self.socket)

    def test_effective_override_failure_does_not_touch_socket(self):
        with patch.object(access,'properties',side_effect=[self.values,{**self.values,'SocketGroup':'other'}]), patch.object(access,'socket_info',return_value=SimpleNamespace(st_gid=0)), patch.object(access.os,'chown') as chown:
            with self.assertRaises(Error):access.configure(Mock(),group=self.group,dropin=self.dropin,socket=self.socket)
        chown.assert_not_called()

    def test_unavailable_socket_times_out_without_success(self):
        with patch.object(access,'properties',return_value=self.values), patch.object(access,'socket_info',return_value=None), patch.object(access.time,'monotonic',side_effect=[0,601]):
            with self.assertRaises(Error):access.configure(Mock(),group=self.group,dropin=self.dropin,socket=self.socket)

    def test_failed_user_access_prevents_install_success(self):
        from mas.install import finish
        with patch('mas.install.initialize',side_effect=Error('permission denied')), patch('mas.install.install_file') as publish, patch('mas.install.configure_path') as path:
            with self.assertRaises(Error):finish(Path('/product'))
        publish.assert_not_called();path.assert_not_called()
