"""Per-container LXD NIC switching, with conditional writes and exact approval."""
import json
import re
import time

from .core import Error, MANAGED
from .i18n import t

KEY = 'user.mas.network'
MASK = {'type': 'none'}
MAC = re.compile(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}')


def record(instance):
    raw = instance.get('config', {}).get(KEY)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
        nic = value['restore']
        if (set(value) != {'version', 'enabled', 'restore'}
                or type(value['version']) is not int or value['version'] != 1
                or type(value['enabled']) is not bool or not isinstance(nic, dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in nic.items())
                or nic.get('type') != 'nic' or nic.get('name') != 'eth0'
                or not nic.get('network') or set(nic) - {'type', 'name', 'network', 'hwaddr'}
                or 'hwaddr' in nic and not MAC.fullmatch(nic['hwaddr'])):
            raise ValueError()
        return value
    except (ValueError, TypeError, KeyError):
        raise Error(t('network_record_invalid')) from None


def enabled(instance):
    saved = record(instance)
    return saved['enabled'] if saved else True


def check_owned(instance, saved, policy):
    if saved is None:
        return
    expected = saved['restore'] if saved['enabled'] else MASK
    expanded = instance.get('expanded_devices', {})
    if (saved['restore']['network'] != policy['network']
            or instance.get('devices', {}).get('eth0') != expected
            or expanded.get('eth0', MASK) != expected):
        raise Error(t('network_conflict'))


class Network:
    def __init__(self, manager):
        self.manager = manager

    def status(self, target):
        item = self.manager.require(target)
        self.manager.isolation.audit(item)
        saved = record(item)
        return {'enabled': enabled(item), 'configured': saved is not None,
                'resources': saved}

    def set(self, target, requested):
        if type(requested) is not bool:
            raise Error(t('network_record_invalid'))
        started = time.monotonic()
        initial = self.manager.require(target, stopped=True)
        self.manager.isolation.audit(initial)
        identity = initial['config'].get('volatile.uuid')
        api = self.manager.lxd.configuration
        current, etag = api.read(target)
        if (not identity or current['config'].get('volatile.uuid') != identity
                or current.get('status') != 'Stopped' or current['config'].get(MANAGED) != 'true'):
            raise Error(t('network_changed'))
        self.manager.isolation.audit(current)
        if (current['config'].get(KEY) != initial['config'].get(KEY)
                or current['devices'] != initial['devices']):
            raise Error(t('network_changed'))
        saved = record(current)
        nic = dict(saved['restore'] if saved else current['expanded_devices'].get('eth0', {}))
        if nic.get('type') != 'nic' or nic.get('name') != 'eth0':
            raise Error(t('network_conflict'))
        hwaddr = current['config'].get('volatile.eth0.hwaddr')
        if 'hwaddr' not in nic and hwaddr:
            if not MAC.fullmatch(hwaddr):
                raise Error(t('network_conflict'))
            nic['hwaddr'] = hwaddr
        updated = {'version': 1, 'enabled': requested, 'restore': nic}
        current['config'] = {**current['config'], KEY: json.dumps(updated, sort_keys=True)}
        current['devices'] = {**current['devices'], 'eth0': nic if requested else dict(MASK)}
        api.write(target, current, etag, on_wait=lambda elapsed: self.manager.emit(
            dict(action='network', target=target, status='waiting', observation='Stopped', elapsed=elapsed)))
        observed = self.manager.require(target, stopped=True)
        if observed['config'].get('volatile.uuid') != identity or record(observed) != updated:
            raise Error(t('network_changed'))
        self.manager.isolation.audit(observed)
        self.manager._completed('network', target, 'Stopped', started)
        return updated
