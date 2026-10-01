"""Focused regression tests for the independently delivered guest diagnostic."""
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('guest_probe', Path(__file__).resolve().parents[1] / 'test' / 'guest_security_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class GuestProbeTests(unittest.TestCase):
    def test_reference_rejects_malformed_or_ambiguous_inputs(self):
        valid = {'schema': 1, 'namespaces': {name: name + ':[123]' for name in probe.NAMESPACES}, 'canaries': []}
        self.assertEqual(probe.validate_reference(valid), valid)
        for invalid in ([], {'schema': True}, {**valid, 'namespaces': {'user': 'user:[123]'}},
                        {**valid, 'canaries': [{'path': '/tmp/../secret', 'sha256': '0' * 64}]},
                        {**valid, 'canaries': [{'path': '/tmp/x\n', 'sha256': '0' * 64}]},
                        {**valid, 'canaries': [{'path': 'relative', 'sha256': '0' * 64}]}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                probe.validate_reference(invalid)

    def test_device_denial_differs_from_unavailable_and_open_success(self):
        for error, expected in ((errno.EPERM, 'PASS'), (errno.EACCES, 'PASS'),
                                (errno.ENODEV, 'SKIP'), (errno.EIO, 'ERROR')):
            with patch.object(probe.os, 'mknod', side_effect=OSError(error, 'native')), patch.object(probe.os, 'open') as opened:
                self.assertEqual(probe.active_probe('device', 'host-memory', '/private')['status'], expected)
                opened.assert_not_called()
        with patch.object(probe.os, 'mknod'), patch.object(probe.os, 'open', return_value=55) as opened, patch.object(probe.os, 'close') as closed:
            item = probe.active_probe('device', 'host-memory', '/private')
            self.assertEqual(item['status'], 'FAIL')
            self.assertFalse(opened.call_args.args[1] & os.O_WRONLY)
            closed.assert_called_once_with(55)

    def test_kernel_open_never_writes_or_claims_open_proves_write(self):
        with patch.object(probe.os, 'open', return_value=55) as opened, patch.object(probe.os, 'close'), patch.object(probe.os, 'write') as written:
            item = probe.active_probe('control', '/proc/sysrq-trigger', '/private')
            self.assertEqual(item['status'], 'REVIEW')
            flags = opened.call_args.args[1]
            self.assertTrue(flags & os.O_WRONLY)
            self.assertFalse(flags & (os.O_CREAT | os.O_TRUNC))
            written.assert_not_called()
        with patch.object(probe.os, 'open', side_effect=OSError(errno.EROFS, 'readonly')):
            self.assertEqual(probe.active_probe('control', '/proc/sysrq-trigger', '/private')['status'], 'PASS')

    def test_bounded_child_timeout_and_bad_output_are_errors(self):
        with patch.object(probe.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['test'], 1, b'partial', b'warning')):
            item = probe.bounded_probe('device', 'host-memory', '/private', 1)
            self.assertEqual(item['status'], 'ERROR')
            self.assertEqual(item['evidence']['native_stdout'], 'partial')
        for child in (subprocess.CompletedProcess([], 0, 'invalid', ''),
                      subprocess.CompletedProcess([], 1, '{}', 'failed'),
                      subprocess.CompletedProcess([], 0, 'null', ''),
                      subprocess.CompletedProcess([], 0, '{"status":"PASS"}', '')):
            with patch.object(probe.subprocess, 'run', return_value=child):
                self.assertEqual(probe.bounded_probe('device', 'host-memory', '/private', 1)['status'], 'ERROR')

    def test_gpu_mounts_preserve_authorized_exception_but_require_readonly(self):
        raw = ('20 1 0:1 / / rw - ext4 /dev/root rw\n'
               '21 20 0:2 /lib /usr/lib/wsl/lib ro - 9p lib rw\n'
               '22 20 0:3 /driver /usr/lib/wsl/drivers/selected rw - 9p driver rw\n'
               '23 20 0:4 /driver-store /usr/lib/wsl/drivers ro - 9p store rw\n'
               '24 20 0:5 /home/gordon /shared\\040home ro - ext4 /dev/root rw\n')
        items = {item['check']: item for item in probe.mount_checks(probe.parse_mounts(raw))}
        self.assertEqual(items['gpu-readonly:/usr/lib/wsl/lib']['status'], 'PASS')
        self.assertEqual(items['gpu-readonly:/usr/lib/wsl/drivers/selected']['status'], 'FAIL')
        self.assertEqual(items['gpu-driver-store']['status'], 'FAIL')
        self.assertEqual(items['mount-sources']['status'], 'REVIEW')
        self.assertEqual(items['mount-sources']['evidence']['suspicious'][0]['path'], '/shared home')
        for text in ('', 'malformed'):
            with self.assertRaises(ValueError):
                probe.parse_mounts(text)

    def test_socket_inside_guest_is_review_not_claimed_host_control(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'own.sock')
            self.assertEqual(probe.socket_check(path)['status'], 'PASS')
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(path)
                listener.listen(1)
                self.assertEqual(probe.socket_check(path)['status'], 'REVIEW')
                accepted, _ = listener.accept()
                with accepted:
                    self.assertEqual(accepted.recv(1), b'')

    def test_unique_host_canary_is_confirmed_and_contents_are_not_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'marker'
            content = b'non-secret-unique-host-canary'
            path.write_bytes(content)
            item = probe.canary_check(0, {'path': str(path), 'sha256': hashlib.sha256(content).hexdigest()})
            self.assertEqual(item['status'], 'FAIL')
            self.assertNotIn(content.decode(), json.dumps(item))
            item = probe.canary_check(0, {'path': str(path), 'sha256': '0' * 64})
            self.assertEqual(item['status'], 'REVIEW')
            path.unlink()
            self.assertEqual(probe.canary_check(0, {'path': str(path), 'sha256': '0' * 64})['status'], 'PASS')

    def test_failed_observation_is_not_absence(self):
        with patch.object(probe.os, 'stat', side_effect=PermissionError(errno.EACCES, 'denied')):
            with self.assertRaises(PermissionError):
                probe.visible_paths(('/mnt/c/Windows',))

    def test_privilege_and_host_guards_prevent_probes(self):
        with patch.object(probe.os, 'geteuid', return_value=1000):
            with self.assertRaisesRegex(ValueError, 'sudo'):
                probe.environment_check()
        with patch.object(probe.os, 'geteuid', return_value=0), patch.object(probe, 'read_text', return_value=''), patch.dict(probe.os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, '宿主'):
                probe.environment_check()
        with patch.object(probe, 'environment_check', side_effect=ValueError('host')), patch.object(probe, 'active_probe') as active, patch('sys.stderr', new=io.StringIO()):
            self.assertEqual(probe.main(['--_probe', 'device', 'host-memory', '/private']), 2)
            active.assert_not_called()

    def test_atomic_report_never_overwrites_and_has_private_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            probe.publish_report(path, {'complete': True})
            self.assertEqual(json.loads(path.read_text()), {'complete': True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                probe.publish_report(path, {'complete': False})
            self.assertEqual(json.loads(path.read_text()), {'complete': True})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_summary_retains_skips_reviews_and_errors_in_exit_semantics(self):
        for statuses, expected in ((('PASS', 'SKIP', 'REVIEW'), 0), (('FAIL',), 1), (('ERROR', 'FAIL'), 2)):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'report.json'
                def checks(reference, gpu, timeout, emit):
                    for status in statuses:
                        emit(probe.result(status, status, 'fixture'))
                with patch.object(probe, 'environment_check'), patch.object(probe, 'run_checks', side_effect=checks), patch('sys.stdout', new=io.StringIO()):
                    self.assertEqual(probe.main(['--report', str(path)]), expected)
                report = json.loads(path.read_text())
                self.assertEqual(report['exit_code'], expected)
                self.assertEqual([item['status'] for item in report['checks']], list(statuses))

    def test_report_failure_and_existing_destination_do_not_run_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            path.write_text('keep')
            with patch.object(probe, 'run_checks') as checks, patch('sys.stdout', new=io.StringIO()), patch('sys.stderr', new=io.StringIO()):
                self.assertEqual(probe.main(['--report', str(path)]), 2)
                checks.assert_not_called()
            self.assertEqual(path.read_text(), 'keep')

    def test_gate_failure_explains_the_problem_and_never_runs_probes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            out, err = io.StringIO(), io.StringIO()
            with (patch.object(probe, 'environment_check', side_effect=ValueError('请使用 sudo\n\x1b[2J')),
                    patch.object(probe, 'run_checks') as checks,
                    patch('sys.stdout', new=out), patch('sys.stderr', new=err)):
                self.assertEqual(probe.main(['--report', str(path)]), 2)
                checks.assert_not_called()
            self.assertIn('请使用 sudo', err.getvalue())
            self.assertNotIn('\x1b', err.getvalue())
            self.assertIn('\\u001b', err.getvalue())
            self.assertEqual(json.loads(path.read_text())['counts']['ERROR'], 1)

    def test_report_and_console_explain_method_denied_step_and_native_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            item = probe.denied_result('device:host-memory', 'mknod', OSError(errno.EPERM, 'native'))
            def checks(reference, gpu, timeout, emit):
                emit(item)
            output = io.StringIO()
            with patch.object(probe, 'environment_check'), patch.object(probe, 'run_checks', side_effect=checks), patch('sys.stdout', new=output):
                self.assertEqual(probe.main(['--report', str(path)]), 0)
            self.assertIn('mknod char 1:1', output.getvalue())
            self.assertIn('"step": "mknod"', output.getvalue())
            self.assertIn('"errno": 1', output.getvalue())
            self.assertEqual(json.loads(path.read_text())['checks'][0], item)

    def test_all_real_check_families_have_precise_methods_and_terminal_safe_text(self):
        checks = ['uid-map', 'gid-map', 'seccomp', 'capabilities', 'apparmor', 'basic-interfaces',
                  'gpu-driver-store', 'mount-sources', 'devlxd', 'windows-interop', 'gpu-expectation',
                  'host-canaries', 'network-policy', 'execution', 'host-canary:0',
                  'gpu-readonly:/usr/lib/wsl/lib']
        checks += ['device:' + name for name in probe.DEVICES]
        checks += ['control:' + path for path in probe.CONTROLS]
        checks += ['namespace:' + name for name in probe.NAMESPACES]
        checks += ['management-socket:' + path for path in probe.SOCKETS]
        for check in checks:
            with self.subTest(check=check):
                self.assertNotEqual(probe.check_method(check), '执行此项检查')
        self.assertEqual(probe.terminal_text('路径\x1b[2J\n\x00'), '路径\\u001b[2J\\n\\u0000')


class DownloadEntryTests(unittest.TestCase):
    def run_entry(self, directory, args=(), **settings):
        root = Path(directory)
        binaries = root / 'bin'
        binaries.mkdir(exist_ok=True)
        temporary = root / 'temporary'
        temporary.mkdir(exist_ok=True)
        helper = '''import json, os, pathlib, shutil, sys
name = pathlib.Path(sys.argv[0]).name
root = pathlib.Path(os.environ['PROBE_ENTRY_FIXTURE'])
with (root / 'calls.jsonl').open('a') as log:
    log.write(json.dumps([name, sys.argv[1:]]) + '\\n')
if name == 'curl':
    if os.environ.get('DOWNLOAD_EXIT'):
        print('native download error', file=sys.stderr)
        sys.exit(int(os.environ['DOWNLOAD_EXIT']))
    destination = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])
    shutil.copyfile(os.environ['PROBE_SOURCE'], destination)
elif name == 'sudo':
    assert sys.argv[1] == '--'
    os.execvp(sys.argv[2], sys.argv[2:])
elif name == 'python3':
    if sys.argv[1] == '-c':
        sys.exit(int(os.environ.get('VERSION_EXIT', '0')))
    path = pathlib.Path(sys.argv[1])
    assert path.is_file() and path.read_bytes() == pathlib.Path(os.environ['PROBE_SOURCE']).read_bytes()
    if os.environ.get('REAL_PYTHON'):
        os.execv(sys.executable, [sys.executable] + sys.argv[1:])
    (root / 'invocation.json').write_text(json.dumps({'file': str(path), 'args': sys.argv[2:], 'cwd': os.getcwd()}))
    sys.exit(int(os.environ.get('PROBE_EXIT', '0')))
'''
        for name in ('curl', 'python3', 'sudo'):
            path = binaries / name
            path.write_text('#!' + sys.executable + '\n' + helper)
            path.chmod(0o700)
        environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'],
                           TMPDIR=str(temporary), PROBE_ENTRY_FIXTURE=str(root),
                           PROBE_SOURCE=str(Path(probe.__file__)))
        environment.update(settings)
        entry = Path(probe.__file__).with_name('security.sh')
        process = subprocess.run(['bash', str(entry), *args], cwd=root, env=environment,
                                 capture_output=True, text=True, timeout=10)
        calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
        self.assertEqual(list(temporary.iterdir()), [], 'downloaded program must be reclaimed')
        return process, calls

    def test_entry_downloads_real_file_preserves_arguments_workdir_and_native_sudo(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ('--report', 'report with spaces.json', '--gpu', 'off')
            process, calls = self.run_entry(directory, args)
            self.assertEqual(process.returncode, 0, process.stderr)
            invocation = json.loads((Path(directory) / 'invocation.json').read_text())
            self.assertEqual(invocation['args'], list(args))
            self.assertEqual(invocation['cwd'], directory)
            self.assertFalse(Path(invocation['file']).exists())
            downloads = [args for name, args in calls if name == 'curl']
            self.assertEqual(len(downloads), 1)
            self.assertIn('https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/guest_security_probe.py', downloads[0])
            sudo = [args for name, args in calls if name == 'sudo']
            self.assertEqual(len(sudo), 0 if os.geteuid() == 0 else 1)
            if sudo:
                self.assertEqual(sudo[0][:2], ['--', 'python3'])

    def test_failure_and_interruption_codes_preserved_and_downloads_reclaimed(self):
        for code in (1, 2, 130):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                process, _ = self.run_entry(directory, PROBE_EXIT=str(code))
                self.assertEqual(process.returncode, code)

    def test_failed_download_never_executes_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            process, calls = self.run_entry(directory, DOWNLOAD_EXIT='22')
            self.assertEqual(process.returncode, 22)
            self.assertIn('native download error', process.stderr)
            self.assertFalse((Path(directory) / 'invocation.json').exists())
            self.assertEqual([name for name, _ in calls], ['python3', 'curl'])

    def test_old_python_fails_before_downloading_or_elevating(self):
        with tempfile.TemporaryDirectory() as directory:
            process, calls = self.run_entry(directory, VERSION_EXIT='2')
            self.assertEqual(process.returncode, 2)
            self.assertIn('Python 版本必须为 3.10', process.stderr)
            self.assertEqual([name for name, _ in calls], ['python3'])

    def test_downloaded_actual_script_help_runs_without_checkout_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            process, _ = self.run_entry(directory, ('--help',), REAL_PYTHON='1')
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn('--host-reference', process.stdout)
            self.assertIn('隔离边界', process.stdout)
            self.assertEqual(list(Path(directory).glob('guest-security-*.json')), [])


if __name__ == '__main__':
    unittest.main()
