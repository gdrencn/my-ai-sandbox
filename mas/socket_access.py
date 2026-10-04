"""Installer-only preparation of the LXD snap's persistent local socket group."""
import grp
import os
from pathlib import Path
import shlex
import stat
import tempfile
import time

from .core import Error
from .i18n import t

UNIT = 'snap.lxd.daemon.unix.socket'
SOCKET = Path('/var/snap/lxd/common/lxd/unix.socket')
CONFIG = Path('/var/snap/lxd/common/config')
DROPIN = Path('/etc/systemd/system') / (UNIT + '.d') / 'mas.conf'
HEADER = '# Managed by my-ai-sandbox: LXD socket access\n'


def daemon_group(config=CONFIG):
    """Read snap's generated settings as data, never execute shell configuration."""
    name = 'lxd'
    if config.exists():
        for line in config.read_text().splitlines():
            if line.startswith('daemon_group='):
                try:
                    values = shlex.split(line.partition('=')[2], comments=True)
                except ValueError as exc:
                    raise Error(t('socket_config_invalid', path=config)) from exc
                if len(values) > 1:
                    raise Error(t('socket_config_invalid', path=config))
                name = (values[0] if values else '') or 'lxd'
    if not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-$' for c in name):
        raise Error(t('socket_config_invalid', path=config))
    try:
        return grp.getgrnam(name)
    except KeyError as exc:
        raise Error(t('socket_group_missing', group=name)) from exc


def content(group):
    return HEADER + '[Socket]\nSocketGroup=' + group + '\n'


def properties(run, unit=UNIT):
    result = run(['systemctl', 'show', unit, '-p', 'LoadState', '-p', 'SocketGroup',
                  '-p', 'SocketMode', '-p', 'Listen'], capture=True, display=False)
    return dict(line.split('=', 1) for line in result.splitlines() if '=' in line)


def check_unit(values, socket=SOCKET):
    if values.get('LoadState') != 'loaded' or values.get('Listen') != str(socket) + ' (Stream)' or values.get('SocketMode') != '0660':
        raise Error(t('socket_unit_conflict'))


def check_paths(dropin):
    for path in (dropin, *dropin.parents):
        if path.is_symlink():
            raise Error(t('socket_config_invalid', path=path))
    if dropin.exists():
        text = dropin.read_text()
        lines = text.splitlines()
        if (len(lines) != 3 or lines[0] + '\n' != HEADER or lines[1] != '[Socket]'
                or not lines[2].startswith('SocketGroup=') or text != content(lines[2].partition('=')[2])):
            raise Error(t('socket_config_invalid', path=dropin))


def socket_info(socket=SOCKET):
    try:
        info = socket.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o660:
        raise Error(t('socket_metadata_invalid', path=socket))
    return info


def ready(group, values, dropin=DROPIN, socket=SOCKET):
    check_unit(values, socket)
    check_paths(dropin)
    info = socket_info(socket)
    return (dropin.exists() and dropin.read_text() == content(group.gr_name)
            and values.get('SocketGroup') in (group.gr_name, str(group.gr_gid))
            and info is not None and info.st_gid == group.gr_gid)


def configure(run, *, group=None, dropin=DROPIN, socket=SOCKET, unit=UNIT):
    """Privileged helper; no daemon restart, no chmod, no changes to other sockets."""
    group = group or daemon_group()
    values = properties(run, unit)
    check_unit(values, socket)
    check_paths(dropin)
    info = socket_info(socket)
    if info is not None and info.st_gid not in (0, group.gr_gid):
        raise Error(t('socket_metadata_invalid', path=socket))
    if not dropin.exists() or dropin.read_text() != content(group.gr_name):
        dropin.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=dropin.parent, prefix='.mas-socket-')
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(content(group.gr_name)); stream.flush(); os.fsync(stream.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, dropin)
        finally:
            Path(temporary).unlink(missing_ok=True)
    # Reload also recovers an interrupted preceding configuration attempt.
    run(['systemctl', 'daemon-reload'], display=False)
    values = properties(run, unit)
    check_unit(values, socket)
    if values.get('SocketGroup') not in (group.gr_name, str(group.gr_gid)):
        raise Error(t('socket_unit_conflict'))
    run(['systemctl', 'start', unit], display=False)
    deadline = time.monotonic() + 600
    while True:
        info = socket_info(socket)
        if info is not None:
            if info.st_gid == group.gr_gid:
                return
            if info.st_gid != 0:
                raise Error(t('socket_metadata_invalid', path=socket))
            os.chown(socket, -1, group.gr_gid, follow_symlinks=False)
        if time.monotonic() >= deadline:
            raise Error(t('socket_wait_failed'))
        time.sleep(1)
