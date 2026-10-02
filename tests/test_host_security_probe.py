"""Host/guest scope separation, honest results and isolated mount regressions."""
import atexit
import contextlib
import copy
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.probe_source import source_bytes
from mas.testing import Terminal, python_command

fixture = tempfile.TemporaryDirectory(prefix='mas-host-probe-units-')
atexit.register(fixture.cleanup)
for name in ('guest_security_probe.py', 'host_security_probe.py'):
    (Path(fixture.name) / name).write_bytes(source_bytes(name))
spec = importlib.util.spec_from_file_location('host_probe', Path(fixture.name) / 'host_security_probe.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
probe = host.probe


class HostProbeTests(unittest.TestCase):
    def test_coordinator_loads_exact_sibling_source_without_cached_module_or_path_mutation(self):
        original_path = sys.path[:]
        shadow = Mock()
        with patch.dict(sys.modules,{'guest_security_probe':shadow}):
            spec = importlib.util.spec_from_file_location('isolated_host_probe',Path(host.__file__))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.assertIsNot(module.probe,shadow)
        self.assertEqual(Path(module.probe.__file__),Path(host.__file__).with_name('guest_security_probe.py'))
        self.assertEqual(sys.path,original_path)

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

    def test_guest_default_has_no_reference_checks_or_binfmt_control(self):
        items = []
        with patch.object(probe, 'bounded_call', side_effect=lambda check, args, timeout: probe.result(check, 'PASS', 'fixture')):
            probe.run_checks('unknown', 1, items.append)
        self.assertFalse(any(item['check'].startswith(('namespace:', 'host-canary:', 'binfmt:')) for item in items))
        self.assertNotIn('process-roots', [item['check'] for item in items])
        self.assertNotIn('/proc/sys/fs/binfmt_misc/register', probe.CONTROLS)

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

    def complete_report(self, primary=False):
        ids = (['namespace:'+name for name in probe.NAMESPACES]
               + ['process-roots','host-canary:0','binfmt:existing','binfmt:temporary-mount']
               + ['uid-map','gid-map','seccomp','basic-interfaces','device-inventory','mount-sources','windows-interop','gpu-expectation']
               + ['management-socket:'+path for path in probe.SOCKETS]
               + ['device:'+name for name in probe.DEVICES]
               + ['control:'+path for path in probe.CONTROLS]
               + ['read-endpoint:'+path for path in probe.READ_ENDPOINTS]
               + ['devlxd-api:'+path for path in probe.DEVLXD_ENDPOINTS])
        checks = [probe.result(name, 'FAIL' if primary and i==0 else 'PASS', 'fixture') for i,name in enumerate(ids)]
        return dict(schema=2, gpu_expected='off', observations=[],
                    counts={'PASS':len(checks)-(1 if primary else 0),'FAIL':1 if primary else 0},
                    exit_code=1 if primary else 0, checks=checks)

    def run_fixture(self, primary=False, pull_failure=False, cleanup_failure=False, stale=False, interrupted=False):
        calls = []
        reference = self.reference()
        data = self.complete_report(primary)
        def command(args):
            calls.append(args)
            if args[0] == 'exec' and args[3:5] == ['python3','-c']:
                return '/tmp/mas-host-challenge-fixture'
            if args[0] == 'exec' and args[3] == 'python3':
                if interrupted:
                    raise KeyboardInterrupt('original interruption')
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
        output, diagnostics = [], []
        report = probe.ChallengeReport('fixture', write=output.append, diagnostic=diagnostics.append)
        with patch.object(host,'make_reference',return_value=reference), patch.object(host,'binfmt_snapshot',return_value=[]), \
                patch.object(host,'boot_id',return_value='stale' if stale else reference['boot_id']), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if stale:
                with self.assertRaisesRegex(ValueError,'历史'):
                    host.run_target(command,'demo',report,gpu='off')
            else:
                error = host.run_target(command,'demo',report,gpu='off')
                report.data['fixture_primary_type'] = type(error).__name__ if error else None
        return report, calls

    def test_complete_orchestration_uses_both_scripts_only_copies_marker_metadata_and_cleans(self):
        report, calls = self.run_fixture()
        pushed = [Path(args[2]).name for args in calls if args[:2] == ['file','push']]
        self.assertEqual(pushed, ['guest_security_probe.py','host_security_probe.py','host-reference.json'])
        self.assertTrue(any('rm' in args for args in calls))
        self.assertEqual(report.data['guest_stdout'], 'guest-output')
        self.assertTrue(all(item['status']=='PASS' for item in report.data['checks']))
        runs = [args for args in calls if args[0]=='exec' and args[3]=='python3' and args[4].endswith('/host_security_probe.py')]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0][runs[0].index('--gpu')+1], 'off')
        self.assertEqual(len(report.data['checks']), len({item['check'] for item in report.data['checks']}))

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
                host.validate_guest_report(data,self.reference(),'off')

    def test_complete_report_rejects_missing_duplicate_wrong_gpu_and_false_counts(self):
        valid = self.complete_report()
        self.assertIs(host.validate_guest_report(valid,self.reference(),'off'), valid)
        invalid = []
        for name in ('uid-map','namespace:user','host-canary:0','device:host-disk','binfmt:temporary-mount'):
            data = copy.deepcopy(valid)
            data['checks'] = [item for item in data['checks'] if item['check'] != name]
            data['counts']['PASS'] -= 1
            invalid.append(data)
        data = copy.deepcopy(valid); data['checks'].append(data['checks'][0]); data['counts']['PASS'] += 1; invalid.append(data)
        for field,value in (('gpu_expected','on'),('exit_code',True),('counts',{'PASS':True,'FAIL':0}),
                            ('observations',[{'check':'apparmor','status':'PASS'}])):
            invalid.append({**valid,field:value})
        data = copy.deepcopy(valid); data['observations'] = [dict(data['checks'][0])]; data['observations'][0].pop('status'); invalid.append(data)
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                host.validate_guest_report(data,self.reference(),'off')

    def test_execution_failure_exit_code_must_match_report(self):
        data = self.complete_report(primary=True)
        data['checks'][0]['failure_kind'] = 'execution'
        with self.assertRaises(ValueError):
            host.validate_guest_report(data,self.reference(),'off')
        for code in (2,130):
            data['exit_code'] = code
            self.assertIs(host.validate_guest_report(data,self.reference(),'off'), data)

    def test_shared_socket_checks_use_host_references_once(self):
        reference = self.reference()
        reference['sockets'] = [dict(path=probe.SOCKETS[0],device=1,inode=2),dict(path='/run/extra-host.sock',device=3,inode=4)]
        calls = []
        def bounded(check,args,timeout):
            calls.append((check,args)); return probe.result(check,'PASS','fixture')
        with patch.object(probe,'bounded_call',side_effect=bounded), \
                patch.object(probe,'socket_paths',return_value=([*probe.SOCKETS,probe.SOCKETS[0]],False)):
            probe.run_checks('off',1,lambda item: None,reference=reference)
        sockets = [(check,args) for check,args in calls if check.startswith('management-socket:')]
        self.assertEqual(len(sockets),len(probe.SOCKETS)+1)
        self.assertEqual(len(sockets),len({check for check,args in sockets}))
        self.assertTrue(all(json.loads(args[2]) == reference['sockets'] for check,args in sockets))

    def test_complete_guest_calls_common_checks_once_with_explicit_gpu(self):
        reference = self.reference(); items = []
        with patch.object(probe,'environment_check'), patch.object(probe,'run_checks') as common, \
                patch.object(probe.os,'readlink',side_effect=lambda path: path.rsplit('/',1)[1]+':[456]'), \
                patch.object(probe,'process_roots',return_value=probe.result('process-roots','PASS','fixture')), \
                patch.object(host,'binfmt_existing',return_value=[probe.result('binfmt:existing','PASS','fixture')]), \
                patch.object(probe,'bounded_call',side_effect=lambda check,args,timeout: probe.result(check,'PASS','fixture')), \
                patch.object(host,'bounded_mount',return_value=probe.result('binfmt:temporary-mount','PASS','fixture')):
            host.guest_checks(reference,1,items.append,'on')
        common.assert_called_once_with('on',1,items.append,reference=reference)
        self.assertEqual(len(items),10)

    def test_interruption_recovers_report_and_runs_host_postchecks_and_cleanup(self):
        report,calls = self.run_fixture(interrupted=True)
        self.assertEqual(report.data['fixture_primary_type'],'KeyboardInterrupt')
        self.assertIn('guest_report',report.data)
        self.assertTrue(any('rm' in args for args in calls))
        by_id = {item['check']:item for item in report.data['checks']}
        self.assertEqual(by_id['host-execution']['failure_kind'],'execution')
        for check in ('host-canary-integrity','binfmt:host-unchanged','host-reference'):
            self.assertEqual(by_id[check]['status'],'PASS')

    def test_positive_controls_require_matching_hash_for_both_file_and_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            def command(args):
                if '--_canary' in args:
                    marker = json.loads(args[-1])
                    return json.dumps(probe.result('host-canary:0','FAIL','fixture',
                        attempts=[dict(outcome='readable',sha256=marker['sha256'])]))
                return ''
            self.assertEqual(len(host.positive_controls(command,'demo',Path(directory),'/tmp/owned')),2)
            with self.assertRaises(ValueError):
                host.positive_controls(lambda args: json.dumps(probe.result('host-canary:0','FAIL','fixture',
                    attempts=[dict(outcome='readable',sha256='0'*64)])),'demo',Path(directory),'/tmp/owned')


if __name__ == '__main__':
    unittest.main()
