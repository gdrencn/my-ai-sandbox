"""Host entry and shared complete challenge; excluded from product/installers."""
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit

from .core import Error, LXD, Manager, validate_target
from .i18n import Parser, t
from .menu import Cancelled, interactive
from .menu import container_options
from .presentation import Progress
from .test_output import Output


def require_host():
    if sys.platform != 'linux':
        raise Error(t('security_host_required'))
    markers = [os.environ.get('container', '')]
    for path in ('/run/systemd/container', '/proc/1/environ'):
        try:
            with open(path, 'rb') as stream:
                value = stream.read(65536).decode(errors='replace')
            markers.extend(value.split('\0') if path.endswith('environ') else [value.strip()])
        except OSError:
            pass
    if any(value and (value.startswith('container=') or value in ('lxc', 'lxd', 'docker', 'podman', 'systemd-nspawn'))
           for value in markers) or Path('/.dockerenv').exists():
        raise Error(t('security_host_required'))


def target_instance(manager, target):
    validate_target(target)
    instance = manager.require(target)
    identity = instance['config'].get('volatile.uuid')
    if instance['status'] not in ('Running', 'Stopped') or not isinstance(identity, str) or not identity:
        raise Error(t('security_target_state', target=target))
    return instance


def choose_target(manager, target, output):
    if target is not None:
        target_instance(manager, target)
        return target
    with output.waiting(t('list_loading')):
        items = manager.list()
    if not items:
        output.keep(t('security_empty'))
        return None
    def choose(ui):
        name = ui.choose(t('security_select'), container_options(items) + [(None, t('menu_cancel'))],
                         default=items[0]['name'], cancel='cancel')
        if name is None:
            raise Cancelled()
        target_instance(manager, name)
        return name
    try:
        return interactive(choose)
    except OSError:
        raise Error(t('security_target_required')) from None


def settle_start(manager, target, lifecycle, report):
    """An interrupted lxc client can leave a daemon operation in progress."""
    api = manager.lxd.configuration
    body, _ = api.request('GET', api.endpoint('/1.0/operations') + '&recursion=1')
    groups = body.get('metadata')
    if body.get('type') != 'sync' or not isinstance(groups, dict) or any(not isinstance(items, list) for items in groups.values()):
        raise Error(t('lxd_invalid_data'))
    lifecycle['pending_operations'] = []
    for items in groups.values():
        for item in items:
            if (not isinstance(item, dict) or not isinstance(item.get('resources'), dict)
                    or type(item.get('status_code')) is not int):
                raise Error(t('lxd_invalid_data'))
            resources = item['resources']
            selected = [resources.get(kind, []) for kind in ('instances', 'containers')]
            if any(not isinstance(paths, list) or any(not isinstance(path, str) for path in paths) for paths in selected):
                raise Error(t('lxd_invalid_data'))
            paths = selected[0] + selected[1]
            metadata = item.get('metadata', {})
            if not isinstance(metadata, dict):
                raise Error(t('lxd_invalid_data'))
            entity = metadata.get('entity_url')
            if entity is not None:
                if not isinstance(entity, str):
                    raise Error(t('lxd_invalid_data'))
                paths.append(entity)
            def belongs(path):
                url = urlsplit(path)
                return (url.path in ('/1.0/instances/'+target, '/1.0/containers/'+target)
                        and parse_qs(url.query).get('project', [manager.lxd.project]) == [manager.lxd.project])
            if item.get('class') != 'task' or item['status_code'] >= 200 or not any(belongs(path) for path in paths):
                continue
            identifier = item.get('id')
            if not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f-]{36}', identifier):
                raise Error(t('lxd_invalid_data'))
            report.write(t('security_wait_start'))
            completed, _ = api.request('GET', api.endpoint('/1.0/operations/'+identifier+'/wait')
                                       + '&timeout=' + str(manager.lxd.timeout))
            result = completed.get('metadata')
            if (completed.get('type') != 'sync' or not isinstance(result, dict)
                    or type(result.get('status_code')) is not int or result['status_code'] < 200):
                raise Error(t('security_restore_failed'))
            lifecycle['pending_operations'].append(dict(id=identifier, status_code=result['status_code'], error=result.get('err', '')))


def challenge_target(manager, target, challenge, report, *, timeout, positive):
    """Run against one stable identity; restore through standard lifecycle."""
    instance = target_instance(manager, target)
    initial, identity = instance['status'], instance['config']['volatile.uuid']
    lifecycle = dict(initial_status=initial, identity=identity, actions=[], final_status=None)
    report.data['lifecycle'] = lifecycle
    starting = False
    try:
        if initial == 'Stopped':
            lifecycle['actions'].append('start')
            starting = True
            manager.start(target)
            starting = False
        current = target_instance(manager, target)
        if current['config']['volatile.uuid'] != identity:
            raise Error(t('security_identity_changed'))
        # Standard start can apply default GPU access to an imported container
        # that has no previous GPU record. Assert the resulting configured flag.
        record = manager.gpu.record(current)
        gpu = 'on' if record and record['enabled'] else 'off'
        report.data['gpu_expected'] = gpu
        return challenge.run_target(manager.lxd.command, target, report, gpu=gpu, timeout=timeout, positive=positive)
    finally:
        try:
            current = manager.require(target)
            if current['config']['volatile.uuid'] != identity:
                raise Error(t('security_identity_changed'))
            if starting:
                settle_start(manager, target, lifecycle, report)
                current = target_instance(manager, target)
                if current['config']['volatile.uuid'] != identity:
                    raise Error(t('security_identity_changed'))
            if initial == 'Stopped' or current['status'] != initial:
                action = 'stop' if initial == 'Stopped' else 'start'
                lifecycle['actions'].append(action)
                getattr(manager, action)(target)
            current = target_instance(manager, target)
            lifecycle['final_status'] = current['status']
            if current['config']['volatile.uuid'] != identity or current['status'] != initial:
                raise Error(t('security_restore_failed'))
            report.emit(challenge.probe.result('host-state-restore', 'PASS',
                        t('security_restored'), **lifecycle))
        except (Exception, KeyboardInterrupt) as exc:
            report.emit(challenge.probe.result('host-state-restore', 'ERROR',
                        t('security_restore_failed'), native_error=str(exc), **lifecycle))


def run_challenge(manager, target, report_path, output, *, project, timeout=3, positive=True):
    """Both public and automated callers use this exact orchestration/reporting."""
    from tests.probe_source import source_bytes
    sources = {name: source_bytes(name) for name in ('guest_security_probe.py', 'host_security_probe.py')}
    evidence = dict(target=target, status='not_run',
                    source_sha256=hashlib.sha256(sources['guest_security_probe.py']).hexdigest(),
                    host_source_sha256=hashlib.sha256(sources['host_security_probe.py']).hexdigest())
    with tempfile.TemporaryDirectory(prefix='mas-security-module-') as directory:
        root = Path(directory)
        for name, content in sources.items():
            (root / name).write_bytes(content)
        spec = importlib.util.spec_from_file_location('complete_host_probe', root / 'host_security_probe.py')
        challenge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(challenge)
        path = challenge.probe.report_path(report_path, 'security-')
        primary = None
        with path.with_suffix('.log').open('x', encoding='utf-8') as log:
            def display(message):
                log.write(message + '\n')
                log.flush()
                output.challenge(message)
            report = challenge.probe.ChallengeReport('complete-boundary-probe', write=display, diagnostic=display,
                                                     project=project, target=target,
                                                     source_sha256=evidence['source_sha256'],
                                                     host_source_sha256=evidence['host_source_sha256'])
            try:
                primary = challenge_target(manager, target, challenge, report, timeout=timeout, positive=positive)
            except (Exception, KeyboardInterrupt) as exc:
                primary = exc
                report.emit(challenge.probe.result('host-execution', 'ERROR', t('security_execution_failed'), native_error=str(exc)))
            code = report.finish(path, interrupted=isinstance(primary, KeyboardInterrupt))
            evidence.update(gpu_expected=report.data.get('gpu_expected'), report=report.data, reference=report.data.get('reference'),
                            guest_report=report.data.get('guest_report'),
                            guest_only_positive_controls=report.data.get('guest_only_positive_controls', []),
                            status='passed' if code == 0 and primary is None else 'failed')
        return code, evidence, primary


def terminate(signum, frame):
    raise KeyboardInterrupt()


def main(argv=None):
    parser = Parser(description=t('security_help'))
    parser.add_argument('target', nargs='?', help=t('security_target_help'))
    parser.add_argument('--report', type=Path, help=t('security_report_help'))
    parser.add_argument('--timeout', type=float, default=3, help=t('security_timeout_help'))
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 10:
        parser.error(t('security_timeout_help'))
    output = Output()
    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        require_host()
        progress = Progress()
        from .isolation import PROJECT
        manager = Manager(LXD(project=PROJECT, diagnostic=progress.output.keep), report=progress)
        target = choose_target(manager, args.target, output)
        if target is None:
            return 0
        output.section(t('test_category_security'), t('case_isolation-runtime'), t('security_help'))
        code, _, _ = run_challenge(manager, target, args.report, output, project=PROJECT, timeout=args.timeout)
        return code
    except Cancelled:
        output.keep(t('security_cancelled'))
        return 130
    except KeyboardInterrupt:
        output.keep(t('security_cancelled'))
        return 130
    except (Error, OSError, ValueError) as exc:
        output.keep(t('error', error=exc))
        return 2
    finally:
        output.clear()
        signal.signal(signal.SIGTERM, previous)
