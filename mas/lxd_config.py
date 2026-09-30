"""Conditional instance configuration through LXD's local REST API.

GET/PUT use the server's ETag, never an unconditional write or automatic retry.
Only this transport is needed beyond lxc: its noninteractive edit has no ETag.
"""
import http.client
import json
import os
from pathlib import Path
import re
import socket
import time
from urllib.parse import quote, urlencode

from .core import Error, validate_target
from .i18n import t
from .diagnostics import notify


def local_socket(executable):
    """Match native LXD client overrides and the snap wrapper's user fallback."""
    if os.environ.get('LXD_SOCKET'):
        return os.environ['LXD_SOCKET']
    if os.environ.get('LXD_DIR'):
        return str(Path(os.environ['LXD_DIR']) / 'unix.socket')
    main = '/var/snap/lxd/common/lxd/unix.socket'
    if str(executable).startswith('/snap/'):
        user = '/var/snap/lxd/common/lxd-user/unix.socket'
        return user if not os.access(main, os.W_OK) and os.access(user, os.W_OK) else main
    return main if os.access(main, os.W_OK) else '/var/lib/lxd/unix.socket'


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__('unix.socket', timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class Configuration:
    def __init__(self, lxd):
        self.lxd = lxd
        self.socket = local_socket(lxd.prefix[0])

    def endpoint(self, path):
        return path + '?' + urlencode({'project': self.lxd.project})

    def request(self, method, endpoint, data=None, etag=None, timeout=None):
        connection = UnixHTTPConnection(self.socket, timeout or self.lxd.timeout)
        headers = {'Content-Type': 'application/json'}
        if etag is not None:
            headers['If-Match'] = etag
        try:
            connection.request(method, endpoint, json.dumps(data) if data is not None else None, headers)
            response = connection.getresponse()
            raw = response.read()
            if response.status == 412:
                raise Error(t('lxd_config_changed'))
            try:
                body = json.loads(raw)
                if not isinstance(body, dict):
                    raise ValueError()
            except (ValueError, UnicodeError) as exc:
                raise Error(t('lxd_invalid_data')) from exc
            if response.status >= 400 or body.get('type') == 'error':
                raise Error(body.get('error') or t('lxd_failed'))
            return body, response.getheader('ETag')
        except TimeoutError as exc:
            raise Error(t('lxd_query_timeout')) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise Error(t('lxd_api_error', error=exc)) from exc
        finally:
            connection.close()

    def read(self, target):
        validate_target(target)
        body, etag = self.request('GET', self.endpoint('/1.0/instances/' + quote(target, safe='')))
        item = body.get('metadata')
        if (body.get('type') != 'sync' or body.get('status_code') != 200
                or not isinstance(item, dict) or not isinstance(item.get('config'), dict)
                or not isinstance(item.get('devices'), dict)):
            raise Error(t('lxd_invalid_data'))
        self.check_etag(etag)
        return item, etag

    @staticmethod
    def check_etag(etag):
        if not isinstance(etag, str) or not re.fullmatch(r'"[^"\r\n]+"', etag):
            raise Error(t('lxd_config_etag'))

    def write(self, target, item, etag, on_wait=None):
        validate_target(target)
        self.check_etag(etag)
        # InstancePut fields only; preserve saved state as well as other settings.
        writable = {key: item[key] for key in
                    ('architecture', 'config', 'devices', 'ephemeral', 'profiles', 'stateful', 'description')
                    if key in item}
        started = time.monotonic()
        deadline = started + self.lxd.timeout
        body, _ = self.request('PUT', self.endpoint('/1.0/instances/' + quote(target, safe='')), writable, etag)
        operation = body.get('operation')
        if (body.get('type') != 'async' or not isinstance(operation, str)
                or not re.fullmatch(r'/1.0/operations/[A-Za-z0-9-]+', operation)):
            raise Error(t('lxd_invalid_data'))
        while True:
            tick = time.monotonic()
            remaining = deadline - tick
            if remaining <= 0:
                raise Error(t('lxd_config_timeout'))
            response, _ = self.request('GET', self.endpoint(operation), timeout=remaining)
            result = response.get('metadata')
            if (response.get('type') != 'sync' or response.get('status_code') != 200
                    or not isinstance(result, dict) or type(result.get('status_code')) is not int):
                raise Error(t('lxd_invalid_data'))
            code = result['status_code']
            if code == 200:
                return
            if code >= 200:
                raise Error(result.get('err') or t('lxd_failed'))
            if on_wait:
                notify(on_wait, time.monotonic() - started)
            time.sleep(max(0, min(1 - (time.monotonic() - tick), deadline - time.monotonic())))
