#!/usr/bin/env python3
"""Independent, non-destructive LXD guest boundary probes (Python 3.10+)."""
import argparse
from collections import Counter
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
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
    'kernel-log': (stat.S_IFCHR, 1, 11),
    'kvm': (stat.S_IFCHR, 10, 232),
    'host-disk': (stat.S_IFBLK, 8, 0),
}
CONTROLS = (
    '/proc/sysrq-trigger', '/proc/sys/kernel/modprobe',
    '/proc/sys/kernel/kexec_load_disabled', '/proc/sys/vm/drop_caches',
    '/sys/power/state',
)
SOCKETS = (
    '/var/snap/lxd/common/lxd/unix.socket', '/var/lib/lxd/unix.socket',
    '/run/lxd/unix.socket', '/run/docker.sock', '/run/containerd/containerd.sock',
    '/run/podman/podman.sock', '/run/libvirt/libvirt-sock',
)
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
        'devlxd': '检查 /dev/lxd/sock 是否可见，区分实例接口与宿主管理接口',
        'windows-interop': '检查 /mnt/c/Windows、/mnt/c/Users、WSLInterop、/init 和 WSL_INTEROP',
        'gpu-expectation': '列出 /dev/dxg 与 /dev/nvidiaN，核对显式 GPU 开关预期',
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
    if check.startswith('namespace:'):
        return '读取 /proc/self/ns/' + check.split(':', 1)[1] + '，有宿主参照时比较标识'
    if check.startswith('management-socket:'):
        return ('检查 ' + check.split(':', 1)[1] + '；存在时尝试 Unix socket 连接并立即关闭，不发送请求')
    if check.startswith('gpu-readonly:'):
        return '读取 mountinfo，核对 ' + check.split(':', 1)[1] + ' 的只读挂载选项'
    if check.startswith('host-canary:'):
        return '尝试直接路径、/proc/1/root 与 /proc/self/root 路径读取，比较唯一标记 SHA-256'
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
    return Path(path).read_text(encoding='utf-8', errors='replace')


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
        if kind == 'device':
            mode, major, minor = DEVICES[value]
            path = os.path.join(work, value)
            os.mknod(path, mode | 0o600, os.makedev(major, minor))
            step = 'open'
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
        elif kind == 'control' and value in CONTROLS:
            fd = os.open(value, os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        else:
            raise ValueError('未知的内部探测')
        os.close(fd)
        if kind == 'device':
            return result(check, 'FAIL', '能够打开未授权设备；未读取、写入或执行 ioctl', step=step)
        return result(check, 'REVIEW', '能够打开内核写入口；未写入，实际写权限尚未证实', step=step)
    except OSError as exc:
        return denied_result(check, step, exc)


def bounded_probe(kind, value, work, timeout):
    command = [sys.executable, str(Path(__file__).resolve()), '--_probe', kind, value, work]
    try:
        child = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return result(kind + ':' + value, 'ERROR', '探测超时，不能当作权限拒绝', timeout=timeout,
                      native_stdout=exc.stdout.decode(errors='replace') if exc.stdout else '',
                      native_stderr=exc.stderr.decode(errors='replace') if exc.stderr else '')
    try:
        item = json.loads(child.stdout)
        if (child.returncode or not isinstance(item, dict)
                or item.get('check') != kind + ':' + value or item.get('status') not in STATUS_TEXT
                or not isinstance(item.get('method'), str) or not isinstance(item.get('message'), str)
                or not isinstance(item.get('evidence'), dict)):
            raise ValueError('子进程返回内容无效')
        return item
    except (ValueError, TypeError):
        return result(kind + ':' + value, 'ERROR', '探测子进程异常', returncode=child.returncode,
                      native_stdout=child.stdout, native_stderr=child.stderr)


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
    return (path == '/usr/lib/wsl/lib' or path.startswith('/usr/lib/wsl/lib/')
            or path.startswith('/usr/lib/wsl/drivers/'))


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


def socket_check(path):
    check = 'management-socket:' + path
    try:
        mode = os.stat(path).st_mode
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
        return result(check, 'REVIEW', '可以连接；未发送管理请求，需确认服务属于宿主还是容器')
    except OSError as exc:
        if exc.errno in DENIED:
            return denied_result(check, 'connect', exc)
        return result(check, 'REVIEW', 'socket 可见但连接未成功，不能据此证明服务隔离',
                      native_error=str(exc), errno=exc.errno)


def canary_check(index, item):
    attempts = []
    for prefix in ('', '/proc/1/root', '/proc/self/root'):
        path = prefix + item['path']
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
            with os.fdopen(fd, 'rb') as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    attempts.append(dict(path=path, outcome='not-regular'))
                    continue
                data = source.read(65537)
            digest = hashlib.sha256(data).hexdigest()
            attempts.append(dict(path=path, outcome='readable', sha256=digest, bytes=len(data)))
            if len(data) <= 65536 and digest == item['sha256']:
                return result('host-canary:' + str(index), 'FAIL',
                              '读到了宿主提供的唯一标记文件', attempts=attempts)
        except OSError as exc:
            if exc.errno not in DENIED | {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}:
                return result('host-canary:' + str(index), 'ERROR', '宿主标记探测异常',
                              native_error=str(exc), attempts=attempts)
            attempts.append(dict(path=path, outcome='unavailable', errno=exc.errno))
    readable = any(attempt['outcome'] in ('readable', 'not-regular') for attempt in attempts)
    return result('host-canary:' + str(index), 'REVIEW' if readable else 'PASS',
                  '同名对象可见，内容不符；需核对来源' if readable else '宿主标记不可读或不可见', attempts=attempts)


def run_checks(reference, gpu, timeout, emit):
    def add(item):
        emit(item)
    for name in ('uid', 'gid'):
        text = read_text('/proc/self/' + name + '_map')
        rows = mappings(text)
        safe = any(start == 0 for start, _, _ in rows) and all(outside > 0 for _, outside, _ in rows)
        add(result(name + '-map', 'PASS' if safe else 'FAIL', '容器 root 不应映射到宿主 root', mapping=text))
    status = dict(line.split(':', 1) for line in read_text('/proc/self/status').splitlines() if ':' in line)
    seccomp = status.get('Seccomp', '').strip()
    add(result('seccomp', 'PASS' if seccomp == '2' else 'FAIL', '检查实际 seccomp 过滤状态', mode=seccomp))
    add(result('capabilities', 'INFO', '能力位属于当前 namespace；不能单凭它判断拥有宿主权限',
               effective=status.get('CapEff', '').strip(), bounding=status.get('CapBnd', '').strip()))
    for name, value in namespace_ids().items():
        expected = reference['namespaces'][name] if reference else None
        add(result('namespace:' + name, ('PASS' if value != expected else 'FAIL') if expected else 'SKIP',
                   '与宿主 namespace 比较' if expected else '无宿主参照，仅记录，尚未验证隔离',
                   guest=value, host=expected))
    profile, enabled = None, None
    for path, key in (('/proc/self/attr/current', 'profile'), ('/sys/module/apparmor/parameters/enabled', 'enabled')):
        try:
            value = read_text(path).strip()
            if key == 'profile':
                profile = value
            else:
                enabled = value
        except OSError:
            pass
    add(result('apparmor', 'INFO' if enabled == 'N' or (profile and profile.startswith('lxd-')) else 'REVIEW',
               '如实记录 AppArmor；未启用不冒充已生效', enabled=enabled, profile=profile))
    with open('/dev/null', 'rb') as source:
        if source.read(1) != b'':
            raise ValueError('/dev/null 行为不符')
    with open('/dev/zero', 'rb') as source:
        if source.read(1) != b'\0':
            raise ValueError('/dev/zero 行为不符')
    if not stat.S_ISDIR(os.stat('/sys').st_mode):
        raise ValueError('/sys 不是目录')
    add(result('basic-interfaces', 'PASS', '/dev/null、/dev/zero、/proc 和 /sys 是正常容器接口',
               sys_present=True))
    for item in mount_checks(parse_mounts(read_text('/proc/self/mountinfo'))):
        add(item)
    for path in SOCKETS:
        add(socket_check(path))
    add(result('devlxd', 'INFO', '实例内 devlxd 与宿主 LXD 管理 socket 不同，按当前兼容策略保留',
               visible=bool(visible_paths(('/dev/lxd/sock',)))))
    windows = visible_paths(('/mnt/c/Windows', '/mnt/c/Users', '/proc/sys/fs/binfmt_misc/WSLInterop', '/init'))
    add(result('windows-interop', 'REVIEW' if windows else 'PASS',
               '发现 Windows/WSL 入口特征，需核对；未运行 Windows 命令' if windows else '未发现典型 Windows/WSL 入口',
               paths=windows, wsl_interop_environment=os.environ.get('WSL_INTEROP')))
    devices = ['/dev/' + name for name in sorted(os.listdir('/dev'))
               if name == 'dxg' or re.fullmatch(r'nvidia[0-9]+', name)]
    add(result('gpu-expectation', ('PASS' if bool(devices) == (gpu == 'on') else 'FAIL') if gpu != 'unknown' else 'INFO',
               'GPU 是获准的资源例外；仅检查显式开关预期，不将其判为越界', expected=gpu, devices=devices))
    if reference and reference.get('canaries'):
        for index, item in enumerate(reference['canaries']):
            add(canary_check(index, item))
    else:
        add(result('host-canaries', 'SKIP', '未提供宿主唯一标记；常见路径检查不能替代任意宿主文件验证'))
    with tempfile.TemporaryDirectory(prefix='mas-guest-security-') as work:
        for name in DEVICES:
            add(bounded_probe('device', name, work, timeout))
        for path in CONTROLS:
            add(bounded_probe('control', path, work, timeout))
    add(result('network-policy', 'INFO', '网络流量及网络登录另议；此脚本不扫描网络、不尝试登录'))


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


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == '--_probe':
        if len(args) != 4:
            return 2
        try:
            environment_check()
            print(json.dumps(active_probe(*args[1:]), ensure_ascii=False))
            return 0
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 2
    parser = argparse.ArgumentParser(add_help=False, description='在 LXD 容器内检查宿主资源隔离边界；不会写入内核控制接口或执行 Windows 命令。')
    parser.add_argument('-h', '--help', action='help', help='显示帮助并退出')
    parser.add_argument('--report', type=Path, help='JSON 报告路径；已存在则报错，默认创建唯一文件')
    parser.add_argument('--host-reference', type=Path, help='可选宿主 namespace/唯一标记参照 JSON')
    parser.add_argument('--gpu', choices=('on', 'off', 'unknown'), default='unknown', help='容器的 GPU 开关预期（默认 unknown）')
    parser.add_argument('--timeout', type=float, default=3, help='每项设备/控制接口探测的超时秒数（1–10，默认 3）')
    options = parser.parse_args(args)
    if not 1 <= options.timeout <= 10:
        parser.error('--timeout 必须为 1–10 秒')
    path = (options.report or Path('guest-security-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.json')).absolute()
    started = time.monotonic()
    report = dict(schema=SCHEMA, purpose='guest-boundary-probe', gpu_expected=options.gpu, checks=[])
    def emit(item):
        report['checks'].append(item)
        print('[' + STATUS_TEXT[item['status']] + '] ' + terminal_text(item['check'])
              + '：' + terminal_text(item['message']), flush=True)
        print('  方法：' + terminal_text(item['method']), flush=True)
        if item['evidence']:
            print('  观察：' + json.dumps(item['evidence'], ensure_ascii=False), flush=True)
        if item['status'] == 'ERROR':
            for key in ('native_error', 'native_stderr'):
                if item['evidence'].get(key):
                    print('  ' + key + ': ' + json.dumps(item['evidence'][key], ensure_ascii=False),
                          file=sys.stderr, flush=True)
    try:
        if any(ord(character) < 32 or ord(character) == 127 for character in str(path)):
            raise ValueError('报告路径不允许控制字符')
        if path.exists() or path.is_symlink() or not path.parent.is_dir():
            raise ValueError('报告路径已存在或父目录不可用：' + str(path))
        reference = validate_reference(json.loads(options.host_reference.read_text())) if options.host_reference else None
        environment_check()
        print('\n容器安全边界测试（以容器 root 执行）\n', flush=True)
        run_checks(reference, options.gpu, options.timeout, emit)
    except Exception as exc:
        emit(result('execution', 'ERROR', '测试未完成', native_error=str(exc)))
    counts = Counter(item['status'] for item in report['checks'])
    code = 2 if counts['ERROR'] else 1 if counts['FAIL'] else 0
    report.update(elapsed=time.monotonic() - started, exit_code=code,
                  counts={status: counts[status] for status in STATUS_TEXT},
                  conclusion='boundary_failure' if counts['FAIL'] else 'incomplete' if counts['ERROR'] else 'no_confirmed_breach',
                  limitation='不证明不存在漏洞；REVIEW/SKIP 项尚未验证，不能算通过。')
    print('\n测试汇总：' + '，'.join(STATUS_TEXT[status] + ' ' + str(counts[status]) for status in STATUS_TEXT))
    print('结论：' + ('发现边界失败。' if counts['FAIL'] else '测试不完整。' if counts['ERROR'] else '未发现明确越界；需核对和未验证项仍需单独判断。'))
    try:
        publish_report(path, report)
        print('报告：' + str(path))
    except OSError as exc:
        print('报告写入失败：' + str(exc), file=sys.stderr)
        return 2
    return code


if __name__ == '__main__':
    raise SystemExit(main())
