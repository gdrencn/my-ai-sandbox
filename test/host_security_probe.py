#!/usr/bin/env python3
"""Host-assisted LXD challenges; uses the same independent guest primitives."""
import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guest_security_probe as probe


def host_environment():
    if sys.platform != 'linux':
        raise ValueError('请在管理 LXD 的 Linux/WSL 宿主运行。')
    markers = [os.environ.get('container', '')]
    path = Path('/run/systemd/container')
    if path.exists():
        markers.append(probe.read_text(path).strip())
    if any(marker and marker not in ('wsl', 'microsoft') for marker in markers):
        raise ValueError('此入口必须在宿主运行；容器内请使用 security.sh。')


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
            raise ValueError('binfmt_misc 子进程结果无效：' + child.stderr)
        return item
    except Exception as exc:
        return probe.result(check, 'ERROR', 'binfmt_misc 子进程未完成', native_error=str(exc))


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


def guest_checks(reference, timeout, emit):
    probe.environment_check()
    validate_host_reference(reference)
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
    for item in reference['sockets']:
        emit(probe.bounded_call('management-socket:' + item['path'], ['--_socket', item['path'], json.dumps(reference['sockets'])], timeout))
    emit(bounded_mount(reference, timeout))


def validate_guest_report(data, reference):
    if (not isinstance(data, dict) or data.get('schema') != 2
            or data.get('exit_code') not in (0, 1, 2, 130) or not isinstance(data.get('checks'), list)):
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
    required |= {'management-socket:'+item['path'] for item in reference['sockets']}
    if len(ids) != len(set(ids)) or not required.issubset(ids) or not any(name.startswith('binfmt:existing') for name in ids):
        raise ValueError('容器挑战报告遗漏或重复了要求的检查项')
    counts = {status:sum(item['status']==status for item in checks) for status in ('PASS','FAIL')}
    if data.get('counts') != counts or (data['exit_code']==0) != (counts['FAIL']==0):
        raise ValueError('容器挑战报告汇总与检查结果不一致')
    return data


def run_target(command, target, report, timeout=3):
    """Public host entry and mas-test use this same orchestration."""
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
                        '--_guest-reference', remote + '/host-reference.json', '--timeout', str(timeout),
                        '--report', remote + '/report.json'])
                    report.data['guest_stdout'] = output
                except Exception as exc:
                    primary = exc
                    report.data['guest_stdout'] = str(exc)
                try:
                    command(['file', 'pull', 'local:' + target + remote + '/report.json', str(root / 'report.json')])
                    guest = validate_guest_report(json.loads((root / 'report.json').read_text()), reference)
                    report.data['guest_report'] = guest
                    for item in guest['checks']:
                        if item.get('status') not in ('PASS', 'FAIL'):
                            raise ValueError('容器挑战报告包含无效测试状态')
                        report.emit(item)
                except Exception as exc:
                    report.emit(probe.result('host-report', 'ERROR', '容器报告取回或读取失败', native_error=str(exc)))
                if primary is not None:
                    report.data['native_failure'] = str(primary)
                    if guest is None or not guest.get('counts', {}).get('FAIL'):
                        report.emit(probe.result('host-execution', 'ERROR', '容器挑战命令失败', native_error=str(primary)))
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


def lxc_command(project):
    def command(args):
        child = subprocess.run(['lxc', '--project', project, *args], capture_output=True, text=True, timeout=90)
        if child.returncode:
            raise RuntimeError('\n'.join(part for part in (child.stdout.strip(), child.stderr.strip()) if part)
                               or 'lxc 退出码 ' + str(child.returncode))
        return child.stdout
    return command


def choose_target(command, target):
    instances = json.loads(command(['list', 'local:', '--format=json']))
    if not isinstance(instances, list) or any(not isinstance(item, dict)
            or not isinstance(item.get('name'), str) or not isinstance(item.get('config'), dict)
            or not isinstance(item.get('status'), str) for item in instances):
        raise ValueError('LXD 容器列表格式无效')
    managed = sorted((item for item in instances if item.get('type') == 'container'
                      and item['config'].get('user.mas.managed') == 'true'), key=lambda item: item['name'])
    def validate(name):
        if not re.fullmatch(r'[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', name or ''):
            raise ValueError('TARGET 必须是本地容器名。')
        instance = next((item for item in managed if item['name'] == name), None)
        if instance is None:
            raise ValueError('当前 Project 中没有此 mas 管理的容器：' + name)
        if instance['status'] not in ('Running', 'Stopped'):
            raise ValueError('容器当前状态不允许挑战：' + name + '（' + instance['status'] + '）')
        return name
    if target is not None:
        return validate(target)
    print('mas 管理的容器：', flush=True)
    for item in managed:
        status = {'Running':'运行中', 'Stopped':'已停止'}.get(item['status'], item['status'])
        print('  ' + probe.terminal_text(item['name']) + '  ' + probe.terminal_text(status), flush=True)
    if not managed:
        print('  当前 Project 中没有 mas 管理的容器。', flush=True)
    try:
        # Separate streams avoid BufferedRandom's seek requirement on a TTY.
        # Read from the controlling terminal even when stdin is a curl pipe.
        with open('/dev/tty', 'r') as terminal_in, open('/dev/tty', 'w') as terminal_out:
            terminal_out.write('输入容器名，留空取消。\n')
            while True:
                terminal_out.write('请输入要挑战的容器名：'); terminal_out.flush()
                name = terminal_in.readline().strip()
                if not name:
                    raise ValueError('已取消宿主侧挑战。')
                try:
                    return validate(name)
                except ValueError as exc:
                    terminal_out.write(probe.terminal_text(str(exc)) + '\n')
    except OSError:
        raise ValueError('非交互执行需要提供 TARGET；例如 security-host.sh demo。') from None


def installed_manager(project):
    """Reuse the installed product's complete lifecycle, including mounts."""
    product = Path(shutil.which('mas') or Path.home() / '.local/bin/mas').resolve()
    if not product.is_file() or not zipfile.is_zipfile(product):
        raise ValueError('未找到已安装的 mas 产品，请先安装 mas。')
    with zipfile.ZipFile(product) as archive:
        if not {'mas/core.py', 'mas/isolation.py', 'mas/presentation.py', 'mas/__init__.py'} <= set(archive.namelist()):
            raise ValueError('已安装的 mas 产品格式无效，请重新安装 mas。')
    sys.path.insert(0, str(product))
    try:
        from mas.core import LXD, Manager
        from mas.presentation import Progress
        progress = Progress()
        return Manager(LXD(project=project, diagnostic=progress.output.keep), report=progress)
    finally:
        sys.path.remove(str(product))


def challenge_target(command, target, report, manager, timeout=3):
    """Challenge a managed target and restore its original stable state."""
    instance = manager.require(target)
    initial = instance['status']
    identity = instance.get('config', {}).get('volatile.uuid')
    if initial not in ('Running', 'Stopped') or not isinstance(identity, str) or not identity:
        raise ValueError('容器状态或身份不允许挑战。')
    lifecycle = dict(initial_status=initial, identity=identity, actions=[], final_status=None)
    report.data['lifecycle'] = lifecycle
    try:
        if initial == 'Stopped':
            print('通过 mas 启动容器：' + probe.terminal_text(target), flush=True)
            lifecycle['actions'].append('start')
            manager.start(target)
        run_target(command, target, report, timeout)
    finally:
        try:
            current = manager.require(target)
            lifecycle['final_status'] = current['status']
            if current.get('config', {}).get('volatile.uuid') != identity:
                raise ValueError('容器身份已变化，未操作替换后的容器。')
            if initial == 'Stopped':
                print('通过 mas 恢复停止状态：' + probe.terminal_text(target), flush=True)
                lifecycle['actions'].append('stop')
                manager.stop(target)
                current = manager.require(target)
                lifecycle['final_status'] = current['status']
                if current.get('config', {}).get('volatile.uuid') != identity:
                    raise ValueError('恢复后容器身份已变化。')
            if current['status'] != initial:
                raise ValueError('容器未恢复原状态：' + initial + ' → ' + current['status'])
            if initial == 'Stopped':
                report.emit(probe.result('host-state-restore', 'PASS', '通过标准 mas stop 恢复原停止状态', target=target))
        except Exception as exc:
            report.emit(probe.result('host-state-restore', 'ERROR', '容器原状态恢复或核验失败', native_error=str(exc)))
        except KeyboardInterrupt:
            report.emit(probe.result('host-state-restore', 'ERROR', '容器原状态恢复中断'))
            raise


def terminate_challenge(signum, frame):
    raise KeyboardInterrupt


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
    parser = argparse.ArgumentParser(description='从 Linux/WSL 宿主挑战现有 LXD 容器的宿主资源边界；不修改容器配置。')
    parser.add_argument('target', nargs='?', help='mas 管理的本地容器名；省略时从终端输入；按需启动并恢复原状态')
    parser.add_argument('--project', default='mas', help='LXD Project，默认 mas')
    parser.add_argument('--report', type=Path, help='宿主 JSON 报告路径，默认生成唯一文件')
    parser.add_argument('--timeout', type=float, default=3, help='单项挑战超时（1–10 秒，默认 3）')
    parser.add_argument('--_guest-reference', type=Path, help=argparse.SUPPRESS)
    options = parser.parse_args(args)
    if not 1 <= options.timeout <= 10:
        parser.error('--timeout 必须为 1–10 秒')
    report = probe.ChallengeReport('host-assisted-boundary-probe', project=options.project, target=options.target)
    try:
        path = probe.report_path(options.report, 'host-security-')
    except ValueError as exc:
        print(probe.terminal_text(str(exc)), file=sys.stderr)
        return 2
    interrupted = False
    previous_term = None
    try:
        if options._guest_reference:
            probe.environment_check()
            reference = validate_host_reference(json.loads(options._guest_reference.read_text()))
            guest_checks(reference, options.timeout, report.emit)
        else:
            previous_term = signal.signal(signal.SIGTERM, terminate_challenge)
            host_environment()
            command = lxc_command(options.project)
            target = choose_target(command, options.target)
            report.data['target'] = target
            print('\n宿主侧容器安全挑战：' + probe.terminal_text(options.project + '/' + target) + '\n', flush=True)
            challenge_target(command, target, report, installed_manager(options.project), options.timeout)
    except KeyboardInterrupt:
        interrupted = True
        report.emit(probe.result('host-execution', 'ERROR', '挑战中断'))
    except Exception as exc:
        report.emit(probe.result('host-execution', 'ERROR', '挑战未完成', native_error=str(exc)))
    finally:
        if previous_term is not None:
            signal.signal(signal.SIGTERM, previous_term)
    return report.finish(path, interrupted)


if __name__ == '__main__':
    raise SystemExit(main())
