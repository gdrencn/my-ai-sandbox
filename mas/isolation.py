"""LXD-managed policy: provisioning, observation and exact resource approval.

No guest workload policy, kernel sandbox or implicit repair of unknown settings.
The same module provisions production and uniquely scoped test projects.
"""
import json
import re
from urllib.parse import quote

from .core import Error, LXD, MANAGED
from .i18n import t

PROJECT = 'mas'
PROFILE = 'mas'
KEY = 'user.mas.policy'
PROFILE_KEY = 'user.mas.profile'
BASE_CONFIG = {
    'security.privileged': 'false', 'security.idmap.isolated': 'true',
    'security.nesting': 'false', 'security.syscalls.deny_default': 'true',
    'security.devlxd.management.volumes': 'false',
}
BASE_PROJECT = {
    'features.profiles': 'true', 'features.storage.volumes': 'true',
    'features.networks': 'false', 'features.images': 'false', 'restricted': 'true',
    'restricted.containers.privilege': 'isolated',
    'restricted.containers.lowlevel': 'block',
    'restricted.containers.nesting': 'block',
    'restricted.containers.interception': 'block',
    'restricted.backups': 'allow', 'restricted.devices.nic': 'managed',
    **{'restricted.devices.' + kind: 'block' for kind in
       ('unix-block', 'unix-hotplug', 'usb', 'pci', 'infiniband', 'proxy')},
}
UNSET_PROJECT = ('restricted.idmap.uid', 'restricted.idmap.gid')
UNSET_CONFIG = ('raw.idmap', 'raw.lxc', 'raw.apparmor', 'raw.seccomp',
                'security.syscalls.allow',
                'linux.kernel_modules', 'linux.kernel_modules.load',
                'security.idmap.base', 'security.idmap.size', 'security.devlxd.images')


def policy_error(differences):
    raise Error(t('policy_refused', differences='\n'.join('• ' + item for item in differences)))


class Isolation:
    def __init__(self, manager):
        self.manager = manager
        self.lxd = manager.lxd
        self.api = self.lxd.configuration
        self.created = False

    def resource(self, kind, name):
        path = '/1.0/' + kind + '/' + quote(name, safe='')
        endpoint = path if kind == 'projects' else self.api.endpoint(path)
        body, etag = self.api.request('GET', endpoint)
        item = body.get('metadata')
        if (body.get('type') != 'sync' or body.get('status_code') != 200
                or not isinstance(item, dict) or not isinstance(item.get('config'), dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in item['config'].items())):
            raise Error(t('lxd_invalid_data'))
        self.api.check_etag(etag)
        return item, etag, endpoint

    @staticmethod
    def record(project):
        from .gpu import valid_driver_directory
        try:
            value = json.loads(project['config'][KEY])
            if (not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1
                    or not isinstance(value.get('pool'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value['pool'])
                    or not isinstance(value.get('network'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value['network'])
                    or not isinstance(value.get('backends'), list)
                    or any(b not in ('wsl-nvidia', 'nvidia-cdi') for b in value['backends'])
                    or len(set(value['backends'])) != len(value['backends'])
                    or not isinstance(value.get('driver_paths'), list)
                    or any(not valid_driver_directory(p) for p in value['driver_paths'])
                    or len(set(value['driver_paths'])) != len(value['driver_paths'])
                    or bool(value['driver_paths']) != ('wsl-nvidia' in value['backends'])):
                raise ValueError()
            return value
        except (KeyError, ValueError, TypeError):
            raise Error(t('policy_record_invalid')) from None

    @staticmethod
    def devices(record):
        return {'root': {'type': 'disk', 'path': '/', 'pool': record['pool']},
                'eth0': {'type': 'nic', 'name': 'eth0', 'network': record['network']}}

    @staticmethod
    def project_config(record):
        wsl = 'wsl-nvidia' in record['backends']
        result = {**BASE_PROJECT, 'restricted.networks.access': record['network'],
                  'restricted.devices.disk': 'allow' if wsl else 'block',
                  'restricted.devices.unix-char': 'allow' if wsl else 'block',
                  'restricted.devices.gpu': 'allow' if 'nvidia-cdi' in record['backends'] else 'block',
                  KEY: json.dumps(record, sort_keys=True)}
        if wsl:
            result['restricted.devices.disk.paths'] = ','.join(['/usr/lib/wsl/lib', *record['driver_paths']])
        return result

    def provision(self):
        """Create owned resources; an existing project is verified, never repaired."""
        host = LXD(timeout=self.lxd.timeout, diagnostic=self.lxd.diagnostic)
        projects = self.list_objects(host, ['project', 'list', 'local:', '--format=json'])
        if any(p['name'] == self.lxd.project for p in projects):
            self.check()
            capability = self.manager.gpu.detect()
            if capability['available']:
                self.allow_gpu(capability)
            return self.check()
        profiles = self.list_objects(host, ['profile', 'list', 'local:', '--format=json'])
        source = next((p for p in profiles if p.get('name') == 'default'), None)
        if not isinstance(source, dict) or not isinstance(source.get('devices'), dict):
            raise Error(t('profile_missing'))
        if any(not isinstance(d, dict) for d in source['devices'].values()):
            raise Error(t('lxd_invalid_data'))
        roots = [d for d in source['devices'].values() if d.get('type') == 'disk' and d.get('path') == '/']
        nics = [d for d in source['devices'].values() if d.get('type') == 'nic']
        if len(roots) != 1 or not roots[0].get('pool') or roots[0].get('source') or len(nics) != 1:
            raise Error(t('policy_source_resources'))
        network = nics[0].get('network') or nics[0].get('parent')
        if not network:
            raise Error(t('policy_source_resources'))
        record = {'version': 1, 'pool': roots[0]['pool'], 'network': network, 'backends': [], 'driver_paths': []}
        self.record({'config': {KEY: json.dumps(record)}})
        self.check_network(record)
        self.create(record)
        self.check()
        capability = self.manager.gpu.detect()
        if capability['available']:
            self.allow_gpu(capability)
        return self.check()

    def create(self, record, *, profile_extra=None, project_extra=None):
        """Provision a fresh owned project; callers define its approved purpose."""
        self.record({'config': {KEY: json.dumps(record)}})
        body, _ = self.api.request('POST', '/1.0/projects',
            {'name': self.lxd.project, 'description': 'my-ai-sandbox managed isolation',
             'config': {'features.profiles': 'true', 'features.storage.volumes': 'true',
                        'features.images': 'false', 'features.networks': 'false',
                        KEY: json.dumps(record, sort_keys=True), **(project_extra or {})}})
        self.sync_result(body)
        self.created = True
        # LXD generates an empty project-local default profile. Configure it with
        # the same baseline for compatible native backups; do not touch host default.
        default, etag, endpoint = self.resource('profiles', 'default')
        if default.get('config') or default.get('devices'):
            policy_error([t('policy_profile_changed', name='default')])
        payload = {'description': 'my-ai-sandbox managed isolation',
                   'config': {**BASE_CONFIG, PROFILE_KEY: '1', **(profile_extra or {})}, 'devices': self.devices(record)}
        self.api.update(endpoint, payload, etag)
        body, _ = self.api.request('POST', self.api.endpoint('/1.0/profiles'), {'name': PROFILE, **payload})
        self.sync_result(body)
        project, etag, endpoint = self.resource('projects', self.lxd.project)
        config = {**project['config'], **self.project_config(record)}
        self.api.update(endpoint, {'description': project.get('description', ''), 'config': config}, etag)

    @staticmethod
    def sync_result(body):
        if body.get('type') != 'sync' or body.get('status_code') != 200:
            raise Error(t('lxd_invalid_data'))

    @staticmethod
    def list_objects(client, args):
        try:
            items = json.loads(client.command(args))
            if not isinstance(items, list) or any(not isinstance(i, dict) or not isinstance(i.get('name'), str) for i in items):
                raise ValueError()
            return items
        except (ValueError, TypeError):
            raise Error(t('lxd_invalid_data')) from None

    def check_network(self, record):
        host = LXD(timeout=self.lxd.timeout, diagnostic=self.lxd.diagnostic)
        networks = self.list_objects(host, ['network', 'list', 'local:', '--format=json'])
        if (not isinstance(networks, list) or any(not isinstance(n, dict) for n in networks)
                or not any(n.get('name') == record['network'] and n.get('managed') is True
                           and n.get('type') == 'bridge' for n in networks)):
            raise Error(t('policy_source_resources'))

    def check(self):
        project, _, _ = self.resource('projects', self.lxd.project)
        record = self.record(project)
        expected = self.project_config(record)
        differences = [key + ' = ' + repr(project['config'].get(key)) for key, value in expected.items()
                       if project['config'].get(key) != value]
        differences += [t('policy_unset', key=key) for key in UNSET_PROJECT if key in project['config']]
        if 'wsl-nvidia' not in record['backends'] and 'restricted.devices.disk.paths' in project['config']:
            differences.append(t('policy_unset', key='restricted.devices.disk.paths'))
        for name in (PROFILE, 'default'):
            profile, _, _ = self.resource('profiles', name)
            profile_config = {**BASE_CONFIG, PROFILE_KEY: '1'}
            for key in sorted(set(profile['config']) | set(profile_config)):
                if profile['config'].get(key) != profile_config.get(key):
                    differences.append(t('policy_profile_difference', name=name, key=key,
                        actual=repr(profile['config'].get(key)), expected=repr(profile_config.get(key))))
            if profile.get('devices') != self.devices(record):
                differences.append(t('policy_profile_devices', name=name))
        if differences:
            policy_error(differences)
        self.check_network(record)
        return record

    def allow_gpu(self, capability):
        """Authorize only the existing GPU module's validated discovery result."""
        record = self.check()
        backend = capability.get('backend')
        paths = capability.get('driver_paths', [])
        from .gpu import valid_driver_directory
        if (capability.get('available') is not True or backend not in ('wsl-nvidia', 'nvidia-cdi')
                or not isinstance(paths, list) or any(not valid_driver_directory(p) for p in paths)
                or (backend == 'wsl-nvidia' and not paths) or (backend == 'nvidia-cdi' and paths)):
            raise Error(t('gpu_unavailable'))
        updated = {**record, 'backends': sorted(set(record['backends']) | {backend}),
                   'driver_paths': sorted(set(record['driver_paths']) | set(paths))}
        if updated == record:
            return
        project, etag, endpoint = self.resource('projects', self.lxd.project)
        if (self.record(project) != record
                or any(project['config'].get(k) != v for k, v in self.project_config(record).items())
                or any(k in project['config'] for k in UNSET_PROJECT)):
            raise Error(t('lxd_config_changed'))
        self.api.update(endpoint, {'description': project.get('description', ''),
                                  'config': {**project['config'], **self.project_config(updated)}}, etag)
        if self.check() != updated:
            raise Error(t('lxd_config_changed'))

    def audit(self, instance, *, legacy=False, record=None):
        """Observe only. Legacy validation permits absent isolated mapping before migration."""
        record = record or self.check()
        if not isinstance(instance, dict):
            raise Error(t('lxd_invalid_data'))
        config = instance.get('expanded_config')
        devices = instance.get('expanded_devices')
        if (instance.get('type') != 'container' or not isinstance(instance.get('config'), dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in instance['config'].items())
                or not isinstance(config, dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in config.items())
                or not isinstance(devices, dict) or any(not isinstance(n, str) or not isinstance(d, dict)
                    or any(not isinstance(k, str) or not isinstance(v, str) for k, v in d.items())
                    for n, d in devices.items())):
            raise Error(t('lxd_invalid_data'))
        defaults = {'security.privileged': 'false', 'security.idmap.isolated': 'false',
                    'security.nesting': 'false', 'security.syscalls.deny_default': 'true',
                    'security.devlxd.management.volumes': 'false'}
        differences = []
        for key, value in BASE_CONFIG.items():
            if legacy and key == 'security.idmap.isolated' and key not in instance.get('config', {}):
                continue
            actual = config.get(key, defaults[key]).lower()
            if actual != value:
                differences.append(key + ' = ' + repr(actual))
        differences += [t('policy_unset', key=key) for key in config
                        if key in UNSET_CONFIG or key.startswith('security.delegate_bpf')
                        or key.startswith('security.syscalls.intercept') and config[key].lower() not in ('false', '0', 'no', 'off', '')]
        if not legacy and instance.get('profiles') not in ([PROFILE], ['default']):
            differences.append('profiles = ' + repr(instance.get('profiles')))
        gpu_record = self.manager.gpu.record(instance)
        self.manager.gpu.check_owned(instance, gpu_record)
        if gpu_record and gpu_record['enabled']:
            if (gpu_record['backend'] not in record['backends']
                    or not set(gpu_record['driver_paths']).issubset(record['driver_paths'])):
                differences.append(t('policy_gpu_resources'))
        gpu_devices = (gpu_record or {}).get('devices', {})
        roots = nics = 0
        for name, definition in devices.items():
            if name in gpu_devices:
                continue
            kind = definition.get('type')
            if kind == 'none' and set(definition) == {'type'}:
                continue
            if kind == 'disk' and definition.get('path') == '/':
                roots += 1
                if (definition.get('pool') != record['pool'] or definition.get('source')
                        or set(definition) - {'type', 'path', 'pool', 'size'}):
                    differences.append(t('policy_device', name=name, definition=repr(definition)))
            elif kind == 'nic':
                nics += 1
                approved = (definition.get('network') == record['network'] and
                            not set(definition) - {'type', 'network', 'name', 'hwaddr'})
                if legacy:
                    approved |= (definition.get('nictype') == 'bridged' and definition.get('parent') == record['network']
                                 and not set(definition) - {'type', 'nictype', 'parent', 'name', 'hwaddr'})
                if (not approved or definition.get('name') != 'eth0'
                        or 'hwaddr' in definition and not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', definition['hwaddr'])):
                    differences.append(t('policy_device', name=name, definition=repr(definition)))
            else:
                differences.append(t('policy_device', name=name, definition=repr(definition)))
        if roots != 1 or nics != 1:
            differences.append(t('policy_root_nic_count'))
        if differences:
            policy_error(differences)
        return instance
