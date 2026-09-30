"""GPU review regressions across module, menu, renderer and portable runner."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from mas.core import Error
from mas.gpu import _discovery_command, GPU, KEY
from mas.menu import Cancelled
from mas.terminal_ui import UI
from mas.testing import Suite, Terminal, python_command
from mas.test_output import Output
from tests.test_gpu_discovery import DiscoveryTests, spec
from tests.test_menu import MenuTests


class StrictDiscoveryTests(DiscoveryTests):
    # Inherit fixtures, not discovery tests (filtered below).
    def test_malformed_mount_collections_and_options(self):
        for options in ('ro', {'ro': True}, ['ro', 1], None):
            value=spec();value['containerEdits']['mounts'][0]['options']=options
            self.result.stdout=json.dumps(value)
            with self.assertRaises(Error):
                from mas.gpu import wsl_driver_paths
                wsl_driver_paths()
        for mounts in ({}, 'not a list', None):
            value=spec();value['containerEdits']['mounts']=mounts
            self.result.stdout=json.dumps(value)
            with self.assertRaises(Error):wsl_driver_paths()


class ReviewTests(unittest.TestCase):
    def test_corrupt_version_is_rejected_before_host_discovery(self):
        from tests.test_gpu import CAP
        from mas.gpu import devices, CONF
        record=dict(version=True,enabled=True,backend='wsl-nvidia',driver_paths=CAP['driver_paths'],
                    devices=devices('wsl-nvidia',CAP['driver_paths']),runtime_file=CONF)
        manager=Mock();manager.require.return_value={'config':{KEY:json.dumps(record)}}
        with patch('mas.gpu.detect') as query:
            with self.assertRaises(Error):GPU(manager).status('test-example')
        query.assert_not_called()

    def test_cancel_reuses_menu_state_without_mutation_or_requery(self):
        view,manager=Mock(),Mock()
        manager.hardware.return_value={'available':True,'enabled':True,'configured':True}
        view.choose.side_effect=['gpu',Cancelled(),None,None]
        with contextlib.redirect_stdout(io.StringIO()):UI(view,manager).hardware('test-example')
        manager.hardware.assert_called_once_with('test-example')

    def test_menu_refresh_failure_preserves_primary_error_and_leaves(self):
        view, manager = Mock(), Mock()
        manager.hardware.side_effect = [
            {'available': True, 'enabled': True, 'configured': True},
            Error('original mutation failure'), Error('configuration read failure')]
        view.choose.side_effect = ['gpu', False, None]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            UI(view, manager).hardware('test-example')
        self.assertEqual(manager.hardware.call_count, 3)
        self.assertIn('original mutation failure', err.getvalue())
        self.assertIn('configuration read failure', err.getvalue())

    def test_gpu_diagnostic_observer_failure_does_not_replace_result(self):
        result=subprocess.CompletedProcess([],0,'result','unknown native diagnostic')
        output=io.StringIO()
        with patch('mas.gpu.subprocess.run',return_value=result), contextlib.redirect_stderr(output):
            actual=_discovery_command(['fixture'],Mock(side_effect=RuntimeError('observer failed')))
        self.assertIs(actual,result)
        self.assertIn('observer failed',output.getvalue())

    def test_direct_tester_diagnostics_clear_progress_and_are_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            suite=Suite.__new__(Suite);suite.directory=Path(directory);suite.events=[]
            stream=io.StringIO();stream.isatty=lambda:True;suite.output=Output(stream)
            suite.output.progress('TRANSIENT_TICK')
            suite.native_diagnostic('native detail')
            history=MenuTests().render_history(stream.getvalue().encode())
            self.assertIn('native detail',history);self.assertNotIn('TRANSIENT_TICK',history)
            self.assertEqual((suite.directory/'native-diagnostics.log').read_text(),'native detail\n')
            self.assertEqual(suite.events[0]['native_stderr'],'native detail')

    def test_pty_and_cli_query_diagnostics_are_displayed_once_and_recorded(self):
        from mas.testing import PRODUCT_UNDER_TEST
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);binary=root/'lxc'
            binary.write_text("#!/bin/sh\nprintf 'native query detail\\n' >&2\nprintf '[]\\n'\n")
            binary.chmod(0o755)
            with patch.dict(os.environ,{'PATH':str(root)+os.pathsep+os.environ['PATH']}):
                suite=Suite(root/'report',600,PRODUCT_UNDER_TEST)
                try:
                    stream=io.StringIO();suite.output=Output(stream);suite.current_case='tui'
                    with suite.terminal(['list']) as terminal:terminal.finish()
                    self.assertIn(b'native query detail',terminal.buffer)
                    self.assertEqual(stream.getvalue().count('native query detail'),1)
                    suite.cli('list')
                    self.assertEqual(stream.getvalue().count('native query detail'),2)
                    self.assertEqual(sum(e.get('native_stderr')=='native query detail' for e in suite.events),2)
                finally:suite.workspace.cleanup()

    def test_gpu_diagnostic_in_real_terminal_clears_active_progress(self):
        source="""
import subprocess
from unittest.mock import patch
from mas.output import Output
from mas.gpu import _discovery_command
output=Output()
output.progress('TRANSIENT_GPU_TICK')
with patch('mas.gpu.subprocess.run',return_value=subprocess.CompletedProcess([],0,'{}','native GPU detail')):
    _discovery_command(['fixture'],output.keep)
print('FINISHED')
"""
        with tempfile.TemporaryDirectory() as directory:
            terminal=Terminal(python_command(source),300,Path(directory)/'terminal.log')
            try:
                terminal.expect('FINISHED');terminal.finish()
                history=MenuTests().render_history(terminal.buffer)
                self.assertIn('native GPU detail',history)
                self.assertNotIn('TRANSIENT_GPU_TICK',history)
            finally:terminal.close()


def load_tests(loader, tests, pattern):
    # Reuse the discovery fixture without counting/rerunning its inherited cases.
    result=unittest.TestSuite(loader.loadTestsFromTestCase(ReviewTests))
    result.addTest(StrictDiscoveryTests('test_malformed_mount_collections_and_options'))
    return result
