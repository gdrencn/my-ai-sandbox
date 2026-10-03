"""Verify the test-stage contract in plain streams and actual terminals."""
import contextlib
import io
import json
import re
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from mas.i18n import catalog
from mas.test_output import Output
from mas.testing import Suite, Terminal, python_command


class TestOutputTests(unittest.TestCase):
    def test_every_stage_has_one_of_seven_categories_and_localized_explanations(self):
        self.assertEqual(set(Suite.CASES), set(Suite.CASE_CATEGORIES))
        self.assertEqual(len(Suite.CASES), len(set(Suite.CASES)))
        self.assertEqual(set(Suite.CASE_CATEGORIES.values()),
                         {'foundation','environment','management','configuration','resources','interaction','security'})
        for language in ('zh_cn','en_us'):
            messages = catalog(language)
            for case, category in Suite.CASE_CATEGORIES.items():
                for key in ('case_'+case, 'test_description_'+case, 'test_category_'+category):
                    self.assertTrue(messages[key].strip(), key)
                    self.assertNotIn('\n', messages[key], key)
                    self.assertNotIn('\033', messages[key], key)

    def test_plain_stages_keep_explanations_before_details_and_outcomes(self):
        suite = Suite.__new__(Suite)
        suite.output = Output(io.StringIO())
        suite.results = {}
        with patch('mas.config.language', return_value='en_us'):
            with suite.case('unit'):
                suite.results['unit'] = {'status': 'not_run', 'evidence': {'native_observation': 'retained'}}
                suite.output.keep('first detail')
            with suite.case('new-default'):
                suite.output.keep('second detail')
        text = suite.output.stream.getvalue()
        self.assertNotIn('\033', text)
        self.assertEqual(sum(line.startswith('─') for line in text.splitlines()), 2)
        self.assertLess(text.index('[Foundation]'), text.index('first detail'))
        self.assertLess(text.index('first detail'), text.index('✓ Unit tests passed'))
        self.assertLess(text.index('✓ Unit tests passed'), text.index('[Container management]'))
        self.assertEqual(suite.results['unit']['category'], 'foundation')
        self.assertEqual(suite.results['unit']['status'], 'passed')
        self.assertEqual(suite.results['unit']['evidence'], {'native_observation': 'retained'})
        self.assertIn('Verify shared behavior', suite.results['unit']['description'])
        self.assertNotIn('\033', json.dumps(suite.results))

    def test_failed_stage_keeps_primary_and_has_no_success_result(self):
        suite = Suite.__new__(Suite)
        suite.output = Output(io.StringIO())
        suite.results = {}
        error = KeyboardInterrupt('interrupted fixture')
        with patch('mas.config.language', return_value='en_us'), self.assertRaises(KeyboardInterrupt) as caught:
            with suite.case('isolation-runtime'):
                suite.results['isolation-runtime'] = {'evidence': {'completed_check': 'retained'}}
                raise error
        self.assertIs(caught.exception, error)
        self.assertEqual(suite.results['isolation-runtime']['status'], 'failed')
        self.assertEqual(suite.results['isolation-runtime']['evidence'], {'completed_check': 'retained'})
        self.assertEqual(suite.results['isolation-runtime']['category'], 'security')
        self.assertIn('[Security challenge]', suite.output.stream.getvalue())
        self.assertIn('✗', suite.output.stream.getvalue())
        self.assertNotIn('✓', suite.output.stream.getvalue())

    def test_plain_colors_are_absent_and_raw_diagnostics_are_retained(self):
        output = Output(io.StringIO())
        with patch('mas.config.language', return_value='zh_cn'):
            output.expected_error('hardware fixture gpu off')
        output.result('✓ success', passed=True)
        output.result('✗ failed', passed=False)
        output.challenge('[通过] check：fixture')
        output.diagnostics('', 'third-party warning unchanged')
        self.assertEqual(output.stream.getvalue(),
                         '预期错误：hardware fixture gpu off\n✓ success\n✗ failed\n'
                         '✓ [通过] check：fixture\nthird-party warning unchanged\n')
        self.assertNotIn('\033', output.stream.getvalue())

    def test_actual_terminals_clear_progress_and_color_only_owned_marks_and_label(self):
        source = '''import io, json, os, sys, termios, fcntl, struct
from unittest.mock import patch
from mas.test_output import Output
from mas.testing import Suite
fcntl.ioctl(sys.stdout.fileno(), termios.TIOCSWINSZ, struct.pack('HHHH',24,32,0,0))
suite=Suite.__new__(Suite);suite.output=Output();suite.results={}
with patch('mas.config.language',return_value=LANGUAGE):
    suite.output.progress('old progress')
    with suite.case('unit'):
        suite.output.progress('active progress')
        suite.output.expected_error('UNCHANGED-COMMAND')
        suite.output.keep('NATIVE-DIAGNOSTIC')
        suite.output.challenge('[通过] check：success')
        suite.output.challenge('  方法：UNCHANGED-METHOD')
    try:
        with suite.case('new-default'):
            raise RuntimeError('UNCHANGED-FAILURE')
    except RuntimeError:
        pass
print('RESULTS:'+json.dumps(suite.results))
print('FINISHED')
'''
        for language, label in (('zh_cn','预期错误'),('en_us','Expected error')):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as directory:
                terminal = Terminal(python_command(source.replace('LANGUAGE', repr(language))), 10,
                                    Path(directory)/'output.log')
                try:
                    terminal.expect('FINISHED'); terminal.finish()
                    raw = terminal.buffer.decode()
                    self.assertIn('\033[33m'+label+'\033[0m', raw)
                    self.assertIn('\033[32m✓\033[0m', raw)
                    self.assertIn('\033[31m✗\033[0m', raw)
                    self.assertNotIn('\033[43m', raw)
                    self.assertIn('UNCHANGED-COMMAND', raw)
                    self.assertIn('NATIVE-DIAGNOSTIC\r\n', raw)
                    self.assertIn('  方法：UNCHANGED-METHOD\r\n', raw)
                    self.assertIn('active progress\r\033[2K\033[33m', raw)
                    self.assertEqual([len(line) for line in re.findall('─+', raw)], [31,31])
                    result_line = next(line for line in raw.splitlines() if line.startswith('RESULTS:'))
                    self.assertNotIn('\033', result_line)
                    self.assertNotIn('\\u001b', result_line)
                finally:
                    terminal.close()

    def test_separator_falls_back_for_a_plain_stream(self):
        output = Output(io.StringIO())
        with patch('mas.config.language', return_value='en_us'), patch('mas.test_output.shutil.get_terminal_size') as size:
            size.return_value.columns = 12
            output.section('Resources','Fixture','All explanation text remains visible.')
        self.assertEqual(output.stream.getvalue().splitlines()[0], '─'*11)
        self.assertIn('All explanation text remains visible.', output.stream.getvalue())

    def test_successful_help_keeps_raw_log_and_stderr_without_promoting_help_text(self):
        for failed in (False,True):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as directory:
                suite = Suite.__new__(Suite)
                suite.output = Output(io.StringIO())
                suite.directory = Path(directory)
                suite.language = 'en_us'; suite.counter = 0; suite.timeout = 300
                suite.events = []; suite.cleanup_errors = []
                def command(args):
                    suite.event_path = suite.directory/'events.jsonl'
                    return [sys.executable,'-c',
                            "import sys;print('restart: failed stop prevents start');"
                            "print('unknown stderr retained',file=sys.stderr);sys.exit("+str(int(failed))+")"]
                suite.command = command
                with patch('mas.config.language',return_value='en_us'), patch('mas.testing.time.sleep'):
                    raw = suite.cli('--help',code=int(failed))
                self.assertIn('failed stop',raw)
                self.assertIn('failed stop',(suite.directory/'cli-1.stdout.log').read_text())
                visible = suite.output.stream.getvalue()
                self.assertIn('unknown stderr retained',visible)
                self.assertEqual('failed stop' in visible,failed)


if __name__ == '__main__':
    unittest.main()
