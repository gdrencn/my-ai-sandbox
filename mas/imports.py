"""Native backup staging without relaxing the production project's policy."""
import json
import re
import uuid

from .core import Error, LXD, MANAGED, Manager
from .diagnostics import cleanup_scope
from .i18n import t
from .isolation import BASE_CONFIG, Isolation, PROFILE, PROFILE_KEY

KEY = 'user.mas.import'


class Imports:
    def __init__(self, manager):
        self.manager = manager

    def restore(self, target, path):
        policy = self.manager.isolation.check()
        owner = {'version': 1, 'id': uuid.uuid4().hex,
                 'destination': self.manager.lxd.project, 'target': target}
        owner['project'] = 'mas-import-' + owner['id']
        staging = Manager(LXD(project=owner['project'], timeout=self.manager.lxd.timeout,
                              diagnostic=self.manager.lxd.diagnostic), self.manager.report)
        created = False
        transferred = False
        def reclaim():
            if created and (transferred or staging.find(target) is None):
                try:
                    self.cleanup(self.manager, owner)
                except (Error, OSError) as exc:
                    raise Error(t('import_staging_preserved', target=target,
                                  project=owner['project'], error=exc)) from exc

        # The scope surrounds the operation, so cleanup cannot replace its
        # primary error or interrupt. Data from an unsuccessful import stays put.
        with cleanup_scope(reclaim, lambda exc: self.manager._cleanup_warning('import', target, exc)):
            try:
                try:
                    staging.isolation.create(policy, profile_extra={'boot.autostart': 'false'},
                                             project_extra={KEY: json.dumps(owner, sort_keys=True)})
                finally:
                    created = staging.isolation.created
                    if created:
                        self.manager.emit(dict(action='import', status='waiting', target=target,
                            observation='Absent', elapsed=0, phase='staging-created', owner=owner))
                item, etag, endpoint = staging.isolation.resource('projects', staging.lxd.project)
                staging.lxd.configuration.update(endpoint,
                    {'description': item.get('description', ''), 'config': {**item['config'],
                     'restricted.containers.lowlevel': 'allow'}}, etag)
                result = staging._run_lxd_until_state('import', target,
                    ['import', 'local:', str(path), target], 'Stopped', require_marker=False)
                if result.get('type') != 'container':
                    raise Error(t('import_not_container', target=target))
                # No guest command is executed. Prevent normal autostart and
                # remove a carried marker before auditing unverified backup data.
                result, etag = staging.lxd.configuration.read(target)
                original_autostart = result['config'].get('boot.autostart', '')
                result['config'].pop(MANAGED, None)
                result['config']['boot.autostart'] = 'false'
                staging.lxd.configuration.write(target, result, etag)
                self.manager.isolation.audit(staging.find(target))
                self.manager.absent(target)
                result = self.manager._run_lxd_until_state('copy-import', target,
                    ['copy', 'local:' + target, 'local:' + target,
                     '--target-project', self.manager.lxd.project, '--profile', PROFILE,
                     '--config', 'boot.autostart=' + original_autostart],
                    'Stopped', require_marker=False, client=staging.lxd)
                self.manager.isolation.audit(result)
                transferred = True
                return result
            except (Error, OSError) as exc:
                if created:
                    raise Error(t('import_staging_preserved', target=target,
                                  project=staging.lxd.project, error=exc)) from exc
                raise

    @staticmethod
    def cleanup(manager, owner):
        """Reclaim exactly a recorded staging resource; also reused by test cleanup."""
        if (not isinstance(owner, dict) or type(owner.get('version')) is not int or owner['version'] != 1
                or not isinstance(owner.get('id'), str) or not re.fullmatch('[0-9a-f]{32}', owner['id'])
                or owner.get('project') != 'mas-import-' + owner['id']
                or owner.get('destination') != manager.lxd.project):
            raise Error(t('import_staging_owner'))
        from .core import validate_target
        validate_target(owner.get('target', ''))
        staging = Manager(LXD(project=owner['project'], timeout=manager.lxd.timeout,
                              diagnostic=manager.lxd.diagnostic), manager.report)
        project, etag, endpoint = staging.isolation.resource('projects', owner['project'])
        if project['config'].get(KEY) != json.dumps(owner, sort_keys=True):
            raise Error(t('import_staging_owner'))
        # The project contains at most this import. Refuse unknown occupants.
        items = staging.lxd.instances()
        if any(i['name'] != owner['target'] or i['status'] != 'Stopped' for i in items):
            raise Error(t('import_staging_owner'))
        record = staging.isolation.record(project)
        profiles = Isolation.list_objects(staging.lxd, ['profile', 'list', 'local:', '--format=json'])
        if any(i['name'] not in (PROFILE, 'default') for i in profiles):
            raise Error(t('import_staging_owner'))
        owned_profile = None
        for item in profiles:
            name = item['name']
            profile, profile_etag, profile_endpoint = staging.isolation.resource('profiles', name)
            complete = (profile['config'] == {**BASE_CONFIG, PROFILE_KEY: '1', 'boot.autostart': 'false'}
                        and profile.get('devices') == staging.isolation.devices(record))
            fresh = name == 'default' and not profile['config'] and not profile.get('devices') and not items
            if not complete and not fresh:
                raise Error(t('import_staging_owner'))
            if name == PROFILE:
                owned_profile = (profile_etag, profile_endpoint)
        if items:
            staging._run_lxd_until_state('cleanup-delete', owner['target'],
                ['delete', 'local:' + owner['target']], 'Absent', require_marker=False)
        if owned_profile:
            profile_etag, profile_endpoint = owned_profile
            body, _ = staging.lxd.configuration.request('DELETE', profile_endpoint, etag=profile_etag)
            staging.lxd.configuration.complete(body)
        body, _ = staging.lxd.configuration.request('DELETE', endpoint, etag=etag)
        staging.lxd.configuration.complete(body)
