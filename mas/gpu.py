"""Owned GPU access, independent of UI and container lifecycle orchestration.

One atomic LXD configuration edit publishes devices and their ownership record.
WSL uses native device primitives because LXD 6.9 snap CDI selects NVML there.
"""
import json
import re
from pathlib import Path
import shutil
import shlex
import subprocess
import time
import tempfile
from urllib.parse import quote, urlencode

from .core import Error
from .i18n import t
from .diagnostics import emit_native, failure_text

KEY = 'user.mas.gpu'
CONF = '/etc/ld.so.conf.d/mas-gpu.conf'
CONTENT = '# Managed by my-ai-sandbox GPU module\n/usr/lib/wsl/lib\n'
PROFILE = '/etc/profile.d/mas-gpu.sh'
PROFILE_CONTENT = '# Managed by my-ai-sandbox GPU module\nexport PATH="/usr/lib/wsl/lib:$PATH"\n'
RUNTIME_FILES = {CONF: CONTENT, PROFILE: PROFILE_CONTENT}
CTK = '/snap/lxd/current/bin/nvidia-ctk'


def _discovery_command(command, diagnostic=None, *, defer_diagnostics=False):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as exc:
        raise Error(t('gpu_detect_timeout')) from exc
    except OSError as exc:
        raise Error(t('gpu_detect_failed', error=str(exc))) from exc
    if result.returncode == 0 and not defer_diagnostics:
        _emit_discovery(result.stderr, diagnostic)
    return result


def _emit_discovery(stderr, diagnostic=None, *, hide_multiple=False):
    # Native informational discovery logs are transient implementation detail;
    # retain warnings and any unrecognized diagnostics without translating.
    lines = [line for line in stderr.splitlines()
             if not re.search(r'(?:^|\s)level=(?:info|debug|trace)(?:\s|$)', line)]
    if hide_multiple:
        lines = [line for line in lines if not re.fullmatch(
            r'time="[^"]+" level=warning msg="Found multiple driver store paths: \[[^\r\n\"]+\]"', line)]
    emit_native('\n'.join(lines), diagnostic)


def valid_driver_directory(path):
    return (isinstance(path, str) and bool(re.fullmatch(r'/usr/lib/wsl/drivers/[A-Za-z0-9_.-]+', path))
            and Path(path).name not in ('.', '..'))


def wsl_driver_paths(diagnostic=None, *, keep_known_warnings=False):
    """Use NVIDIA's DXCore-backed discovery, never guess from directory names."""
    if not Path(CTK).is_file():
        raise Error(t('gpu_discovery_tool_missing', path=CTK))
    result = _discovery_command([CTK, 'cdi', 'generate', '--mode=wsl', '--format=json', '--output', '',
                                '--disable-hook=all', '--nvidia-cdi-hook-path=' + CTK,
                                '--feature-flag=disable-nvsandboxutils',
                                '--library-search-path=/usr/lib/wsl/lib'], diagnostic, defer_diagnostics=True)
    if result.returncode:
        raise Error(t('gpu_detect_failed', error=failure_text(result.stdout, result.stderr)))
    validated = False
    try:
        spec = json.loads(result.stdout)
        if not isinstance(spec, dict) or spec['kind'] != 'nvidia.com/gpu' or not isinstance(spec['devices'], list):
            raise ValueError()
        selected = [d for d in spec['devices'] if d['name'] == 'all']
        if len(selected) != 1:
            raise ValueError()
        paths = set()
        for edits in (spec.get('containerEdits', {}), selected[0].get('containerEdits', {})):
            mounts = edits.get('mounts', [])
            if not isinstance(mounts, list):
                raise ValueError()
            for mount in mounts:
                source = mount['hostPath']
                if not isinstance(source, str):
                    raise ValueError()
                if source.rsplit('/', 1)[-1] != 'libcuda.so.1.1':
                    continue
                if (not valid_driver_directory(source.rsplit('/', 1)[0])
                        or mount.get('containerPath') != source
                        or not isinstance(mount.get('options'), list)
                        or any(not isinstance(option, str) for option in mount['options'])
                        or 'ro' not in mount['options']
                        or not Path(source).is_file()
                        or str(Path(source).resolve(strict=True)) != source):
                    raise ValueError()
                paths.add(str(Path(source).parent))
        if not paths:
            raise ValueError()
        validated = True
        return sorted(paths)
    except (ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError) as exc:
        raise Error(t('gpu_discovery_invalid')) from exc
    finally:
        _emit_discovery(result.stderr, diagnostic, hide_multiple=validated and not keep_known_warnings)


def detect(diagnostic=None, *, keep_known_warnings=False):
    """Report NVIDIA discrete compute GPUs; no packages or configuration changes."""
    wsl = Path('/dev/dxg').exists()
    executable = '/usr/lib/wsl/lib/nvidia-smi' if wsl else shutil.which('nvidia-smi')
    if not executable or not Path(executable).is_file():
        return {'available': False, 'backend': None, 'gpus': []}
    result = _discovery_command([executable, '--query-gpu=name,uuid', '--format=csv,noheader'], diagnostic)
    if result.returncode == 6:
        return {'available': False, 'backend': None, 'gpus': []}
    if result.returncode:
        raise Error(t('gpu_detect_failed', error=failure_text(result.stdout, result.stderr)))
    gpus = []
    for line in result.stdout.splitlines():
        name, separator, identity = line.partition(',')
        if separator and identity.strip().startswith('GPU-'):
            gpus.append({'name': name.strip(), 'uuid': identity.strip()})
    if not gpus:
        raise Error(t('gpu_detect_failed', error=result.stdout.strip()))
    if wsl and not all(Path(p).is_dir() for p in ('/usr/lib/wsl/lib', '/usr/lib/wsl/drivers')):
        raise Error(t('gpu_runtime_missing'))
    driver_paths = wsl_driver_paths(diagnostic, keep_known_warnings=keep_known_warnings) if wsl else []
    return {'available': True, 'backend': 'wsl-nvidia' if wsl else 'nvidia-cdi', 'gpus': gpus, 'driver_paths': driver_paths}


def devices(backend, driver_paths=()):
    if backend == 'wsl-nvidia':
        result = {
            'mas-gpu-dxg': {'type': 'unix-char', 'source': '/dev/dxg', 'path': '/dev/dxg', 'mode': '0666'},
            'mas-gpu-lib': {'type': 'disk', 'source': '/usr/lib/wsl/lib', 'path': '/usr/lib/wsl/lib', 'readonly': 'true'},
        }
        for index, path in enumerate(driver_paths):
            result['mas-gpu-driver-' + str(index)] = {'type': 'disk', 'source': path, 'path': path, 'readonly': 'true'}
        return result
    if backend == 'nvidia-cdi':
        return {'mas-gpu': {'type': 'gpu', 'gputype': 'physical', 'id': 'nvidia.com/gpu=all'}}
    raise Error(t('gpu_record_invalid'))


class GPU:
    def __init__(self, manager):
        self.manager = manager
        self.lxd = manager.lxd
        self.keep_known_warnings = False

    def detect(self):
        return detect(diagnostic=self.lxd.diagnostic, keep_known_warnings=self.keep_known_warnings)

    def record(self, instance):
        raw = instance['config'].get(KEY)
        if raw is None:
            return None
        try:
            item = json.loads(raw)
            if not isinstance(item, dict):
                raise ValueError()
            paths = item.get('driver_paths')
            if (not isinstance(paths, list) or any(not valid_driver_directory(p) for p in paths)
                    or len(paths) != len(set(paths))
                    or (item.get('backend') == 'wsl-nvidia' and not paths)
                    or (item.get('backend') == 'nvidia-cdi' and paths)):
                raise ValueError()
            if (type(item.get('version')) is not int or item['version'] != 1
                    or type(item.get('enabled')) is not bool
                    or item.get('backend') not in ('wsl-nvidia', 'nvidia-cdi')
                    or item.get('devices') != (devices(item['backend'], paths) if item['enabled'] else {})
                    or item.get('runtime_profile') not in (None, PROFILE if item['enabled'] and item['backend'] == 'wsl-nvidia' else None)
                    or item.get('runtime_file') != (CONF if item['enabled'] and item['backend'] == 'wsl-nvidia' else None)):
                raise ValueError()
            return item
        except (ValueError, TypeError, KeyError) as exc:
            raise Error(t('gpu_record_invalid')) from exc

    def check_owned(self, instance, record):
        owned = record['devices'] if record else {}
        local = instance.get('devices', {})
        expanded = instance.get('expanded_devices', local)
        for name, definition in owned.items():
            if local.get(name) != definition or expanded.get(name) != definition:
                raise Error(t('gpu_conflict', device=name))
        for name, definition in expanded.items():
            if name in owned:
                continue
            path = definition.get('path', '')
            source = definition.get('source', '')
            if (name.startswith('mas-gpu') or definition.get('type') == 'gpu'
                    or path == '/dev/dxg' or source == '/dev/dxg'
                    or path in RUNTIME_FILES or path in ('/etc/ld.so.conf.d', '/etc/profile.d')
                    or path == '/etc'
                    or path == '/usr' or path == '/usr/lib'
                    or path == '/usr/lib/wsl' or path.startswith('/usr/lib/wsl/')
                    or source.startswith('/usr/lib/wsl/')):
                raise Error(t('gpu_conflict', device=name))

    def status(self, target, *, capability=None):
        instance = self.manager.require(target)
        record = self.record(instance)
        self.check_owned(instance, record)
        capability = self.detect() if capability is None else capability
        return {**capability, 'enabled': record['enabled'] if record else capability['available'],
                'configured': record is not None, 'resources': record or {},
                'state': instance['status']}

    def _runtime_file(self, target, path=CONF):
        endpoint = '/1.0/instances/' + quote(target, safe='') + '/files?' + urlencode(
            {'project': self.lxd.project, 'path': path.rsplit('/', 1)[0]})
        raw = self.lxd.command(['query', endpoint])
        try:
            entries = json.loads(raw)
        except ValueError as exc:
            raise Error(t('gpu_runtime_query', path=path)) from exc
        if not isinstance(entries, list) or any(not isinstance(name, str) for name in entries):
            raise Error(t('gpu_runtime_query', path=path))
        if path.rsplit('/', 1)[1] not in entries:
            return None
        # Pull preserves the native file type. Never follow a guest symlink on the host.
        with tempfile.TemporaryDirectory(prefix='mas-gpu-file-') as directory:
            local = Path(directory) / 'runtime'
            self.lxd.command(['file', 'pull', 'local:' + target + path, str(local)])
            if local.is_symlink() or not local.is_file():
                raise Error(t('gpu_runtime_conflict', path=path))
            content = local.read_bytes()
        if content != RUNTIME_FILES[path].encode('utf-8'):
            raise Error(t('gpu_runtime_conflict', path=path))
        return RUNTIME_FILES[path]

    def set(self, target, enabled, *, capability=None):
        if type(enabled) is not bool:
            raise ValueError('enabled must be bool')
        with self.manager.filesystems.locked():
            instance = self.manager.require(target, stopped=True)
            identity = instance['config'].get('volatile.uuid')
            def same_instance(item=None):
                item = self.manager.require(target, stopped=True) if item is None else item
                if not isinstance(identity, str) or not identity or item['config'].get('volatile.uuid') != identity:
                    raise Error(t('gpu_identity_changed', target=target))
                return item
            same_instance(instance)
            record = self.record(instance)
            self.check_owned(instance, record)
            capability = capability or ({'available': False, 'backend': record['backend']} if not enabled and record else self.detect())
            if enabled and not capability['available']:
                raise Error(t('gpu_unavailable'))
            if not capability['available'] and record is None:
                raise Error(t('gpu_unavailable'))
            backend = capability['backend'] if enabled else (record['backend'] if record else capability['backend'])
            if record and record['enabled'] and record['backend'] != backend:
                raise Error(t('gpu_backend_changed'))
            # Validate/remove only our exact internal loader file. A failed removal
            # leaves the old ownership record intact and can safely be retried.
            if backend == 'wsl-nvidia' or (record and record['enabled'] and record['backend'] == 'wsl-nvidia'):
                # Check every file before removing any; module owns exact fixed content.
                existing = {path: self._runtime_file(target, path) for path in RUNTIME_FILES}
                if not enabled:
                    for path, content in existing.items():
                        if content is None:
                            continue
                        same_instance()
                        self.lxd.command(['file', 'delete', 'local:' + target + path])
                        deadline = time.monotonic() + self.lxd.timeout
                        while self._runtime_file(target, path) is not None:
                            same_instance()
                            if time.monotonic() >= deadline:
                                raise Error(t('gpu_wait_failed'))
                            time.sleep(1)
            driver_paths = capability.get('driver_paths', []) if enabled else (record['driver_paths'] if record else capability.get('driver_paths', []))
            definition = devices(backend, driver_paths) if enabled else {}
            desired = {'version': 1, 'enabled': enabled, 'backend': backend, 'driver_paths': driver_paths,
                       'devices': definition, 'runtime_file': CONF if enabled and backend == 'wsl-nvidia' else None,
                       'runtime_profile': PROFILE if enabled and backend == 'wsl-nvidia' else None}
            current, etag = self.lxd.configuration.read(target)
            same_instance(current)
            # Recheck immediately before publication, including expanded profile devices.
            instance = same_instance()
            if self.record(instance) != record or self.record(current) != record:
                raise Error(t('gpu_record_changed'))
            self.check_owned(instance, record)
            expanded = dict(current.get('expanded_devices', current['devices']))
            for name in (record or {}).get('devices', {}):
                current['devices'].pop(name)
                expanded.pop(name, None)
            current['devices'].update(definition)
            expanded.update(definition)
            current['expanded_devices'] = expanded
            current['config'][KEY] = json.dumps(desired, sort_keys=True)
            current['expanded_config'] = {**current.get('expanded_config', {}), **current['config']}
            if enabled:
                self.manager.isolation.allow_gpu(capability)
            self.manager.isolation.audit(current)
            start = time.monotonic()
            self.lxd.configuration.write(target, current, etag,
                on_wait=lambda elapsed: self.manager.emit(dict(action='gpu', target=target,
                    status='waiting', observation='not yet observed', elapsed=elapsed)))
            while True:
                observed = same_instance()
                self.check_owned(observed, self.record(observed))
                elapsed = time.monotonic() - start
                matches = self.record(observed) == desired
                self.manager.emit(dict(action='gpu', target=target, status='ok' if matches else 'waiting',
                                       observation='enabled' if enabled else 'disabled', elapsed=elapsed))
                if matches:
                    return desired
                if elapsed >= self.lxd.timeout:
                    raise Error(t('gpu_wait_failed'))
                time.sleep(1)

    def ensure(self, target):
        """Default access on stopped new/legacy containers; explicit off persists."""
        instance = self.manager.require(target)
        record = self.record(instance)
        if record is not None:
            self.check_owned(instance, record)
            if record['enabled']:
                capability = self.detect()
                if not capability['available'] or capability['backend'] != record['backend']:
                    raise Error(t('gpu_unavailable'))
                if (capability.get('driver_paths', []) != record['driver_paths']
                        or record['backend'] == 'wsl-nvidia' and record.get('runtime_profile') != PROFILE):
                    self.set(target, True, capability=capability)
            return
        capability = self.detect()
        if capability['available']:
            self.set(target, True, capability=capability)

    def prepare(self, target):
        """Required internal GPU runtime preparation, after native start."""
        instance = self.manager.require(target)
        record = self.record(instance)
        if not record or record['backend'] != 'wsl-nvidia':
            return
        self.check_owned(instance, record)
        # Validate both files before writing either. All paths/content are constants.
        script = 'set -eu\n'
        if record['enabled']:
            for path, content in RUNTIME_FILES.items():
                script += 'p=' + shlex.quote(path) + '\nexpected=' + shlex.quote(content.rstrip('\n')) + '\n'
                message = shlex.quote(t('gpu_runtime_conflict', path=path))
                script += ('if [ -L "$p" ] || { [ -e "$p" ] && { [ ! -f "$p" ] || '
                           '[ "$(cat "$p")" != "$expected" ]; }; }; then echo ' + message + ' >&2; exit 1; fi\n')
            for path, content in RUNTIME_FILES.items():
                script += "printf '%s\\n' " + shlex.quote(content.rstrip('\n')) + ' > ' + shlex.quote(path) + '\n'
                script += 'chmod 0644 ' + shlex.quote(path) + '\n'
            script += 'test -c /dev/dxg\ntest -r /usr/lib/wsl/lib/libcuda.so.1\n'
        script += 'ldconfig\n'
        self.manager._run_lxd_until_state('gpu-runtime', target,
            ['exec', 'local:' + target, '--', '/bin/sh', '-c', script], 'Running')
