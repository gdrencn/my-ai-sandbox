"""Verify policy rejection evidence and failed guest-report recovery."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from mas.core import Error
from mas.test_output import Output
from mas.testing import Suite


class SecurityRunnerTests(unittest.TestCase):
    def setUp(self):
        language = patch('mas.config.language', return_value='en_us')
        language.start()
        self.addCleanup(language.stop)
        self.suite = Suite.__new__(Suite)
        self.suite.manager = Mock()
        self.suite.events = []
        self.suite.project = "fixture-project"
        self.suite.output = Output(io.StringIO())

    def test_only_explicit_policy_denials_are_counted_as_refusals(self):
        for message in ('Privileged containers are forbidden', 'Disk source path not allowed',
                        'permission denied', 'connection refused', 'unknown configuration key'):
            with self.subTest(message=message):
                self.suite.events.clear()
                self.suite.manager.lxd.command.side_effect = Error(message)
                if 'forbidden' in message or 'not allowed' in message:
                    self.suite.expected_native_refusal(['fixture'])
                    self.assertEqual(len(self.suite.events), 1)
                else:
                    with self.assertRaisesRegex(AssertionError, 'unrelated error'):
                        self.suite.expected_native_refusal(['fixture'])
                    self.assertEqual(self.suite.events, [])

    def test_accepted_native_update_is_never_a_policy_pass(self):
        self.suite.manager.lxd.command.return_value = ''
        with self.assertRaises(AssertionError):
            self.suite.expected_native_refusal(['fixture'])
        self.assertEqual(self.suite.events, [])

    def guest_fixture(self, pull_failure=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.suite.workspace = directory
        self.suite.directory = Path(directory.name)
        self.suite.guest_reports = []
        self.suite.manager.gpu.record.return_value = None
        self.suite.manager.require.return_value = {"status":"Running", "config":{"volatile.uuid":"fixture-identity"}}
        primary = Error('guest probe found a boundary failure')
        calls = []
        def command(args):
            calls.append(args)
            if args[:3] == ['exec', 'local:fixture', '--']:
                if args[3:5] == ['python3', '-c']:
                    return '/tmp/mas-host-challenge-fixture\n'
                if args[3] == 'python3':
                    raise primary
                return ''
            if args[:2] == ['file', 'pull']:
                if pull_failure:
                    raise Error('secondary report retrieval error')
                Path(args[-1]).write_text(json.dumps({'exit_code': 1, 'counts': {'FAIL': 1, 'ERROR': 0}}))
            return ''
        self.suite.manager.lxd.command.side_effect = command
        return primary, calls

    def test_failed_guest_probe_retains_report_before_cleanup_and_original_error(self):
        primary, calls = self.guest_fixture()
        with self.assertRaises(Error) as failure:
            self.suite.guest_boundary('fixture')
        self.assertIs(failure.exception, primary)
        self.assertGreaterEqual(self.suite.guest_reports[0]['report']['counts']['FAIL'], 1)
        self.assertIn(str(primary), self.suite.output.stream.getvalue())
        self.assertTrue((self.suite.directory / 'boundary-1.json').is_file())
        self.assertEqual(self.suite.guest_reports[0]['status'], 'failed')
        self.assertLess(next(i for i, args in enumerate(calls) if args[:2] == ['file', 'pull']),
                        next(i for i, args in enumerate(calls) if 'rm' in args))
        self.assertEqual(list(self.suite.directory.glob('host-canary-*')), [])

    def test_report_retrieval_failure_does_not_replace_probe_failure(self):
        primary, calls = self.guest_fixture(pull_failure=True)
        with self.assertRaises(Error) as failure:
            self.suite.guest_boundary('fixture')
        self.assertIs(failure.exception, primary)
        self.assertTrue(any('rm' in args for args in calls))
        self.assertTrue((self.suite.directory / 'boundary-1.log').is_file())
