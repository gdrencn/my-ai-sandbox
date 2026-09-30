"""Verify that the verifier cannot silently report failed work as successful."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from mas import testing
from mas.test_output import Output


class RunnerTests(unittest.TestCase):
    def setUp(self):
        language=patch('mas.config.language',return_value='en_us')
        language.start();self.addCleanup(language.stop)

    def runner(self, failure=None, cleanup_failure=None, save_failure=None):
        suite=testing.Suite.__new__(testing.Suite)
        suite.started=time.monotonic()
        suite.directory=Path('/unused/test-report')
        suite.results={'unit':{'status':'not_run'},'new-default':{'status':'not_run'}}
        suite.cleanup_errors=[]
        stream=io.StringIO();suite.output=Output(stream)
        def run():
            with suite.case('unit'):
                if failure:raise failure
            with suite.case('new-default'):pass
        suite.run=run
        suite.cleanup=Mock(side_effect=cleanup_failure)
        suite.save=Mock(side_effect=save_failure)
        with patch.object(testing,'Suite',return_value=suite),patch.object(testing,'PRODUCT_UNDER_TEST'), \
                contextlib.redirect_stderr(io.StringIO()):
            code=testing.main(['--output','/unused/test-report'])
        return code,suite,stream.getvalue()

    def test_failure_and_interrupt_preserve_not_run_and_cleanup(self):
        for failure in (AssertionError('injected failure'),KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                code,suite,output=self.runner(failure)
                self.assertEqual(code,1)
                self.assertEqual(suite.results['unit']['status'],'failed')
                self.assertEqual(suite.results['new-default']['status'],'not_run')
                suite.cleanup.assert_called_once();suite.save.assert_called_once()
                self.assertIn('0 passed, 1 failed, 1 not run',output)

    def test_cleanup_failure_cannot_report_overall_success(self):
        code,suite,output=self.runner(cleanup_failure=OSError('cleanup refused'))
        self.assertEqual(code,1)
        self.assertEqual(suite.cleanup_errors,['cleanup refused'])
        suite.save.assert_called_once()
        self.assertIn('Cleanup failed: cleanup refused',output)
        self.assertNotIn('resources cleaned up',output)

    def test_report_failure_causes_nonzero_exit(self):
        code,suite,output=self.runner(save_failure=OSError('report disk full'))
        self.assertEqual(code,1)
        self.assertIn('report disk full',output)
        suite.cleanup.assert_called_once()

    def test_success_records_each_group(self):
        code,suite,output=self.runner()
        self.assertEqual(code,0)
        self.assertTrue(all(value['status']=='passed' for value in suite.results.values()))
        self.assertIn('2 passed, 0 failed, 0 not run',output)

    def test_unit_discovery_includes_new_modules_and_identifiers(self):
        modules=testing.unit_modules()
        names=[module.__name__ for module in modules]
        self.assertIn('tests.test_failures',names)
        self.assertIn('tests.test_runner',names)
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module) for module in modules)
        identifiers=list(testing.test_ids(suite))
        self.assertEqual(len(identifiers),suite.countTestCases())
        self.assertEqual(len(identifiers),len(set(identifiers)))

    def test_unit_report_records_skips_failures_errors_and_test_ids(self):
        class Examples(unittest.TestCase):
            def test_pass(self):pass
            @unittest.skip('unavailable fixture')
            def test_skip(self):pass
            def test_fail(self):self.fail('failure')
            def test_error(self):raise RuntimeError('error')
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(Examples)
        identifiers=list(testing.test_ids(suite))
        result=unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        summary=testing.unit_summary(result,[SimpleNamespace(__name__='fixture')],identifiers)
        self.assertEqual(summary['tests_run'],4)
        self.assertEqual((summary['failures'],summary['errors']),(1,1))
        self.assertFalse(summary['successful'])
        self.assertEqual(summary['skipped'][0]['reason'],'unavailable fixture')
        self.assertEqual(len(summary['test_ids']),4)

    def test_python_fixture_uses_tester_origin_outside_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            # Neither cwd nor PYTHONPATH may shadow the archive being tested.
            Path(directory, 'mas.py').write_text('raise RuntimeError("wrong mas")')
            Path(directory, 'shadow_only.py').write_text('VALUE = True')
            source = (
                'import importlib.util, mas.testing; '
                'print(mas.testing.__file__); '
                'assert importlib.util.find_spec("shadow_only") is None'
            )
            with patch.object(sys, 'path', [directory, *sys.path]):
                command = testing.python_command(source)
            result = subprocess.run(command, cwd=directory,
                                    env={**os.environ, 'PYTHONPATH': directory},
                                    capture_output=True, text=True, timeout=300)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), testing.__file__)

    def test_optimized_python_refuses_to_run_verification(self):
        source='from mas.testing import main;main([])'
        result=subprocess.run(testing.python_command(source, '-O'),capture_output=True,text=True,timeout=300)
        self.assertEqual(result.returncode,2)
        self.assertIn('PYTHONOPTIMIZE',result.stderr)

    def test_bootstrap_checksum_failure_prevents_installation(self):
        import bootstrap
        from mas import __version__
        release={'tag_name':'v'+__version__,'assets':[dict(name=name,browser_download_url=name)
                 for name in ('SHA256SUMS','mas.pyz','mas-install.pyz')]}
        def download(name):
            return b'0000  mas.pyz\n0000  mas-install.pyz\n' if name=='SHA256SUMS' else b'corrupted download'
        with patch.object(sys,'argv',['bootstrap.py','--language','en_us']), \
                patch.object(bootstrap,'choose_language'),patch.object(bootstrap,'release',return_value=release), \
                patch.object(bootstrap,'download',side_effect=download),patch.object(bootstrap.subprocess,'call') as execute, \
                contextlib.redirect_stdout(io.StringIO()),self.assertRaisesRegex(RuntimeError,'Checksum mismatch'):
            bootstrap.main()
        execute.assert_not_called()

    def test_cleanup_recovers_mounts_before_querying_missing_target(self):
        suite=testing.Suite.__new__(testing.Suite)
        suite.output=Output(io.StringIO())
        suite.workspace=Mock();suite.created_project=True
        suite.targets=['test-fixture'];suite.cleanup_errors=[]
        suite.manager=Mock();suite.host=Mock();suite.project='test-project'
        suite.manager.mountedfs.return_value=[{'path':'/var/log'}]
        def find(target):
            suite.manager.unmountfs.assert_called_once_with(target,'/var/log')
            return None
        suite.manager.find.side_effect=find
        suite.cleanup()
        self.assertEqual(suite.cleanup_errors,[])
        suite.manager._run_lxd_until_state.assert_not_called()
