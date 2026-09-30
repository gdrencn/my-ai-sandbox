"""Exercise the real HTTP/Unix transport and conditional LXD write contract."""
import copy
import http.server
import json
import os
from pathlib import Path
import socketserver
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from mas.core import Error
from mas.lxd_config import Configuration, local_socket
from mas.i18n import t


class UnixServer(socketserver.UnixStreamServer):
    allow_reuse_address = True


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.item = dict(config={'user.keep': 'yes'}, devices={'root': {'type': 'disk', 'path': '/'}},
                         stateful=True, description='keep', profiles=['default'], architecture='x86_64',
                         ephemeral=False, name='test-config', status='Stopped')
        self.etag = '"one"'
        self.requests = []
        self.operation_codes = [103, 200]
        self.operation_error = ''
        fixture = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def respond(self, code, body, etag=None):
                data = json.dumps(body).encode()
                self.send_response(code)
                if etag is not None:
                    self.send_header('ETag', etag)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def do_GET(self):
                fixture.requests.append(('GET', self.path, dict(self.headers), None))
                if '/operations/' in self.path:
                    code = fixture.operation_codes.pop(0) if len(fixture.operation_codes) > 1 else fixture.operation_codes[0]
                    self.respond(200, dict(type='sync', status_code=200, metadata=dict(status_code=code, err=fixture.operation_error)))
                else:
                    self.respond(200, dict(type='sync', status_code=200, metadata=fixture.item), fixture.etag)
            def do_PUT(self):
                value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture.requests.append(('PUT', self.path, dict(self.headers), value))
                if self.headers.get('If-Match') != fixture.etag:
                    self.respond(412, dict(type='error', error='ETag mismatch'))
                    return
                fixture.item.update(value)
                fixture.etag = '"two"'
                self.respond(202, dict(type='async', status_code=100, operation='/1.0/operations/config-test'))
        self.server = UnixServer(str(Path(self.directory.name)/'socket'), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.client = Configuration(SimpleNamespace(prefix=['/snap/bin/lxc'], project='isolated project', timeout=600))
        self.client.socket = str(Path(self.directory.name)/'socket')

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_conditional_publication_preserves_fields_and_waits_for_native_completion(self):
        value, etag = self.client.read('test-config')
        value['config']['user.new'] = 'published'
        wait = Mock()
        self.client.write('test-config', value, etag, on_wait=wait)
        put = next(request for request in self.requests if request[0] == 'PUT')
        self.assertEqual(put[2]['If-Match'], '"one"')
        self.assertTrue(put[3]['stateful'])
        self.assertEqual(put[3]['description'], 'keep')
        self.assertEqual(put[3]['devices'], {'root': {'type': 'disk', 'path': '/'}})
        self.assertNotIn('status', put[3])
        self.assertEqual(self.item['config']['user.keep'], 'yes')
        self.assertEqual(len([r for r in self.requests if '/operations/' in r[1]]), 2)
        wait.assert_called_once()
        for _, endpoint, _, _ in self.requests:
            self.assertEqual(parse_qs(urlsplit(endpoint).query), {'project': ['isolated project']})

    def test_native_concurrent_change_rejects_stale_write_without_retry(self):
        value, etag = self.client.read('test-config')
        self.item['config']['user.keep'] = 'native-change'
        self.etag = '"changed"'
        value['config']['user.gpu'] = 'must-not-publish'
        with self.assertRaisesRegex(Error, t('lxd_config_changed')):
            self.client.write('test-config', value, etag)
        self.assertEqual(self.item['config']['user.keep'], 'native-change')
        self.assertNotIn('user.gpu', self.item['config'])
        self.assertEqual(sum(r[0] == 'PUT' for r in self.requests), 1)
        self.assertFalse(any('/operations/' in r[1] for r in self.requests))

    def test_missing_invalid_etag_and_unsafe_target_never_publish(self):
        for etag in (None, '', '*', 'unquoted', '"bad\nheader"'):
            with self.subTest(etag=etag):
                self.etag = etag
                # Invalid multiline header is checked directly, not sent by HTTP.
                with self.assertRaises(Error):
                    if etag and '\n' in etag:
                        self.client.write('test-config', self.item, etag)
                    else:
                        self.client.read('test-config')
        with self.assertRaises(Error):
            self.client.write('remote:test', self.item, '"one"')
        self.assertFalse(any(r[0] == 'PUT' for r in self.requests))

    def test_failed_native_operation_is_not_success(self):
        value, etag = self.client.read('test-config')
        self.operation_codes = [400]
        self.operation_error = 'native validation failed'
        with self.assertRaisesRegex(Error, 'native validation failed'):
            self.client.write('test-config', value, etag)

    def test_poll_timeout_retains_accepted_operation_and_does_not_resubmit(self):
        value, etag = self.client.read('test-config')
        self.operation_codes = [103]
        clock = [0]
        def advance(seconds):
            clock[0] += 300
        with patch('mas.lxd_config.time.monotonic', side_effect=lambda: clock[0]), patch('mas.lxd_config.time.sleep', side_effect=advance):
            with self.assertRaisesRegex(Error, t('lxd_config_timeout')):
                self.client.write('test-config', value, etag)
        self.assertEqual(sum(r[0] == 'PUT' for r in self.requests), 1)

    def test_malformed_api_and_operation_results_fail_explicitly(self):
        for response in ({}, {'type': 'sync', 'metadata': self.item},
                         {'type': 'sync', 'status_code': 200, 'metadata': []}):
            with patch.object(self.client, 'request', return_value=(response, '"one"')):
                with self.assertRaises(Error):self.client.read('test-config')
        for operation in ('https://outside/1.0/operations/x', '/1.0/instances/x', None):
            with patch.object(self.client, 'request', return_value=({'type': 'async', 'operation': operation}, None)):
                with self.assertRaises(Error):self.client.write('test-config', self.item, '"one"')
        with patch.object(self.client, 'request', side_effect=[({'type':'async','operation':'/1.0/operations/x'},None),
                                                             ({'type':'sync','status_code':200,'metadata':{'status_code':True}},None)]):
            with self.assertRaises(Error):self.client.write('test-config', self.item, '"one"')

    def test_socket_failure_does_not_fallback_or_escalate_privilege(self):
        self.client.socket += '-absent'
        with self.assertRaises(Error):self.client.read('test-config')

    def test_local_socket_overrides_and_snap_user_fallback(self):
        with patch.dict(os.environ, {'LXD_SOCKET':'/chosen/socket','LXD_DIR':'/other'}, clear=True):
            self.assertEqual(local_socket('/snap/bin/lxc'), '/chosen/socket')
        with patch.dict(os.environ, {'LXD_DIR':'/chosen'}, clear=True):
            self.assertEqual(local_socket('/snap/bin/lxc'), '/chosen/unix.socket')
        with patch.dict(os.environ, {}, clear=True), patch('mas.lxd_config.os.access', side_effect=lambda path, mode: 'lxd-user' in path):
            self.assertEqual(local_socket('/snap/bin/lxc'), '/var/snap/lxd/common/lxd-user/unix.socket')
            self.assertEqual(local_socket('/usr/bin/lxc'), '/var/lib/lxd/unix.socket')
