"""Host/guest scope separation, honest results and isolated mount regressions."""
import atexit
import contextlib
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.probe_source import source_bytes
from mas.testing import Terminal, python_command

fixture = tempfile.TemporaryDirectory(prefix='mas-host-probe-units-')
atexit.register(fixture.cleanup)
for name in ('guest_security_probe.py', 'host_security_probe.py', 'security-host.sh'):
    (Path(fixture.name) / name).write_bytes(source_bytes(name))
spec = importlib.util.spec_from_file_location('host_probe', Path(fixture.name) / 'host_security_probe.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
probe = host.probe


class HostProbeTests(unittest.TestCase):
    def reference(self):
        return dict(schema=1, boot_id='12345678-1234-1234-1234-123456789abc',
                    namespaces={name: name + ':[123]' for name in probe.NAMESPACES},
                    canaries=[dict(path='/tmp/host-marker', sha256='0'*64)], sockets=[], binfmt=[])

    def test_complete_reference_required_and_invalid_metadata_rejected(self):
        self.assertEqual(host.validate_host_reference(self.reference()), self.reference())
        for field, value in (('boot_id', 'old'), ('canaries', []), ('binfmt', None),
                             ('binfmt', [{'path':'/tmp', 'device':True, 'inode':1}])):
            with self.subTest(field=field), self.assertRaises(ValueError):
                host.validate_host_reference({**self.reference(), field:value})

    def test_host_guard_rejects_guest_before_lxc(self):
        with patch.dict(os.environ, {'container':'lxc'}), self.assertRaisesRegex(ValueError, '宿主'):
            host.host_environment()
        with tempfile.TemporaryDirectory() as directory, patch.object(host, 'lxc_command') as command, \
                patch.object(host, 'host_environment', side_effect=ValueError('guest')), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(host.main(['demo', '--report', str(Path(directory)/'report.json')]), 2)
            command.assert_not_called()

    def test_wsl_systemd_marker_is_a_supported_host(self):
        with patch.dict(os.environ, {'container':'wsl'}), patch.object(host.Path,'exists',return_value=True), \
                patch.object(probe,'read_text',return_value='wsl'):
            host.host_environment()

    def test_only_running_local_containers_selected_and_query_failure_preserved(self):
        command = Mock(return_value=json.dumps([{'name':'demo', 'type':'container', 'status':'Running'},
                                                {'name':'vm', 'type':'virtual-machine', 'status':'Running'},
                                                {'name':'stopped', 'type':'container', 'status':'Stopped'}]))
        self.assertEqual(host.choose_target(command, 'demo'), 'demo')
        for target in ('vm', 'stopped', 'missing', 'remote:demo', 'bad/path', 'bad-'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                host.choose_target(command, target)
        with self.assertRaises(json.JSONDecodeError):
            host.choose_target(Mock(return_value='invalid'), 'demo')
        with patch('builtins.open', side_effect=OSError()), contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'TARGET'):
            host.choose_target(command, None)

    def test_guest_default_has_no_reference_checks_or_binfmt_control(self):
        items = []
        with patch.object(probe, 'bounded_call', side_effect=lambda check, args, timeout: probe.result(check, 'PASS', 'fixture')):
            probe.run_checks('unknown', 1, items.append)
        self.assertFalse(any(item['check'].startswith(('namespace:', 'host-canary:', 'binfmt:')) for item in items))
        self.assertNotIn('process-roots', [item['check'] for item in items])
        self.assertNotIn('/proc/sys/fs/binfmt_misc/register', probe.CONTROLS)

    def test_target_prompt_uses_real_terminal_with_redirected_stdin(self):
        source = '''import json, sys
sys.path.insert(0, FIXTURE)
import host_security_probe as host
sys.stdin = open('/dev/null')
target = host.choose_target(lambda args: json.dumps([
    dict(name='demo',type='container',status='Running')]), None)
print('SELECTED:' + target)
'''.replace('FIXTURE', repr(fixture.name))
        with tempfile.TemporaryDirectory() as directory:
            terminal = Terminal(python_command(source), 10, Path(directory)/'terminal.log')
            try:
                terminal.expect('请输入要挑战的容器名：')
                terminal.send('demo\n')
                terminal.expect('SELECTED:demo')
                terminal.finish()
            finally:
                terminal.close()

    def test_observations_outside_totals_and_incomplete_checks_fail(self):
        report = probe.ChallengeReport('fixture')
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            for status in ('INFO', 'PASS', 'REVIEW', 'SKIP'):
                report.emit(probe.result(status, status, 'fixture'))
            self.assertEqual(report.finish(Path(directory)/'report.json'), 1)
        self.assertEqual(report.data['counts'], {'PASS':1, 'FAIL':2})
        self.assertEqual(len(report.data['observations']), 1)
        self.assertTrue(all(item['status'] in ('PASS','FAIL') for item in report.data['checks']))
        self.assertTrue(all(item.get('failure_kind') == 'verification' for item in report.data['checks'][1:]))

    def test_execution_failure_kind_survives_host_report_replay(self):
        report = probe.ChallengeReport('fixture')
        with contextlib.redirect_stdout(io.StringIO()):
            report.emit(dict(probe.result('fixture','FAIL','failed'), failure_kind='execution'))
        self.assertEqual(report.data['checks'][0]['failure_kind'], 'execution')

    def test_missing_control_passes_only_absence_not_unexecuted_denial(self):
        with patch.object(probe.os, 'open', side_effect=FileNotFoundError(errno.ENOENT, 'missing')):
            item = probe.active_probe('control', '/proc/sysrq-trigger', '/private')
        self.assertEqual(item['status'], 'PASS')
        self.assertIn('入口不存在', item['message'])
        self.assertEqual(item['evidence']['errno'], errno.ENOENT)

    def test_mount_denial_is_a_completed_assertion(self):
        libc = Mock(); libc.unshare.return_value = -1
        with patch.object(host.ctypes, 'CDLL', return_value=libc), patch.object(host.ctypes, 'get_errno', return_value=errno.EPERM):
            item = host.binfmt_mount_probe(self.reference())
        self.assertEqual(item['status'], 'PASS')
        self.assertEqual(item['evidence']['step'], 'unshare')
        libc.mount.assert_not_called()

    def test_private_mount_detaches_and_unknown_failure_is_not_denial(self):
        libc = Mock(); libc.unshare.return_value = libc.mount.return_value = libc.umount2.return_value = 0
        before = set(Path(fixture.name).iterdir())
        with patch.object(host.ctypes, 'CDLL', return_value=libc):
            item = host.binfmt_mount_probe(self.reference())
        self.assertEqual(item['status'], 'PASS')
        self.assertEqual(set(Path(fixture.name).iterdir()), before)
        self.assertEqual(libc.mount.call_args_list[0].args[3], (1<<14)|(1<<18))
        libc.umount2.assert_called_once()
        with patch.object(host.ctypes, 'CDLL', return_value=libc), \
                patch.object(probe, 'namespace_ids', side_effect=PermissionError(errno.EACCES,'identity denied')):
            item = host.binfmt_mount_probe(self.reference())
        self.assertEqual(item['status'], 'ERROR')
        self.assertEqual(item['evidence']['step'], 'identity')
        libc.umount2.return_value = -1
        with patch.object(host.ctypes, 'CDLL', return_value=libc), patch.object(host.ctypes,'get_errno',return_value=errno.EPERM):
            item = host.binfmt_mount_probe(self.reference())
        self.assertEqual(item['status'], 'ERROR')
        self.assertEqual(item['evidence']['step'], 'unmount')
        libc.unshare.return_value = -1
        with patch.object(host.ctypes, 'CDLL', return_value=libc), patch.object(host.ctypes, 'get_errno', return_value=errno.EIO):
            self.assertEqual(host.binfmt_mount_probe(self.reference())['status'], 'ERROR')

    def test_binfmt_inventory_uses_all_mountpoints_and_does_not_write(self):
        with patch.object(probe, 'parse_mounts', return_value=[]), patch.object(probe, 'read_text', return_value='fixture'):
            self.assertEqual(host.binfmt_existing(self.reference())[0]['status'], 'PASS')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'register').write_text('unchanged')
            mount = dict(path=directory, filesystem='binfmt_misc')
            reference = self.reference(); reference['binfmt'] = [dict(path='/host', device=root.stat().st_dev, inode=root.stat().st_ino)]
            with patch.object(probe, 'parse_mounts', return_value=[mount]), patch.object(probe, 'read_text', return_value='fixture'):
                self.assertEqual(host.binfmt_existing(reference)[0]['status'], 'FAIL')
                reference['binfmt'] = []
                self.assertEqual(host.binfmt_existing(reference)[0]['status'], 'REVIEW')
            self.assertEqual((root/'register').read_text(), 'unchanged')

    def test_mount_timeout_and_malformed_child_are_not_passes(self):
        with patch.object(host.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['fixture'], 1)):
            self.assertEqual(host.bounded_mount(self.reference(), 1)['status'], 'ERROR')
        for stdout in ('null', '{}', 'invalid'):
            with patch.object(host.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout, '')):
                self.assertEqual(host.bounded_mount(self.reference(), 1)['status'], 'ERROR')

    def run_fixture(self, primary=False, pull_failure=False, cleanup_failure=False, stale=False):
        calls = []
        reference = self.reference()
        ids = ['namespace:'+name for name in probe.NAMESPACES] + ['process-roots','host-canary:0','binfmt:existing','binfmt:temporary-mount']
        checks = [probe.result(name, 'FAIL' if primary and i==0 else 'PASS', 'fixture') for i,name in enumerate(ids)]
        data = dict(schema=2, counts={'PASS':len(checks)-(1 if primary else 0),'FAIL':1 if primary else 0},
                    exit_code=1 if primary else 0, checks=checks)
        def command(args):
            calls.append(args)
            if args[0] == 'exec' and args[3:5] == ['python3','-c']:
                return '/tmp/mas-host-challenge-fixture'
            if args[0] == 'exec' and args[3] == 'python3':
                if primary:
                    raise RuntimeError('original probe failure')
                return 'guest-output'
            if args[:2] == ['file','pull']:
                if pull_failure:
                    raise RuntimeError('retrieval failure')
                Path(args[-1]).write_text(json.dumps(data))
            if 'rm' in args and cleanup_failure:
                raise RuntimeError('cleanup failure')
            return ''
        report = probe.ChallengeReport('fixture')
        with patch.object(host,'make_reference',return_value=reference), patch.object(host,'binfmt_snapshot',return_value=[]), \
                patch.object(host,'boot_id',return_value='stale' if stale else reference['boot_id']), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if stale:
                with self.assertRaisesRegex(ValueError,'历史'):
                    host.run_target(command,'demo',report)
            else:
                host.run_target(command,'demo',report)
        return report, calls

    def test_public_orchestration_uses_both_scripts_only_copies_marker_metadata_and_cleans(self):
        report, calls = self.run_fixture()
        pushed = [Path(args[2]).name for args in calls if args[:2] == ['file','push']]
        self.assertEqual(pushed, ['guest_security_probe.py','host_security_probe.py','host-reference.json'])
        self.assertTrue(any('rm' in args for args in calls))
        self.assertEqual(report.data['guest_stdout'], 'guest-output')
        self.assertTrue(all(item['status']=='PASS' for item in report.data['checks']))

    def test_probe_report_recovered_and_primary_and_cleanup_failures_preserved(self):
        report, calls = self.run_fixture(primary=True, pull_failure=True, cleanup_failure=True)
        self.assertEqual(report.data['native_failure'], 'original probe failure')
        self.assertTrue(any(item['check']=='host-report' for item in report.data['checks']))
        self.assertTrue(any(item['check']=='host-cleanup' for item in report.data['checks']))
        self.assertLess(next(i for i,args in enumerate(calls) if args[:2]==['file','pull']),next(i for i,args in enumerate(calls) if 'rm' in args))

    def test_stale_boot_reference_prevents_guest_commands(self):
        report, calls = self.run_fixture(stale=True)
        self.assertEqual(calls, [])

    def test_incomplete_or_false_success_report_is_rejected(self):
        for data in (None, {}, {'schema':2,'exit_code':0,'counts':{'PASS':1,'FAIL':0},
                               'checks':[probe.result('namespace:user','PASS','fixture')]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                host.validate_guest_report(data,self.reference())

    def test_host_entry_downloaded_help_is_independent_and_temporary_files_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); binaries=root/'bin'; binaries.mkdir(); temporary=root/'temp'; temporary.mkdir()
            curl=binaries/'curl'
            curl.write_text('#!' + sys.executable + '\nimport pathlib,shutil,sys\na=sys.argv\nshutil.copyfile(pathlib.Path('+repr(fixture.name)+')/a[2].split("/")[-1],a[a.index("-o")+1])\n')
            curl.chmod(0o700)
            process=subprocess.run(['bash',str(Path(fixture.name)/'security-host.sh'),'--help'],cwd=root,
                env=dict(os.environ, PATH=str(binaries)+os.pathsep+os.environ['PATH'],TMPDIR=str(temporary)),capture_output=True,text=True,timeout=10)
            self.assertEqual(process.returncode,0,process.stderr)
            self.assertIn('--project',process.stdout)
            self.assertNotIn('--_guest-reference',process.stdout)
            self.assertEqual(list(temporary.iterdir()),[])


if __name__ == '__main__':
    unittest.main()
