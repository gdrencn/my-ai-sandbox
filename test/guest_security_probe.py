#!/usr/bin/env python3
"""Independent, non-destructive LXD guest boundary probes (Python 3.10+)."""
import argparse
import http.client
import itertools
import contextlib
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid

SCHEMA = 1
NAMESPACES = ('user', 'pid', 'mnt', 'net', 'ipc', 'uts')
DENIED = {errno.EACCES, errno.EPERM, errno.EROFS}
DEVICES = {
    'host-memory': (stat.S_IFCHR, 1, 1),
    'kernel-memory': (stat.S_IFCHR, 1, 2),
    'io-ports': (stat.S_IFCHR, 1, 4),
    'kernel-log': (stat.S_IFCHR, 1, 11),
    'kvm': (stat.S_IFCHR, 10, 232),
    'host-disk': (stat.S_IFBLK, 8, 0),
    'host-nvme': (stat.S_IFBLK, 259, 0),
    'host-loop': (stat.S_IFBLK, 7, 0),
}
CONTROLS = (
    '/proc/sysrq-trigger', '/proc/sys/kernel/modprobe',
    '/proc/sys/kernel/kexec_load_disabled', '/proc/sys/vm/drop_caches',
    '/proc/sys/kernel/core_pattern', '/proc/sys/kernel/hotplug',
    '/proc/sys/kernel/modules_disabled', '/proc/sys/kernel/sysrq',
    '/proc/sys/kernel/panic', '/proc/sys/kernel/panic_on_oops',
    '/proc/sys/kernel/unprivileged_bpf_disabled', '/proc/sys/kernel/perf_event_paranoid',
    '/proc/sys/kernel/yama/ptrace_scope',
    '/sys/power/state', '/sys/power/disk', '/sys/kernel/uevent_helper',
)
SOCKETS = (
    '/var/snap/lxd/common/lxd/unix.socket', '/var/lib/lxd/unix.socket',
    '/run/lxd/unix.socket', '/run/lxd.socket', '/run/docker.sock',
    '/var/run/docker.sock', '/run/containerd/containerd.sock',
    '/run/podman/podman.sock', '/run/libvirt/libvirt-sock', '/run/libvirt/virtqemud-sock',
    '/run/dbus/system_bus_socket', '/run/systemd/private', '/run/snapd.socket',
    '/run/snapd-snap.socket',
)
WINDOWS_PATHS = ('/mnt/c/Windows', '/mnt/c/Users', '/mnt/d/Windows', '/mnt/d/Users',
                 '/mnt/wsl', '/mnt/wslg', '/run/WSL', '/init',
                 '/proc/sys/fs/binfmt_misc/WSLInterop')
READ_ENDPOINTS = ('/proc/kcore', '/proc/kmsg')
SPECIAL_FILESYSTEMS = ('/sys/kernel/debug', '/sys/kernel/security', '/sys/fs/pstore',
                       '/sys/firmware/efi/efivars', '/sys/fs/bpf')
MAX_INVENTORY = 512
STATUS_TEXT = {'PASS': '通过', 'FAIL': '失败', 'REVIEW': '需核对',
               'SKIP': '未验证', 'INFO': '信息', 'ERROR': '测试错误'}


def check_method(check):
    methods = {
        'uid-map': '读取 /proc/self/uid_map，检查容器 root 对应的外层 UID',
        'gid-map': '读取 /proc/self/gid_map，检查容器 root 对应的外层 GID',
        'seccomp': '读取 /proc/self/status 的 Seccomp 值，核对过滤模式 2',
        'capabilities': '读取 /proc/self/status 的 CapEff 和 CapBnd，仅记录能力位',
        'apparmor': '读取 AppArmor enabled 和 /proc/self/attr/current，记录实际状态',
        'basic-interfaces': '读取 /dev/null 和 /dev/zero，观察 /proc 与 /sys',
        'gpu-driver-store': '检查 mountinfo 是否暴露整个 /usr/lib/wsl/drivers',
        'mount-sources': '检查 mountinfo 的文件系统类型、挂载根和挂载点',
        'device-inventory': '有界枚举 /dev 的设备类型及 major:minor；未知设备仅提示核对，不打开 watchdog/USB/PCI 设备',
        'process-roots': '有界读取可见进程的 root/mnt/user namespace，和提供的宿主 namespace 比较；不读取进程内存或环境',
        'socket-inventory': '读取 /proc/net/unix 与 /run/user 的管理 socket 路径，不连接抽象 socket 或扫描网络',
        'special-filesystems': '记录 debugfs/securityfs/pstore/efivarfs/bpffs 挂载与可见性，不修改其中内容',
        'devlxd': '检查 /dev/lxd/sock 是否可见，区分实例接口与宿主管理接口',
        'windows-interop': '检查 Windows/WSL 路径、binfmt_misc 注册项和 WSL_INTEROP，不执行解释器或 Windows 命令',
        'gpu-expectation': '列出 /dev/dxg 与 /dev/nvidiaN，核对显式 GPU 开关预期',
        'network-expectation': '核对网络开关预期、接口类型和 IPv4/IPv6 路由，不扫描网络或尝试登录',
        'host-canaries': '有宿主非敏感唯一标记参照时，尝试路径读取并比较 SHA-256',
        'network-policy': '说明网络测试范围，不进行网络扫描或登录',
        'execution': '检查执行条件、输入与报告路径，运行各项探测',
    }
    if check.startswith('device:'):
        mode, major, minor = DEVICES[check.split(':', 1)[1]]
        kind = 'char' if mode == stat.S_IFCHR else 'block'
        return (f'在私有临时目录 mknod {kind} {major}:{minor}，再只读 open/close；'
                '不读取、写入或执行 ioctl')
    if check.startswith('control:'):
        return '对 ' + check.split(':', 1)[1] + ' 尝试写模式 open/close，不写入任何字节'
    if check.startswith('read-endpoint:'):
        return '对 ' + check.split(':', 1)[1] + ' 只读 open/close；不读取内存或日志内容'
    if check.startswith('devlxd-api:'):
        return '对实例 devlxd 执行有界只读 GET ' + check.split(':', 1)[1] + '；不创建、修改或删除资源'
    if check.startswith('namespace:'):
        return '读取 /proc/self/ns/' + check.split(':', 1)[1] + '，有宿主参照时比较标识'
    if check.startswith('management-socket:'):
        return ('检查 ' + check.split(':', 1)[1] + '；存在时尝试 Unix socket 连接并立即关闭，不发送请求')
    if check.startswith('gpu-readonly:'):
        return '读取 mountinfo，核对 ' + check.split(':', 1)[1] + ' 的只读挂载选项'
    if check.startswith('host-canary:'):
        return '有界尝试直接路径及可见进程 root 下的唯一标记，比较 SHA-256；仅记录摘要，不保存内容'
    if check.startswith('binfmt:'):
        return '核对 binfmt_misc 来源；仅打开接口或在临时 user/mount namespace 挂载，不写注册规则'
    if check.startswith('host-'):
        return '从宿主采集当次参照并核对挑战前后状态'
    return methods.get(check, '执行此项检查')


def result(check, status, message, **evidence):
    return dict(check=check, method=check_method(check), status=status, message=message, evidence=evidence)


def terminal_text(text):
    return re.sub(r'[\x00-\x1f\x7f-\x9f]',
                  lambda match: json.dumps(match[0], ensure_ascii=True)[1:-1], text)


def mappings(text):
    rows = [tuple(map(int, line.split())) for line in text.splitlines() if line.strip()]
    if not rows or any(len(row) != 3 or min(row[:2]) < 0 or row[2] <= 0 for row in rows):
        raise ValueError('身份映射格式无效')
    return rows


def read_text(path):
    with open(path, encoding='utf-8', errors='replace') as source:
        text = source.read(1048577)
    if len(text) > 1048576:
        raise ValueError('读取超过 1 MiB 上限：' + str(path))
    return text


def visible_paths(paths):
    visible = []
    for path in paths:
        try:
            os.stat(path)
            visible.append(path)
        except FileNotFoundError:
            pass
    return visible


def namespace_ids():
    return {name: os.readlink('/proc/self/ns/' + name) for name in NAMESPACES}


def validate_reference(data):
    if not isinstance(data, dict) or type(data.get('schema')) is not int or data['schema'] != SCHEMA:
        raise ValueError('宿主参照 schema 必须为 1')
    ns = data.get('namespaces')
    if not isinstance(ns, dict) or set(ns) != set(NAMESPACES):
        raise ValueError('宿主参照必须包含 user/pid/mnt/net/ipc/uts 六种 namespace')
    for name, value in ns.items():
        if not isinstance(value, str) or not re.fullmatch(re.escape(name) + r':\[[0-9]+\]', value):
            raise ValueError('宿主 namespace 标识格式无效：' + name)
    canaries = data.get('canaries', [])
    if not isinstance(canaries, list) or len(canaries) > 16:
        raise ValueError('canaries 必须是至多 16 项的列表')
    for item in canaries:
        if not isinstance(item, dict):
            raise ValueError('canary 格式无效')
        path, digest = item.get('path'), item.get('sha256')
        if (not isinstance(path, str) or not path.startswith('/') or path == '/'
                or any(ord(c) < 32 or ord(c) == 127 for c in path)
                or any(part in ('.', '..') for part in path.split('/'))
                or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
            raise ValueError('canary 需要绝对文件路径和小写 SHA-256；不接受路径跳转')
    sockets = data.get('sockets', [])
    if not isinstance(sockets, list) or len(sockets) > 64:
        raise ValueError('sockets 必须是至多 64 项的列表')
    for item in sockets:
        if (not isinstance(item, dict) or not isinstance(item.get('path'), str)
                or not item['path'].startswith('/') or any(ord(c) < 32 or ord(c) == 127 for c in item['path'])
                or type(item.get('device')) is not int or item['device'] < 0
                or type(item.get('inode')) is not int or item['inode'] <= 0):
            raise ValueError('socket 参照需要绝对路径及有效 device/inode')
    return data


def environment_check():
    if sys.platform != 'linux':
        raise ValueError('此脚本仅适用于 Linux LXD 容器')
    if os.geteuid() != 0:
        raise ValueError('请在容器内用 sudo python3 运行，测试容器 root 的权限边界')
    markers = [os.environ.get('container', '')]
    for path in ('/run/systemd/container', '/proc/1/environ'):
        try:
            value = read_text(path)
            markers.extend(value.split('\0') if path.endswith('environ') else [value.strip()])
        except OSError:
            pass
    if not any(value in ('lxc', 'container=lxc') for value in markers):
        raise ValueError('未识别到 LXC 容器；拒绝在普通宿主环境执行探测')
    return markers


def denied_result(check, step, exc):
    evidence = dict(step=step, errno=exc.errno, native_error=str(exc))
    if exc.errno in DENIED:
        return result(check, 'PASS', '访问被权限或只读边界拒绝', **evidence)
    if exc.errno in (errno.ENOENT, errno.ENODEV, errno.ENXIO, errno.ENOSYS, errno.EOPNOTSUPP):
        return result(check, 'SKIP', '对象或能力不可用，不能据此确认权限隔离', **evidence)
    return result(check, 'ERROR', '探测发生非预期错误', **evidence)


def active_probe(kind, value, work):
    """Child-only operations: create a private node/open/close; never write or ioctl."""
    check = kind + ':' + value
    step = 'mknod' if kind == 'device' else 'open'
    try:
        if kind == 'device' and value in DEVICES:
            mode, major, minor = DEVICES[value]
            path = os.path.join(work, value)
            os.mknod(path, mode | 0o600, os.makedev(major, minor))
            step = 'open'
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
        elif kind == 'control' and value in CONTROLS:
            fd = os.open(value, os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        elif kind == 'read-endpoint' and value in READ_ENDPOINTS:
            fd = os.open(value, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        else:
            raise ValueError('未知的内部探测')
        os.close(fd)
        if kind == 'device':
            return result(check, 'FAIL', '能够打开未授权设备；未读取、写入或执行 ioctl', step=step)
        return result(check, 'REVIEW', '能够打开内核入口；未读写，实际内容访问权限尚未证实', step=step)
    except OSError as exc:
        if kind in ('control', 'read-endpoint') and exc.errno in (errno.ENOENT, errno.ENOTDIR):
            return result(check, 'PASS', '当前路径未暴露；此项验证入口不存在，不声称执行了权限拒绝测试',
                          step=step, errno=exc.errno, native_error=str(exc))
        return denied_result(check, step, exc)


def bounded_call(check, arguments, timeout):
    command = [sys.executable, '-I', str(Path(__file__).resolve()), *arguments]
    try:
        child = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return result(check, 'ERROR', '探测超时，不能当作权限拒绝', timeout=timeout,
                      native_stdout=exc.stdout.decode(errors='replace') if exc.stdout else '',
                      native_stderr=exc.stderr.decode(errors='replace') if exc.stderr else '')
    try:
        item = json.loads(child.stdout)
        if (child.returncode or not isinstance(item, dict)
                or item.get('check') != check or item.get('status') not in STATUS_TEXT
                or not isinstance(item.get('method'), str) or not isinstance(item.get('message'), str)
                or not isinstance(item.get('evidence'), dict)):
            raise ValueError('子进程返回内容无效')
        return item
    except (ValueError, TypeError):
        return result(check, 'ERROR', '探测子进程异常', returncode=child.returncode,
                      native_stdout=child.stdout, native_stderr=child.stderr)


def bounded_probe(kind, value, work, timeout):
    return bounded_call(kind + ':' + value, ['--_probe', kind, value, work], timeout)


def decode_mount_field(text):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), text)


def parse_mounts(text):
    records = []
    for line in text.splitlines():
        left, right = line.split(' - ', 1)
        fields, fs = left.split(), right.split()
        if len(fields) < 6 or len(fs) < 3:
            raise ValueError('mountinfo 格式无效')
        records.append(dict(root=decode_mount_field(fields[3]),
                            path=decode_mount_field(fields[4]), options=fields[5].split(','),
                            filesystem=fs[0], source=decode_mount_field(fs[1]),
                            super_options=fs[2].split(',')))
    if not records:
        raise ValueError('mountinfo 为空')
    return records


def gpu_mapping(path):
    return path == '/usr/lib/wsl/lib' or bool(re.fullmatch(r'/usr/lib/wsl/drivers/[^/]+', path))


def mount_checks(records):
    items = []
    suspicious = []
    for mount in records:
        path = mount['path']
        if gpu_mapping(path):
            items.append(result('gpu-readonly:' + path, 'PASS' if 'ro' in mount['options'] else 'FAIL',
                                'GPU 运行库映射应为只读', mount=mount))
        elif path == '/usr/lib/wsl/drivers':
            items.append(result('gpu-driver-store', 'FAIL', '整个驱动目录被挂载，超出精确子目录授权', mount=mount))
        elif (mount['filesystem'] in ('9p', 'drvfs', 'cifs', 'smb3', 'virtiofs')
              or re.match(r'^/mnt/(?:[a-z](?:/|$)|wsl(?:g)?(?:/|$))', path)
              or re.match(r'^/home/[^/]+(?:/|$)', mount['root'])):
            suspicious.append(mount)
    items.append(result('mount-sources', 'REVIEW' if suspicious else 'PASS',
                        '发现需核对来源的文件系统映射' if suspicious else '未发现典型 Windows/宿主 home 映射',
                        suspicious=suspicious))
    return items


def socket_check(path, references=()):
    check = 'management-socket:' + path
    try:
        info = os.stat(path)
        mode = info.st_mode
    except FileNotFoundError:
        return result(check, 'PASS', '管理 socket 路径不存在')
    except OSError as exc:
        return denied_result(check, 'stat', exc)
    if not stat.S_ISSOCK(mode):
        return result(check, 'REVIEW', '此路径存在但不是 socket，需核对来源')
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(2)
            connection.connect(path)
            peer = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        host_match = any(item['device'] == info.st_dev and item['inode'] == info.st_ino for item in references)
        local_peer, peer_namespaces = False, {}
        if peer[0] > 0:
            try:
                peer_namespaces = {name:os.readlink('/proc/' + str(peer[0]) + '/ns/' + name) for name in ('pid', 'mnt', 'user')}
                local_peer = all(peer_namespaces[name] == os.readlink('/proc/self/ns/' + name) for name in peer_namespaces)
            except OSError:
                pass
        return result(check, 'FAIL' if host_match else 'PASS' if local_peer else 'REVIEW',
                      '连接到了宿主参照中的管理 socket' if host_match else
                      '服务进程属于当前容器 namespace；未发送管理请求' if local_peer else
                      '可以连接；未发送管理请求，来源尚不能确认',
                      device=info.st_dev, inode=info.st_ino, host_reference_match=host_match,
                      peer_pid=peer[0], peer_uid=peer[1], peer_gid=peer[2], peer_namespaces=peer_namespaces)
    except OSError as exc:
        if exc.errno in DENIED:
            return denied_result(check, 'connect', exc)
        return result(check, 'REVIEW', 'socket 可见但连接未成功，不能据此证明服务隔离',
                      native_error=str(exc), errno=exc.errno)


def canary_check(index, item):
    attempts = []
    prefixes = ['', '/proc/1/root', '/proc/self/root']
    pids = sorted((name for name in os.listdir('/proc') if name.isdigit()), key=int)
    prefixes += ['/proc/' + pid + '/root' for pid in pids[:MAX_INVENTORY] if pid != '1']
    for prefix in prefixes:
        path = prefix + item['path']
        try:
            # The reference contains only caller-approved non-secret canaries.
            # Follow aliases too; rejecting a symlink would miss a real route.
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            with os.fdopen(fd, 'rb') as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    attempts.append(dict(path=path, outcome='not-regular'))
                    continue
                data = source.read(65537)
            digest = hashlib.sha256(data).hexdigest()
            attempts.append(dict(path=path, outcome='readable', sha256=digest, bytes=len(data)))
            if len(data) <= 65536 and digest == item['sha256']:
                return result('host-canary:' + str(index), 'FAIL',
                              '读到了宿主提供的唯一标记文件', attempts=attempts, processes_truncated=len(pids) > MAX_INVENTORY)
        except OSError as exc:
            if exc.errno not in DENIED | {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}:
                return result('host-canary:' + str(index), 'ERROR', '宿主标记探测异常',
                              native_error=str(exc), attempts=attempts)
            attempts.append(dict(path=path, outcome='unavailable', errno=exc.errno))
    readable = any(attempt['outcome'] in ('readable', 'not-regular') for attempt in attempts)
    truncated = len(pids) > MAX_INVENTORY
    return result('host-canary:' + str(index), 'REVIEW' if readable else 'SKIP' if truncated else 'PASS',
                  '同名对象可见，内容不符；需核对来源' if readable else
                  '进程路径清单达到上限，未完整验证' if truncated else '宿主标记不可读或不可见',
                  attempts=attempts, processes_truncated=len(pids) > MAX_INVENTORY)


def device_inventory():
    entries, unknown, errors, depth_limited = [], [], [], []
    pending = [('/dev', 0)]
    visited = 0
    while pending and visited < MAX_INVENTORY:
        directory, depth = pending.pop()
        try:
            with os.scandir(directory) as stream:
                for entry in stream:
                    if visited >= MAX_INVENTORY:
                        break
                    visited += 1
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISDIR(info.st_mode) and depth < 3:
                            pending.append((entry.path, depth + 1))
                        elif stat.S_ISDIR(info.st_mode):
                            depth_limited.append(entry.path)
                        if not (stat.S_ISCHR(info.st_mode) or stat.S_ISBLK(info.st_mode)):
                            continue
                        major, minor = os.major(info.st_rdev), os.minor(info.st_rdev)
                        basic = (stat.S_ISCHR(info.st_mode) and
                                 ((major == 1 and minor in (3, 5, 7, 8, 9))
                                  or (major == 5 and minor in (0, 1, 2))
                                  or 136 <= major <= 143
                                  or (major == 10 and minor in (200, 229))))
                        gpu = (stat.S_ISCHR(info.st_mode) and
                               (major, minor) not in {(major, minor) for mode, major, minor in DEVICES.values() if mode == stat.S_IFCHR}
                               and bool(re.fullmatch(r'/dev/(?:dxg|nvidia[0-9]+|nvidiactl|nvidia-uvm(?:-tools)?|nvidia-modeset|dri/(?:card|renderD)[0-9]+)', entry.path)))
                        item = dict(path=entry.path, kind='char' if stat.S_ISCHR(info.st_mode) else 'block',
                                    major=major, minor=minor, basic=basic, gpu=gpu)
                        entries.append(item)
                        if not basic and not gpu:
                            unknown.append(item)
                    except OSError as exc:
                        errors.append(dict(path=entry.path, errno=exc.errno, native_error=str(exc)))
        except OSError as exc:
            errors.append(dict(path=directory, errno=exc.errno, native_error=str(exc)))
    inaccessible = [item for item in errors if item['errno'] in DENIED]
    errors = [item for item in errors if item['errno'] not in DENIED]
    return result('device-inventory', 'REVIEW' if unknown else 'ERROR' if errors else 'SKIP' if visited >= MAX_INVENTORY or depth_limited else 'PASS',
                  '设备清单；非基础/GPU 设备需核对来源及授权，不据节点存在认定可操作宿主',
                  devices=sorted(entries, key=lambda item: item['path']), unclassified=unknown,
                  errors=errors, inaccessible=inaccessible, depth_limited=depth_limited, truncated=visited >= MAX_INVENTORY)


def process_roots(reference):
    pids = sorted((name for name in os.listdir('/proc') if name.isdigit()), key=int)
    entries, errors, matches = [], [], []
    for pid in pids[:MAX_INVENTORY]:
        entry = dict(pid=int(pid))
        try:
            entry['root'] = os.readlink('/proc/' + pid + '/root')
            entry['namespaces'] = {name: os.readlink('/proc/' + pid + '/ns/' + name) for name in ('user', 'mnt', 'pid')}
            if reference and any(entry['namespaces'][name] == reference['namespaces'][name] for name in entry['namespaces']):
                matches.append(entry)
            entries.append(entry)
        except OSError as exc:
            if exc.errno != errno.ENOENT:  # Processes may exit during inventory.
                errors.append(dict(pid=int(pid), errno=exc.errno, native_error=str(exc)))
    return result('process-roots', 'FAIL' if matches else 'SKIP' if not reference or errors or len(pids) > MAX_INVENTORY else 'PASS',
                  '发现使用宿主 namespace 的可见进程' if matches else
                  '进程来源验证未完成' if not reference or errors or len(pids) > MAX_INVENTORY else
                  '已核对可见进程 namespace 与 root 路径，未发现宿主进程',
                  processes=entries, host_matches=matches, errors=errors, truncated=len(pids) > MAX_INVENTORY)


def socket_paths():
    paths = list(SOCKETS)
    truncated = False
    for line in read_text('/proc/net/unix').splitlines()[1:]:
        fields = line.split(maxsplit=7)
        if len(fields) == 8:
            path = fields[7]
            if path.startswith('/') and re.search(r'(?:lxd|docker|containerd|podman|libvirt|virtqemud|snapd|systemd/private|bus)', path):
                paths.append(path)
    root = Path('/run/user')
    if root.exists():
        entries = list(itertools.islice(root.iterdir(), MAX_INVENTORY + 1))
        truncated = len(entries) > MAX_INVENTORY
        for entry in entries[:MAX_INVENTORY]:
            if entry.name.isdigit():
                paths.extend(str(entry / suffix) for suffix in ('docker.sock', 'podman/podman.sock', 'bus'))
    paths = list(dict.fromkeys(paths))
    return paths[:MAX_INVENTORY], truncated or len(paths) > MAX_INVENTORY


class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        try:
            self.sock.settimeout(self.timeout)
            self.sock.connect('/dev/lxd/sock')
        except BaseException:
            self.sock.close()
            self.sock = None
            raise


DEVLXD_ENDPOINTS = ('/1.0', '/1.0/config', '/1.0/config/security.privileged',
                    '/1.0/storage-pools/mas-probe-unowned/volumes/custom',
                    '/1.0/images/' + '0' * 64 + '/export')


def devlxd_check(endpoint):
    check = 'devlxd-api:' + endpoint
    try:
        if not stat.S_ISSOCK(os.stat('/dev/lxd/sock').st_mode):
            return result(check, 'REVIEW', '实例接口路径不是 socket')
    except FileNotFoundError:
        return result(check, 'PASS', '实例接口未暴露，当前没有此访问入口')
    with contextlib.closing(UnixHTTP('localhost', timeout=2)) as connection:
        connection.request('GET', endpoint)
        response = connection.getresponse()
        # Do not read image contents or return cloud-init/credential values.
        if endpoint in ('/1.0', '/1.0/config') and response.status == 200:
            body = response.read(16385)
            if len(body) > 16384:
                raise ValueError('devlxd 响应超出读取上限')
            data = json.loads(body)
            if endpoint == '/1.0/config':
                if not isinstance(data, list) or any(not isinstance(key, str) or not key.startswith(('/1.0/config/user.', '/1.0/config/cloud-init.')) for key in data):
                    raise ValueError('devlxd 配置列表格式无效')
                return result(check, 'PASS', '只返回本实例允许的配置键名，不读取配置值', http_status=200, keys=data)
            if not isinstance(data, dict):
                raise ValueError('devlxd 实例响应格式无效')
            return result(check, 'FAIL' if data.get('supported_storage_drivers') else 'PASS',
                          '实例接口未开放卷管理能力', http_status=200,
                          volume_management_advertised=bool(data.get('supported_storage_drivers')))
        if endpoint in ('/1.0', '/1.0/config'):
            return result(check, 'SKIP', '基本实例接口不可用', http_status=response.status)
        # 403 proves the documented feature/authorization gate refused access.
        # A missing fingerprint/pool can also produce 404 with the feature on.
        status = 'PASS' if response.status in (401, 403) else 'FAIL' if response.status == 200 else 'SKIP' if response.status == 404 else 'ERROR'
        return result(check, status, '实例受限 API 的只读请求结果；404 不能证明权限已关闭', http_status=response.status)


def network_check(expected):
    """Observe both IP families locally, without sending network traffic."""
    names = sorted(name for _, name in socket.if_nameindex())
    if len(names) > MAX_INVENTORY:
        raise ValueError('网络接口清单超过上限')
    external = []
    for name in names:
        flags = int(read_text('/sys/class/net/' + name + '/flags').strip(), 16)
        if not flags & 0x8:  # IFF_LOOPBACK
            external.append(name)
    routes = []
    for family, path in (('ipv4', '/proc/net/route'), ('ipv6', '/proc/net/ipv6_route')):
        try:
            lines = read_text(path).splitlines()
        except FileNotFoundError:
            if family == 'ipv6':
                continue
            raise
        for line in lines[1:] if family == 'ipv4' else lines:
            fields = line.split()
            if len(fields) != (11 if family == 'ipv4' else 10):
                raise ValueError('网络路由数据格式无效')
            routes.append(dict(family=family, interface=fields[0] if family == 'ipv4' else fields[-1]))
            if len(routes) > MAX_INVENTORY:
                raise ValueError('网络路由清单超过上限')
    external_routes = [route for route in routes if route['interface'] not in names or route['interface'] in external]
    matches = external == ['eth0'] if expected == 'on' else not external and not external_routes
    return result('network-expectation', 'INFO' if expected == 'unknown' else 'PASS' if matches else 'FAIL',
                  '核对网络开关及 IPv4/IPv6 接口、路由；容器内部回环通信保留',
                  expected=expected, interfaces=names, external_interfaces=external, routes=routes)


def run_checks(gpu, timeout, emit, reference=None, network='unknown'):
    def observe(check, operation):
        try:
            emit(operation())
        except Exception as exc:
            emit(result(check, 'ERROR', '此项观察失败；继续检查其他入口', native_error=str(exc)))

    def identity(name):
        text = read_text('/proc/self/' + name + '_map')
        rows = mappings(text)
        safe = any(start == 0 for start, _, _ in rows) and all(outside > 0 for _, outside, _ in rows)
        return result(name + '-map', 'PASS' if safe else 'FAIL', '容器 root 不应映射到宿主 root', mapping=text)
    for name in ('uid', 'gid'):
        observe(name + '-map', lambda name=name: identity(name))

    status = {}
    def security_status():
        status.update(dict(line.split(':', 1) for line in read_text('/proc/self/status').splitlines() if ':' in line))
        mode = status.get('Seccomp', '').strip()
        return result('seccomp', 'PASS' if mode == '2' else 'FAIL', '检查实际 seccomp 过滤状态', mode=mode)
    observe('seccomp', security_status)
    emit(result('capabilities', 'INFO' if status else 'SKIP', '能力位属于当前 namespace；不能单凭它判断拥有宿主权限',
                effective=status.get('CapEff', '').strip(), bounding=status.get('CapBnd', '').strip()))
    def apparmor():
        values, errors = {}, []
        for path, key in (('/proc/self/attr/current', 'profile'), ('/sys/module/apparmor/parameters/enabled', 'enabled')):
            try:
                values[key] = read_text(path).strip()
            except OSError as exc:
                errors.append(dict(path=path, errno=exc.errno))
        return result('apparmor', 'INFO', '记录可选 AppArmor 的实际状态；不将未启用本身视为越界', **values, errors=errors)
    observe('apparmor', apparmor)

    def basic():
        with open('/dev/null', 'rb') as source:
            if source.read(1) != b'':
                raise ValueError('/dev/null 行为不符')
        with open('/dev/zero', 'rb') as source:
            if source.read(1) != b'\0':
                raise ValueError('/dev/zero 行为不符')
        if not stat.S_ISDIR(os.stat('/sys').st_mode):
            raise ValueError('/sys 不是目录')
        return result('basic-interfaces', 'PASS', '/dev/null、/dev/zero、/proc 和 /sys 是正常容器接口', sys_present=True)
    observe('basic-interfaces', basic)
    observe('device-inventory', device_inventory)

    records = []
    try:
        records = parse_mounts(read_text('/proc/self/mountinfo'))
        for item in mount_checks(records):
            emit(item)
    except Exception as exc:
        emit(result('mount-sources', 'ERROR', '挂载来源读取失败', native_error=str(exc)))
    def special():
        mounts = [item for item in records if item['path'] in SPECIAL_FILESYSTEMS]
        visible = visible_paths(SPECIAL_FILESYSTEMS)
        return result('special-filesystems', 'INFO', '记录内核接口挂载；可见不等于能读取或修改宿主', mounts=mounts, visible=visible)
    observe('special-filesystems', special)

    paths = list(SOCKETS)
    try:
        paths, truncated = socket_paths()
        emit(result('socket-inventory', 'SKIP' if truncated else 'INFO',
                    '管理入口路径清单；逐项连接检查，不发送管理请求', paths=paths, truncated=truncated))
    except Exception as exc:
        emit(result('socket-inventory', 'ERROR', '动态路径发现失败，仍检查固定管理路径', native_error=str(exc)))
    references = reference.get('sockets', []) if reference else []
    paths = sorted(set(paths) | {item['path'] for item in references})
    for path in paths:
        emit(bounded_call('management-socket:' + path, ['--_socket', path, json.dumps(references)], timeout))
    observe('devlxd', lambda: result('devlxd', 'INFO', '基本实例接口与宿主管理接口不同，按当前兼容策略保留',
                                   visible=bool(visible_paths(('/dev/lxd/sock',)))))
    for endpoint in DEVLXD_ENDPOINTS:
        emit(bounded_call('devlxd-api:' + endpoint, ['--_devlxd', endpoint], timeout))

    def windows():
        paths = visible_paths(WINDOWS_PATHS)
        interop = os.environ.get('WSL_INTEROP')
        registrations = []
        truncated = False
        root = Path('/proc/sys/fs/binfmt_misc')
        if root.exists():
            entries = list(itertools.islice(root.iterdir(), MAX_INVENTORY + 1))
            truncated = len(entries) > MAX_INVENTORY
            for item in entries[:MAX_INVENTORY]:
                if item.name not in ('register', 'status'):
                    content = read_text(item)
                    interpreter = next((line[12:] for line in content.splitlines() if line.startswith('interpreter ')), '')
                    registrations.append(dict(name=item.name, interpreter=interpreter))
            if any(item['interpreter'] == '/init' or '.exe' in item['interpreter'].lower() for item in registrations):
                paths.append('binfmt_misc:Windows-interpreter')
        return result('windows-interop', 'REVIEW' if paths or interop else 'SKIP' if truncated else 'PASS',
                      'Windows/WSL 入口特征需核对；未执行解释器或 Windows 命令' if paths or interop else '未发现典型 Windows/WSL 入口',
                      paths=paths, registrations=registrations, truncated=truncated, wsl_interop_environment=interop)
    observe('windows-interop', windows)
    def gpu_check():
        candidates = ['/dev/' + name for name in sorted(os.listdir('/dev'))
                      if name == 'dxg' or re.fullmatch(r'nvidia[0-9]+', name)]
        if Path('/dev/dri').is_dir():
            candidates += [str(item) for item in Path('/dev/dri').iterdir() if re.fullmatch(r'(card|renderD)[0-9]+', item.name)]
        devices = [path for path in candidates if stat.S_ISCHR(os.stat(path).st_mode)]
        invalid = sorted(set(candidates) - set(devices))
        status = ('PASS' if bool(devices) == (gpu == 'on') else 'FAIL') if gpu != 'unknown' else 'INFO'
        return result('gpu-expectation', 'REVIEW' if invalid else status,
                      'GPU 为获准资源例外；核对显式开关预期及设备类型', expected=gpu, devices=devices, invalid_nodes=invalid)
    observe('gpu-expectation', gpu_check)
    observe('network-expectation', lambda: network_check(network))
    with tempfile.TemporaryDirectory(prefix='mas-guest-security-') as work:
        for name in DEVICES:
            emit(bounded_probe('device', name, work, timeout))
        for path in CONTROLS:
            emit(bounded_probe('control', path, work, timeout))
        for path in READ_ENDPOINTS:
            emit(bounded_probe('read-endpoint', path, work, timeout))
    emit(result('network-policy', 'INFO', '已核对本地接口与路由；流量和登录策略另议，此脚本不扫描网络、不尝试登录'))


def publish_report(path, report):
    """Publish a complete private report without replacing an existing destination."""
    data = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    fd, name = tempfile.mkstemp(prefix='.guest-security-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.link(name, path)
    finally:
        os.unlink(name)


class ChallengeReport:
    """Separate observations from assertions; incomplete evidence never passes."""
    def __init__(self, purpose, *, write=None, diagnostic=None, **metadata):
        self.write = write or (lambda message: print(message, flush=True))
        self.diagnostic = diagnostic or (lambda message: print(message, file=sys.stderr, flush=True))
        self.started = time.monotonic()
        self.data = dict(schema=2, purpose=purpose, checks=[], observations=[], **metadata)

    def emit(self, item):
        item = dict(item)
        original = item['status']
        if original == 'INFO':
            item.pop('status')
            self.data['observations'].append(item)
            label = '记录'
        else:
            item['status'] = 'PASS' if original == 'PASS' else 'FAIL'
            if original != 'PASS':
                item.setdefault('failure_kind', 'execution' if original == 'ERROR' else
                                'verification' if original in ('SKIP', 'REVIEW') else 'boundary')
                if original in ('SKIP', 'REVIEW'):
                    item['message'] = '验证未通过：' + item['message']
            self.data['checks'].append(item)
            label = '通过' if item['status'] == 'PASS' else '失败'
        self.write('[' + label + '] ' + terminal_text(item['check']) + '：' + terminal_text(item['message']))
        self.write('  方法：' + terminal_text(item['method']))
        if item['evidence']:
            self.write('  观察：' + terminal_text(json.dumps(item['evidence'], ensure_ascii=False)))
        if original == 'ERROR':
            self.diagnostic('  测试未能完成此项验证。')
            for key in ('native_error', 'native_stderr'):
                if item['evidence'].get(key):
                    self.diagnostic('  ' + key + ': ' + terminal_text(str(item['evidence'][key])))

    def finish(self, path, interrupted=False):
        failures = [item for item in self.data['checks'] if item['status'] == 'FAIL']
        errors = any(item.get('failure_kind') == 'execution' for item in failures)
        code = 130 if interrupted else 2 if errors else 1 if failures else 0
        counts = {status: sum(item['status'] == status for item in self.data['checks']) for status in ('PASS', 'FAIL')}
        self.data.update(elapsed=time.monotonic()-self.started, exit_code=code, counts=counts,
                         conclusion='checks_failed' if failures else 'checks_passed',
                         scope='结论仅适用于列出的检查与当次观察；环境记录不计为测试。')
        self.write('\n测试汇总：通过 ' + str(counts['PASS']) + '，失败 ' + str(counts['FAIL']))
        self.write('结论：' + ('测试中断。' if interrupted else '检查未通过，请查看失败原因。' if failures else '本次列出的检查全部通过。'))
        try:
            publish_report(path, self.data)
            self.write('报告：' + terminal_text(str(path)))
        except OSError as exc:
            self.diagnostic('报告写入失败：' + terminal_text(str(exc)))
            return 2
        return code


def report_path(value, prefix):
    path = (value or Path(prefix + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.json')).absolute()
    if any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
        raise ValueError('报告路径不允许控制字符')
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise ValueError('报告路径已存在或父目录不可用：' + str(path))
    return path


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0].startswith('--_'):
        try:
            environment_check()
            if args[0] == '--_probe' and len(args) == 4:
                item = active_probe(*args[1:])
            elif args[0] == '--_canary' and len(args) == 3 and re.fullmatch(r'[0-9]+', args[1]):
                canary = json.loads(args[2])
                validate_reference(dict(schema=1, namespaces=namespace_ids(), canaries=[canary]))
                item = canary_check(int(args[1]), canary)
            elif args[0] == '--_socket' and len(args) == 3:
                references = json.loads(args[2])
                validate_reference(dict(schema=1, namespaces=namespace_ids(), sockets=references))
                if not args[1].startswith('/') or any(ord(c) < 32 or ord(c) == 127 for c in args[1]):
                    raise ValueError('socket 路径无效')
                item = socket_check(args[1], references)
            elif args[0] == '--_devlxd' and len(args) == 2 and args[1] in DEVLXD_ENDPOINTS:
                item = devlxd_check(args[1])
            else:
                raise ValueError('内部探测参数无效')
            print(json.dumps(item, ensure_ascii=False))
            return 0
        except Exception as exc:
            print(terminal_text(str(exc)), file=sys.stderr)
            return 2
    parser = argparse.ArgumentParser(add_help=False, description='在 LXD 容器内检查宿主资源隔离边界；不会写入内核控制接口或执行 Windows 命令。')
    parser.add_argument('-h', '--help', action='help', help='显示帮助并退出')
    parser.add_argument('--report', type=Path, help='JSON 报告路径；已存在则报错，默认创建唯一文件')
    parser.add_argument('--gpu', choices=('on', 'off', 'unknown'), default='unknown', help='容器的 GPU 开关预期（默认 unknown）')
    parser.add_argument('--timeout', type=float, default=3, help='每项设备/控制/socket/API/标记探测超时（1–10 秒，默认 3）')
    options = parser.parse_args(args)
    if not 1 <= options.timeout <= 10:
        parser.error('--timeout 必须为 1–10 秒')
    report = ChallengeReport('guest-boundary-probe', gpu_expected=options.gpu)
    interrupted = False
    try:
        path = report_path(options.report, 'guest-security-')
    except ValueError as exc:
        print(terminal_text(str(exc)), file=sys.stderr)
        return 2
    try:
        environment_check()
        print('\n容器安全边界测试（以容器 root 执行）\n', flush=True)
        run_checks(options.gpu, options.timeout, report.emit)
    except KeyboardInterrupt:
        interrupted = True
        report.emit(result('execution', 'ERROR', '测试已中断；保留已完成的检查'))
    except Exception as exc:
        report.emit(result('execution', 'ERROR', '测试未完成', native_error=str(exc)))
    return report.finish(path, interrupted)


if __name__ == '__main__':
    raise SystemExit(main())
