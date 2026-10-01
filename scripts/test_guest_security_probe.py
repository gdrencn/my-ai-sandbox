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
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('guest_probe', Path(__file__).with_name('guest_security_probe.py'))
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


if __name__ == '__main__':
    unittest.main()
