#!/usr/bin/env python3
"""Complete automated LXD boundary challenge with fresh host references."""
import argparse
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import uuid

probe_spec = importlib.util.spec_from_file_location('boundary_guest_probe', Path(__file__).with_name('guest_security_probe.py'))
probe = importlib.util.module_from_spec(probe_spec)
probe_spec.loader.exec_module(probe)


def boot_id():
    return probe.read_text('/proc/sys/kernel/random/boot_id').strip()


def binfmt_snapshot():
    """Read-only identity/registration metadata; never open an interpreter."""
    mounts = probe.parse_mounts(probe.read_text('/proc/self/mountinfo'))
    snapshots = []
    for mount in mounts:
        if mount['filesystem'] != 'binfmt_misc':
            continue
        root = Path(mount['path'])
        info = root.stat()
        entries = sorted(root.iterdir())
        if len(entries) > probe.MAX_INVENTORY:
            raise ValueError('binfmt_misc 注册清单超过检查上限')
        registrations = []
        for entry in entries:
            if entry.name == 'register':
                continue
            content = probe.read_text(entry)
            registrations.append(dict(name=entry.name, sha256=hashlib.sha256(content.encode()).hexdigest(),
                interpreter=next((line[12:] for line in content.splitlines() if line.startswith('interpreter ')), ''),
                flags=next((line[7:] for line in content.splitlines() if line.startswith('flags: ')), '')))
        snapshots.append(dict(path=str(root), device=info.st_dev, inode=info.st_ino, registrations=registrations))
    return snapshots


def validate_host_reference(data):
    probe.validate_reference(data)
    if (not data.get('canaries') or not isinstance(data.get('boot_id'), str)
            or not re.fullmatch(r'[0-9a-f-]{36}', data['boot_id'])):
        raise ValueError('宿主参照缺少当次 boot ID 或唯一标记')
    mounts = data.get('binfmt')
    if not isinstance(mounts, list) or len(mounts) > probe.MAX_INVENTORY:
        raise ValueError('宿主 binfmt_misc 参照无效')
    for item in mounts:
        if (not isinstance(item, dict) or not isinstance(item.get('path'), str) or not item['path'].startswith('/')
                or any(ord(c) < 32 or ord(c) == 127 for c in item['path'])
                or type(item.get('device')) is not int or item['device'] < 0
                or type(item.get('inode')) is not int or item['inode'] <= 0):
            raise ValueError('宿主 binfmt_misc 挂载身份无效')
    return data


def make_reference(marker, content):
    sockets = []
    for path in probe.SOCKETS:
        try:
            info = os.stat(path)
            if stat.S_ISSOCK(info.st_mode):
                sockets.append(dict(path=path, device=info.st_dev, inode=info.st_ino))
        except FileNotFoundError:
            pass
    return validate_host_reference(dict(schema=1, boot_id=boot_id(), namespaces=probe.namespace_ids(),
        canaries=[dict(path=str(marker), sha256=hashlib.sha256(content).hexdigest())],
        sockets=sockets, binfmt=binfmt_snapshot()))


def binfmt_mount_probe(reference):
    """Child only: isolated mount/user namespaces and no handler registration."""
    check = 'binfmt:temporary-mount'
    libc = ctypes.CDLL(None, use_errno=True)
    libc.unshare.argtypes = [ctypes.c_int]
    libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_void_p]
    def call(function, *args):
        if function(*args):
            number = ctypes.get_errno()
            raise OSError(number, os.strerror(number))
    step = 'unshare'
    try:
        call(libc.unshare, 0x10000000 | 0x00020000)  # CLONE_NEWUSER | CLONE_NEWNS
        step = 'private-propagation'
        call(libc.mount, None, b'/', None, (1 << 14) | (1 << 18), None)  # MS_REC | MS_PRIVATE
        work = tempfile.mkdtemp(prefix='mas-binfmt-', dir=Path(__file__).resolve().parent)
        mounted = False
        try:
            step = 'mount'
            call(libc.mount, b'binfmt_misc', os.fsencode(work), b'binfmt_misc', 0, None)
            mounted = True
            step = 'identity'
            info = os.stat(work)
            guest_ns = probe.namespace_ids()
            same_host = any(item['device'] == info.st_dev and item['inode'] == info.st_ino for item in reference['binfmt'])
            safe = not same_host and guest_ns['user'] != reference['namespaces']['user']
            # Mount lifetime ends with this child; detach before deleting its directory.
            libc.umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]
            step = 'unmount'
            call(libc.umount2, os.fsencode(work), 2)  # MNT_DETACH
            mounted = False
            return probe.result(check, 'PASS' if safe else 'FAIL',
                '临时挂载属于独立 user namespace，未暴露宿主实例' if safe else '临时挂载与宿主实例相同或身份不符合要求',
                device=info.st_dev, inode=info.st_ino, user_namespace=guest_ns['user'], host_match=same_host)
        finally:
            # Never recursively remove the contents of a mounted kernel fs.
            # On detach failure the child namespace teardown removes the mount;
            # the host runner then reclaims its underlying owned guest directory.
            if not mounted:
                try:
                    os.rmdir(work)
                except OSError:
                    step = 'cleanup'
                    raise
    except OSError as exc:
        if step in ('unshare', 'private-propagation', 'mount') and exc.errno in probe.DENIED:
            return probe.result(check, 'PASS', '建立临时入口被权限边界拒绝', step=step, errno=exc.errno)
        if step == 'mount' and exc.errno in (errno.ENODEV, errno.ENOSYS, errno.EOPNOTSUPP):
            return probe.result(check, 'PASS', '当前内核不提供此挂载能力，未能建立入口', step=step, errno=exc.errno)
        return probe.result(check, 'ERROR', '临时挂载测试未完成', step=step, errno=exc.errno, native_error=str(exc))


def bounded_mount(reference, timeout):
    check = 'binfmt:temporary-mount'
    try:
        child = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()), '--_binfmt', json.dumps(reference)],
                               capture_output=True, text=True, timeout=timeout)
        item = json.loads(child.stdout)
        if child.returncode or not isinstance(item, dict) or item.get('check') != check or item.get('status') not in probe.STATUS_TEXT:
            raise ValueError('binfmt_misc 子进程结果无效')
        return item
    except Exception as exc:
        return probe.result(check, 'ERROR', 'binfmt_misc 子进程未完成', native_error=str(exc),
                            native_stdout=child.stdout if 'child' in locals() else '',
                            native_stderr=child.stderr if 'child' in locals() else '')


def binfmt_existing(reference):
    mounts = [item for item in probe.parse_mounts(probe.read_text('/proc/self/mountinfo')) if item['filesystem'] == 'binfmt_misc']
    if not mounts:
        return [probe.result('binfmt:existing', 'PASS', '当前 mount namespace 未暴露 binfmt_misc 挂载', mounts=[])]
    results = []
    for mount in mounts:
        path = mount['path']
        info = os.stat(path)
        host_match = any(item['device'] == info.st_dev and item['inode'] == info.st_ino for item in reference['binfmt'])
        if host_match:
            results.append(probe.result('binfmt:existing:' + path, 'FAIL', '发现宿主 binfmt_misc 实例映射', mount=mount))
            continue
        # Different identity alone cannot establish ownership. Test only opening;
        # never write a handler and never execute a registered interpreter.
        try:
            fd = os.open(str(Path(path) / 'register'), os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            os.close(fd)
        except OSError as exc:
            if exc.errno in probe.DENIED | {errno.ENOENT}:
                results.append(probe.result('binfmt:existing:' + path, 'PASS',
                    '现有注册入口不可写或未提供，未修改规则', mount=mount, errno=exc.errno))
                continue
            raise
        results.append(probe.result('binfmt:existing:' + path, 'REVIEW',
            '现有注册入口可以打开；不同文件系统身份不足以证明它属于容器，来源验证未通过', mount=mount))
    return results


def guest_checks(reference, timeout, emit, gpu):
    probe.environment_check()
    validate_host_reference(reference)
    probe.run_checks(gpu, timeout, emit, reference=reference)
    for name in probe.NAMESPACES:
        try:
            guest = os.readlink('/proc/self/ns/' + name)
            host = reference['namespaces'][name]
            emit(probe.result('namespace:' + name, 'PASS' if guest != host else 'FAIL',
                              '比较容器与宿主 namespace', guest=guest, host=host))
        except Exception as exc:
            emit(probe.result('namespace:' + name, 'ERROR', 'namespace 比较失败', native_error=str(exc)))
    for check, operation in (('process-roots', lambda: probe.process_roots(reference)),
                             ('binfmt:existing', lambda: binfmt_existing(reference))):
        try:
            items = operation()
            for item in items if isinstance(items, list) else [items]:
                emit(item)
        except Exception as exc:
            emit(probe.result(check, 'ERROR', '此项验证失败', native_error=str(exc)))
    for index, item in enumerate(reference['canaries']):
        emit(probe.bounded_call('host-canary:' + str(index), ['--_canary', str(index), json.dumps(item)], timeout))
    emit(bounded_mount(reference, timeout))


def validate_guest_report(data, reference, gpu):
    if (not isinstance(data, dict) or data.get('schema') != 2
            or type(data.get('exit_code')) is not int or data['exit_code'] not in (0, 1, 2, 130)
            or data.get('gpu_expected') != gpu or not isinstance(data.get('checks'), list)
            or not isinstance(data.get('observations'), list)):
        raise ValueError('容器挑战报告格式无效')
    checks = data['checks']
    for item in checks:
        if (not isinstance(item, dict) or not isinstance(item.get('check'), str)
                or item.get('status') not in ('PASS', 'FAIL') or not isinstance(item.get('method'), str)
                or not isinstance(item.get('message'), str) or not isinstance(item.get('evidence'), dict)
                or item.get('failure_kind', 'boundary') not in ('boundary', 'verification', 'execution')):
            raise ValueError('容器挑战报告的检查项无效')
    ids = [item['check'] for item in checks]
    required = {'namespace:'+name for name in probe.NAMESPACES} | {'process-roots', 'binfmt:temporary-mount'}
    required |= {'host-canary:'+str(index) for index in range(len(reference['canaries']))}
    required |= {'management-socket:'+path for path in probe.SOCKETS}
    required |= {'management-socket:'+item['path'] for item in reference['sockets']}
    required |= {'uid-map','gid-map','seccomp','basic-interfaces','device-inventory','mount-sources','windows-interop','gpu-expectation'}
    required |= {'device:'+name for name in probe.DEVICES}
    required |= {'control:'+path for path in probe.CONTROLS}
    required |= {'read-endpoint:'+path for path in probe.READ_ENDPOINTS}
    required |= {'devlxd-api:'+path for path in probe.DEVLXD_ENDPOINTS}
    if (len(ids) != len(set(ids)) or not required.issubset(ids)
            or not any(name == 'binfmt:existing' or name.startswith('binfmt:existing:') for name in ids)):
        raise ValueError('容器挑战报告遗漏或重复了要求的检查项')
    observations = data['observations']
    for item in observations:
        if (not isinstance(item, dict) or 'status' in item or not isinstance(item.get('check'), str)
                or not isinstance(item.get('method'), str) or not isinstance(item.get('message'), str)
                or not isinstance(item.get('evidence'), dict)):
            raise ValueError('容器挑战报告的环境记录无效')
    all_ids = ids + [item['check'] for item in observations]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError('容器挑战报告重复了检查或环境记录')
    counts = {status:sum(item['status']==status for item in checks) for status in ('PASS','FAIL')}
    execution_failed = any(item['status'] == 'FAIL' and item.get('failure_kind') == 'execution' for item in checks)
    expected_code = 2 if execution_failed else 1 if counts['FAIL'] else 0
    if (data.get('counts') != counts or any(type(value) is not int for value in data.get('counts', {}).values())
            or (data['exit_code'] != expected_code and not (data['exit_code'] == 130 and execution_failed))):
        raise ValueError('容器挑战报告汇总与检查结果不一致')
    return data


def run_target(command, target, report, *, gpu, timeout=3, positive=False):
    """Run all guest probes once, recover evidence, then verify host integrity."""
    if gpu not in ('on', 'off'):
        raise ValueError('完整挑战需要明确的 GPU 开关预期。')
    primary = None
    remote = None
    with tempfile.TemporaryDirectory(prefix='mas-host-security-') as directory:
        root = Path(directory)
        # The marker is intentionally readable without credentials on the host.
        # Isolation must hide it rather than merely rely on directory permissions.
        with tempfile.TemporaryDirectory(prefix='mas-host-canary-') as marker_directory:
            os.chmod(marker_directory, 0o755)
            marker = Path(marker_directory) / 'marker'
            content = ('mas-non-secret-' + uuid.uuid4().hex).encode()
            marker.write_bytes(content)
            marker.chmod(0o644)
            reference = make_reference(marker, content)
            report.data['reference'] = reference
            reference_file = root / 'host-reference.json'
            reference_file.write_text(json.dumps(reference))
            try:
                if boot_id() != reference['boot_id']:
                    raise ValueError('宿主已重启，拒绝使用历史参照')
                remote = command(['exec', 'local:' + target, '--', 'python3', '-c',
                    "import tempfile;print(tempfile.mkdtemp(prefix='mas-host-challenge-'))"]).strip()
                if not re.fullmatch(r'/tmp/mas-host-challenge-[a-zA-Z0-9_-]+', remote):
                    remote = None
                    raise ValueError('容器临时目录返回格式无效')
                for source in (Path(probe.__file__), Path(__file__), reference_file):
                    command(['file', 'push', str(source), 'local:' + target + remote + '/' + source.name])
                primary = None
                guest = None
                try:
                    output = command(['exec', 'local:' + target, '--', 'python3', remote + '/host_security_probe.py',
                        '--_guest-reference', remote + '/host-reference.json', '--gpu', gpu, '--timeout', str(timeout),
                        '--report', remote + '/report.json'])
                    report.data['guest_stdout'] = output
                except (Exception, KeyboardInterrupt) as exc:
                    primary = exc
                    report.data['guest_stdout'] = str(exc)
                try:
                    command(['file', 'pull', 'local:' + target + remote + '/report.json', str(root / 'report.json')])
                    guest = validate_guest_report(json.loads((root / 'report.json').read_text()), reference, gpu)
                    report.data['guest_report'] = guest
                    for item in guest['checks']:
                        if item.get('status') not in ('PASS', 'FAIL'):
                            raise ValueError('容器挑战报告包含无效测试状态')
                        report.emit(item)
                    for item in guest['observations']:
                        report.emit(dict(item, status='INFO'))
                except Exception as exc:
                    report.emit(probe.result('host-report', 'ERROR', '容器报告取回或读取失败', native_error=str(exc)))
                if primary is not None:
                    report.data['native_failure'] = str(primary)
                    report.diagnostic(probe.terminal_text(str(primary)) or '容器挑战被中断。')
                    if guest is None or not guest.get('counts', {}).get('FAIL'):
                        report.emit(probe.result('host-execution', 'ERROR', '容器挑战命令失败', native_error=str(primary)))
                if positive and primary is None and guest and not guest['counts']['FAIL']:
                    report.data['guest_only_positive_controls'] = positive_controls(command, target, root, remote)
            finally:
                if remote:
                    try:
                        command(['exec', 'local:' + target, '--', 'rm', '-rf', '--', remote])
                    except Exception as exc:
                        report.emit(probe.result('host-cleanup', 'ERROR', '容器临时文件清理失败', native_error=str(exc), path=remote))
                for check, operation, message in (
                    ('host-canary-integrity', lambda: marker.read_bytes() == content, '宿主唯一标记内容应保持不变'),
                    ('binfmt:host-unchanged', lambda: binfmt_snapshot() == reference['binfmt'], '宿主 binfmt_misc 注册规则应保持不变'),
                    ('host-reference', lambda: boot_id() == reference['boot_id'], '宿主启动身份应保持不变')):
                    try:
                        report.emit(probe.result(check, 'PASS' if operation() else 'FAIL', message))
                    except Exception as exc:
                        report.emit(probe.result(check, 'ERROR', '挑战后状态核验失败', native_error=str(exc)))


    return primary


def positive_controls(command, target, root, remote):
    """Owned guest samples prove detection; they are not host escapes."""
    marker = root / 'positive-canary'
    content = ('mas-guest-positive-' + uuid.uuid4().hex).encode()
    marker.write_bytes(content)
    command(['file','push',str(marker),'local:'+target+remote+'/positive-canary'])
    command(['exec','local:'+target,'--','ln','-s',remote+'/positive-canary',remote+'/canary-alias'])
    outcomes = []
    for filename in ('positive-canary', 'canary-alias'):
        item = dict(path=remote+'/'+filename, sha256=hashlib.sha256(content).hexdigest())
        raw = command(['exec','local:'+target,'--','python3',remote+'/guest_security_probe.py',
                       '--_canary','0',json.dumps(item)])
        outcome = json.loads(raw)
        if outcome.get('status') != 'FAIL' or outcome.get('check') != 'host-canary:0' or not any(attempt.get('outcome') == 'readable' and attempt.get('sha256') == item['sha256']
                for attempt in outcome.get('evidence', {}).get('attempts', [])):
            raise ValueError('容器内正向检测样本未被识别：' + probe.terminal_text(raw))
        outcomes.append(outcome)
    return outcomes

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == '--_binfmt':
        try:
            probe.environment_check()
            if len(args) != 2:
                raise ValueError('内部挂载参数无效')
            reference = validate_host_reference(json.loads(args[1]))
            print(json.dumps(binfmt_mount_probe(reference), ensure_ascii=False))
            return 0
        except Exception as exc:
            print(probe.terminal_text(str(exc)), file=sys.stderr)
            return 2
    parser = argparse.ArgumentParser(description='自动化测试内部的完整容器安全挑战模块。')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--gpu', choices=('on','off'), required=True)
    parser.add_argument('--timeout', type=float, default=3)
    parser.add_argument('--_guest-reference', type=Path, required=True)
    options = parser.parse_args(args)
    if not 1 <= options.timeout <= 10:
        parser.error('--timeout 必须为 1–10 秒')
    report = probe.ChallengeReport('complete-boundary-probe', gpu_expected=options.gpu)
    try:
        path = probe.report_path(options.report, 'host-security-')
    except ValueError as exc:
        print(probe.terminal_text(str(exc)), file=sys.stderr)
        return 2
    interrupted = False
    try:
        probe.environment_check()
        reference = validate_host_reference(json.loads(options._guest_reference.read_text()))
        guest_checks(reference, options.timeout, report.emit, options.gpu)
    except KeyboardInterrupt:
        interrupted = True
        report.emit(probe.result('host-execution', 'ERROR', '挑战中断'))
    except Exception as exc:
        report.emit(probe.result('host-execution', 'ERROR', '挑战未完成', native_error=str(exc)))
    return report.finish(path, interrupted)


if __name__ == '__main__':
    raise SystemExit(main())
