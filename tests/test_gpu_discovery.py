"""Official WSL discovery boundaries: no directory guessing or CDI execution."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from mas.core import Error
from mas.gpu import CTK, wsl_driver_paths

ACTIVE = '/usr/lib/wsl/drivers/nvidia-active'


def spec(path=ACTIVE):
    return {'kind': 'nvidia.com/gpu', 'cdiVersion': '0.3.0',
            'devices': [{'name': 'all', 'containerEdits': {'deviceNodes': [{'path': '/dev/dxg'}]}}],
            'containerEdits': {'hooks': [{'path': '/never-execute'}],
                'mounts': [{'hostPath': path+'/libcuda.so.1.1',
                            'containerPath': path+'/libcuda.so.1.1', 'options': ['ro']}]}}


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.result = subprocess.CompletedProcess([], 0, json.dumps(spec()), '')
        for name, replacement in [('subprocess.run', None), ('Path.is_file', True),
                                   ('Path.glob', None)]:
            kwargs = {'return_value': replacement}
            if name == 'subprocess.run': kwargs = {'side_effect': lambda *a, **kw: self.result}
            if name == 'Path.glob': kwargs = {'side_effect': AssertionError('directory scanning forbidden')}
            p = patch('mas.gpu.'+name, **kwargs)
            mock = p.start(); self.addCleanup(p.stop)
            if name == 'subprocess.run': self.run = mock
        p=patch('mas.gpu.Path.resolve', autospec=True, side_effect=lambda path, **kw: path)
        p.start();self.addCleanup(p.stop)

    def test_official_selected_path_and_hooks_are_not_executed(self):
        self.assertEqual(wsl_driver_paths(), [ACTIVE])
        args, kwargs = self.run.call_args
        self.assertEqual(args[0], [CTK, 'cdi', 'generate', '--mode=wsl', '--format=json', '--output', '',
                                  '--disable-hook=all', '--nvidia-cdi-hook-path=' + CTK,
                                  '--feature-flag=disable-nvsandboxutils'])
        self.assertEqual(kwargs['timeout'], 600)
        self.assertEqual(self.run.call_count, 1)

    def test_paths_in_device_edits_are_supported_and_deduplicated(self):
        d=spec();d['devices'][0]['containerEdits']['mounts']=d['containerEdits']['mounts'][:]
        self.result.stdout=json.dumps(d)
        self.assertEqual(wsl_driver_paths(),[ACTIVE])
        d['containerEdits'].pop('mounts');self.result.stdout=json.dumps(d)
        self.assertEqual(wsl_driver_paths(),[ACTIVE])

    def test_selection_is_requeried_not_cached(self):
        self.assertEqual(wsl_driver_paths(),[ACTIVE])
        self.result.stdout=json.dumps(spec('/usr/lib/wsl/drivers/nvidia-updated'))
        self.assertEqual(wsl_driver_paths(),['/usr/lib/wsl/drivers/nvidia-updated'])

    def test_missing_tool_and_native_failures_do_not_fallback(self):
        with patch('mas.gpu.Path.is_file',return_value=False):
            with self.assertRaises(Error):wsl_driver_paths()
        self.run.assert_not_called()
        self.result.returncode=1;self.result.stderr='official failure'
        with self.assertRaisesRegex(Error,'official failure'):wsl_driver_paths()
        for exc in (OSError('cannot execute'),subprocess.TimeoutExpired(CTK,600)):
            with patch('mas.gpu.subprocess.run',side_effect=exc):
                with self.assertRaises(Error):wsl_driver_paths()

    def test_malformed_empty_or_wrong_kind_spec_is_rejected(self):
        for value in ('not json', 'null', '[]', '{}', json.dumps({**spec(),'kind':'other/gpu'}),
                      json.dumps({**spec(),'devices':[]}),
                      json.dumps({**spec(),'containerEdits':{}})):
            with self.subTest(value=value):
                self.result.stdout=value
                with self.assertRaises(Error):wsl_driver_paths()

    def test_unsafe_missing_changed_or_writable_paths_are_rejected(self):
        for path in ('/etc','/usr/lib/wsl/drivers/..','/usr/lib/wsl/drivers/a/../b',
                     '/usr/lib/wsl/drivers/a/subdir'):
            self.result.stdout=json.dumps(spec(path))
            with self.assertRaises(Error):wsl_driver_paths()
        for field,value in [('containerPath','/different'),('options',['rw'])]:
            d=spec();d['containerEdits']['mounts'][0][field]=value;self.result.stdout=json.dumps(d)
            with self.assertRaises(Error):wsl_driver_paths()
        self.result.stdout=json.dumps(spec())
        with patch('mas.gpu.Path.is_file',side_effect=[True, False]):
            with self.assertRaises(Error):wsl_driver_paths()
        with patch('mas.gpu.Path.resolve',return_value=Path('/etc/libcuda.so.1.1')):
            with self.assertRaises(Error):wsl_driver_paths()

    def test_warnings_preserved_info_not_printed(self):
        self.result.stderr='time="x" level=info msg="selected"\ntime="x" level=warning msg="notice"\nunknown diagnostic\n'
        output=io.StringIO()
        with contextlib.redirect_stderr(output):wsl_driver_paths()
        self.assertNotIn('selected',output.getvalue())
        self.assertIn('notice',output.getvalue());self.assertIn('unknown diagnostic',output.getvalue())
