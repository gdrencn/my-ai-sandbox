"""Per-user native LXD/SSHFS mounts; no container permission rewriting."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import threading
from urllib.parse import urlencode, quote
import uuid

from .core import Error, validate_target
from .i18n import t
from .diagnostics import cleanup_scope


def fuse_access_ready(path=Path('/etc/fuse.conf')):
    try:
        return any(line.split('#', 1)[0].strip() == 'user_allow_other' for line in path.read_text().splitlines())
    except FileNotFoundError:
        return False


def normalized(path):
    if not isinstance(path, str) or not path.startswith('/') or any(ord(c) < 32 or ord(c) == 127 for c in path) or '..' in path.split('/'):
        raise Error(t('fs_path_invalid'))
    return '/' + '/'.join(part for part in path.split('/') if part not in ('', '.'))


def overlaps(a, b):
    return a == b or a.startswith(b.rstrip('/') + '/') or b.startswith(a.rstrip('/') + '/')


def mounts():
    def decode(value):
        return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)
    result = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        before, after = line.split(' - ', 1)
        left, right = before.split(), after.split()
        result.append(dict(id=int(left[0]), destination=decode(left[4]), kind=right[0], source=decode(right[1])))
    return result


def process_identity(pid):
    try:
        parts = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        if parts[0] == 'Z':
            return None
        return dict(pid=pid, start=parts[19], boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    except (FileNotFoundError, ProcessLookupError):
        return None


def alive(identity):
    return bool(identity) and process_identity(identity['pid']) == identity


class Filesystems:
    def __init__(self, manager, root=None, state=None):
        self.manager = manager
        self.root = Path(root) if root else Path.home() / 'LXDCMFS'
        self.root = self.root.absolute()
        self.state = Path(state) if state else Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'my-ai-sandbox/filesystems'
        self.state = self.state.absolute()
        self.project = manager.lxd.project
        self.timeout = manager.lxd.timeout
        self._thread_lock = threading.RLock()
        self._lock_depth = 0

    def _private(self):
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.state.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Error(t('fs_state_private', path=self.state))

    def _load(self):
        try:
            path = self.state / 'mounts.json'
            if path.is_symlink():
                raise ValueError('symlink')
            data = json.loads(path.read_text())
            if data.get('version') != 1 or not isinstance(data.get('directories'), dict) or not isinstance(data.get('mounts'), list):
                raise ValueError('schema')
            for directory, identity in data['directories'].items():
                candidate = Path(directory)
                if str(candidate) != directory or (candidate != self.root and self.root not in candidate.parents) or '..' in candidate.parts:
                    raise ValueError('directory')
                legacy = isinstance(identity, list) and len(identity) == 2 and all(type(n) is int and n >= 0 for n in identity)
                current = isinstance(identity, dict) and set(identity) == {'fsid', 'inode', 'owner'} and all(type(n) is int and n >= 0 for n in identity.values())
                if not (legacy or current):
                    raise ValueError('directory identity')
            seen = set()
            for entry in data['mounts']:
                if not isinstance(entry, dict) or not re.fullmatch('[a-f0-9]{32}', entry['id']):
                    raise ValueError('entry')
                if set(entry) - {'id', 'target', 'project', 'path', 'destination', 'source', 'default', 'prepared', 'created', 'listener', 'sshfs', 'mount_id', 'work_created'}:
                    raise ValueError('unknown field')
                if entry['id'] in seen:
                    raise ValueError('duplicate id')
                seen.add(entry['id'])
                validate_target(entry['target'])
                if type(entry['default']) is not bool or entry['source'] not in ('', 'mas-' + entry['id'] + '@127.0.0.1:' + entry['path']):
                    raise ValueError('source/default')
                if 'work_created' in entry and type(entry['work_created']) is not bool:
                    raise ValueError('work directory ownership')
                if 'prepared' in entry and type(entry['prepared']) is not bool:
                    raise ValueError('prepared')
                if 'mount_id' in entry and (type(entry['mount_id']) is not int or entry['mount_id'] <= 0):
                    raise ValueError('mount id')
                created = entry.get('created', [])
                if not isinstance(created, list) or any(not isinstance(name, str) or str(Path(name)) != name or '..' in Path(name).parts or (Path(name) != self.root and self.root not in Path(name).parents) or not (Path(name) == Path(entry['destination']) or Path(name) in Path(entry['destination']).parents) for name in created):
                    raise ValueError('created paths')
                for kind in ('listener', 'sshfs'):
                    identity = entry.get(kind)
                    if identity is not None and (not isinstance(identity, dict) or set(identity) != {'pid', 'start', 'boot'} or type(identity['pid']) is not int or identity['pid'] <= 0 or not isinstance(identity['start'], str) or not identity['start'].isdigit() or not isinstance(identity['boot'], str) or not re.fullmatch('[a-f0-9-]{36}', identity['boot'])):
                        raise ValueError('process identity')
                if normalized(entry['path']) != entry['path'] or not isinstance(entry['project'], str) or not entry['project'] or any(ord(c) < 32 for c in entry['project']):
                    raise ValueError('path')
                if entry['destination'] != str(self.root / entry['target'] / entry['path'].lstrip('/')):
                    raise ValueError('destination')
            return data
        except FileNotFoundError:
            return dict(version=1, directories={}, mounts=[])
        except (ValueError, KeyError, TypeError, AttributeError, Error) as exc:
            raise Error(t('fs_state_invalid', path=self.state)) from exc

    def _save(self, data):
        fd, name = tempfile.mkstemp(dir=self.state, prefix='.mounts-')
        with cleanup_scope(lambda: Path(name).unlink(missing_ok=True)):
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.state / 'mounts.json')
            directory = os.open(self.state, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    @contextmanager
    def locked(self):
        # Reentrant within this shared Filesystems object, exclusive across
        # threads/processes. Each nested call reloads committed registry state.
        if not self._thread_lock.acquire(timeout=self.timeout):
            raise Error(t('fs_lock_timeout'))
        fd = None
        entered = False
        try:
            if not self._lock_depth:
                self._private()
                fd = os.open(self.state / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                deadline = time.monotonic() + self.timeout
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise Error(t('fs_lock_timeout'))
                        time.sleep(1)
            self._lock_depth += 1
            entered = True
            yield self._load()
        finally:
            if entered:
                self._lock_depth -= 1
            if fd is not None:
                os.close(fd)
            self._thread_lock.release()

    def _entries(self, data, target):
        return [e for e in data['mounts'] if e['target'] == target and e['project'] == self.project]

    def _target(self, target, recovery=False):
        validate_target(target)
        if not recovery:
            self.manager.require(target)

    def _home(self, target):
        content = self.manager.lxd.command(['file', 'pull', 'local:' + target + '/etc/passwd', '-'])
        for line in content.splitlines():
            fields = line.split(':')
            if len(fields) == 7 and fields[0] == 'sandbox':
                return normalized(fields[5])
        raise Error(t('fs_home_missing', target=target))

    def _directory(self, target, path):
        # Native files API returns a JSON directory listing, but symlinks return
        # their link target. Check each component so aliases cannot bypass overlap.
        for part in dict.fromkeys([*reversed(PurePosixPath(path).parents), PurePosixPath(path)]):
            query = '/1.0/instances/' + quote(target, safe='') + '/files?' + urlencode(dict(project=self.project, path=str(part)))
            try:
                value = json.loads(self.manager.lxd.command(['query', query]))
            except (ValueError, Error) as exc:
                raise Error(t('fs_directory', path=part)) from exc
            if not isinstance(value, list) or any(not isinstance(name, str) for name in value):
                raise Error(t('fs_directory', path=part))

    @staticmethod
    def _identity(path):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise Error(t('fs_conflict', path=path))
        return dict(fsid=os.statvfs(path).f_fsid, inode=info.st_ino, owner=info.st_uid)

    def _same_directory(self, path, identity):
        current = self._identity(path)
        if isinstance(identity, list):
            info = path.lstat()
            return identity == [info.st_dev, info.st_ino]
        return identity == current

    def _make(self, data, destination, entry=None):
        if os.path.lexists(destination):
            raise Error(t('fs_conflict', path=destination))
        for part in [self.root, *[p for p in reversed(destination.parents) if self.root in p.parents], destination]:
            key = str(part)
            if os.path.lexists(part):
                if not self._same_directory(part, data['directories'].get(key)):
                    raise Error(t('fs_conflict', path=part))
            else:
                part.mkdir(mode=0o700)
                data['directories'][key] = self._identity(part)
                if entry is not None:
                    entry.setdefault('created', []).append(key)
                self._save(data)

    def _reclaim(self, data, destination):
        for part in [destination, *destination.parents]:
            if part != self.root and self.root not in part.parents:
                break
            key = str(part)
            identity = data['directories'].get(key)
            if identity is None:
                continue
            if os.path.lexists(part):
                if not self._same_directory(part, identity):
                    raise Error(t('fs_conflict', path=part))
                try:
                    part.rmdir()
                except OSError:
                    if part == destination:
                        raise Error(t('fs_not_empty', path=part))
                    break
            del data['directories'][key]
            self._save(data)

    def _actual(self, entry):
        return [item for item in mounts() if item['destination'] == entry['destination']]

    def _matching(self, entry, actual):
        return len(actual) == 1 and actual[0]['kind'] == 'fuse.sshfs' and actual[0]['source'] == entry['source'] and ('mount_id' not in entry or actual[0]['id'] == entry['mount_id'])

    def _status(self, entry):
        actual = self._actual(entry)
        if not actual:
            return 'residual'
        if not self._matching(entry, actual):
            return 'conflict'
        return 'mounted' if alive(entry.get('listener')) and alive(entry.get('sshfs')) else 'disconnected'

    def list(self, target):
        self._target(target, recovery=True)
        if not self.state.exists():
            return []
        with self.locked() as data:
            return [dict(path=e['path'], destination=e['destination'], status=self._status(e), default=e['default']) for e in self._entries(data, target)]

    def guard_delete(self, target):
        self.require_no_mounts(target)

    def require_no_mounts(self, target):
        if self.list(target):
            raise Error(t('fs_before_transition', target=target))

    @contextmanager
    def deletion_guard(self, target):
        with self.locked() as data:
            if self._entries(data, target):
                raise Error(t('fs_before_transition', target=target))
            yield

    def _wait(self, action, target, probe, diagnostics=None, final=True, *, started=None, deadline=None, ready_state=None):
        started = time.monotonic() if started is None else started
        deadline = started + self.timeout if deadline is None else deadline
        outcome = 'error'
        observation = 'waiting'
        try:
            while True:
                tick = time.monotonic()
                if tick >= deadline:
                    raise Error(t('fs_timeout', target=target))
                done = probe()
                observation = (ready_state or ('mounted' if action == 'mountfs' else 'unmounted')) if done else 'waiting'
                self.manager.emit(dict(action=action, target=target, status='waiting', observation=observation, elapsed=time.monotonic()-started))
                if done:
                    outcome = 'ok'
                    return done
                time.sleep(max(0, min(1-(time.monotonic()-tick), deadline-time.monotonic())))
        finally:
            if final:
                self.manager.emit(dict(action=action, target=target, status=outcome, observation=observation, elapsed=time.monotonic()-started, native_stderr=diagnostics() if diagnostics and outcome == 'ok' else ''))

    def _spawn(self, args, out, err, password=None):
        with out.open('ab') as stdout, err.open('ab') as stderr:
            child = subprocess.Popen(args, stdin=subprocess.PIPE if password is not None else subprocess.DEVNULL,
                                     stdout=stdout, stderr=stderr, start_new_session=True, cwd=out.parent,
                                     env={**os.environ, 'LC_ALL': 'C'})
        if password is not None:
            try:
                child.stdin.write((password+'\n').encode())
                child.stdin.close()
            except BrokenPipeError:
                pass
        return child

    def _terminate(self, identity, progress=None):
        if alive(identity):
            try:
                os.kill(identity['pid'], signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic()+self.timeout
            while alive(identity):
                if progress is not None:
                    progress()
                if time.monotonic() >= deadline:
                    raise Error(t('fs_process_timeout'))
                time.sleep(1)
        if identity:
            try:
                os.waitpid(identity['pid'], os.WNOHANG)
            except ChildProcessError:
                pass

    def _prepare_mount(self, data, entry, work):
        """Journal intent before creating owned resources, within failure protection."""
        data['mounts'].append(entry)
        self._save(data)
        work.mkdir(mode=0o700)
        entry['work_created'] = True
        self._save(data)
        self._make(data, Path(entry['destination']), entry)
        entry['prepared'] = True
        self._save(data)

    def _start_listener(self, data, entry, work):
        username = 'mas-' + entry['id']
        entry['source'] = username + '@127.0.0.1:' + entry['path']
        listener = self._spawn(self.manager.lxd.prefix + ['file', 'mount', 'local:'+entry['target'],
            '--listen', '127.0.0.1:0', '--auth-user', username], work/'listener.out', work/'listener.err')
        entry['listener'] = process_identity(listener.pid)
        self._save(data)
        return listener

    def _listener_details(self, listener, work):
        if listener.poll() is not None:
            raise Error((work/'listener.err').read_text().strip() or t('fs_listener_failed'))
        output = (work/'listener.out').read_text()
        port = re.search(r'SSH SFTP listening on 127\.0\.0\.1:(\d+)', output)
        password = re.search(r'password "([^"\n]+)"', output)
        return (port[1], password[1]) if port and password else None

    def _start_sshfs(self, data, entry, work, connection):
        port, password = connection
        known_hosts = str(work/'known_hosts').replace('\\', '\\\\').replace('"', '\\"')
        sshfs = self._spawn(['sshfs', entry['source'], entry['destination'], '-f', '-p', port,
            '-o', 'password_stdin', '-o', 'allow_root', '-o', 'StrictHostKeyChecking=accept-new',
            '-o', 'UserKnownHostsFile="'+known_hosts+'"', '-o', 'GlobalKnownHostsFile=/dev/null',
            '-o', 'IdentityAgent=none', '-o', 'PubkeyAuthentication=no', '-o', 'PreferredAuthentications=password'],
            work/'sshfs.out', work/'sshfs.err', password)
        entry['sshfs'] = process_identity(sshfs.pid)
        self._save(data)
        return sshfs

    def _mount_observation(self, entry, listener, sshfs, work):
        if listener.poll() is not None:
            raise Error((work/'listener.err').read_text().strip() or t('fs_listener_failed'))
        if sshfs.poll() is not None:
            raise Error((work/'sshfs.err').read_text().strip() or t('fs_mount_failed'))
        actual = self._actual(entry)
        if actual and not self._matching(entry, actual):
            raise Error(t('fs_conflict', path=entry['destination']))
        return actual[0] if actual else None

    def mount(self, target, path=None, *, default_home=False):
        self._target(target)
        for program in ('sshfs', 'fusermount3'):
            if not shutil.which(program):
                raise Error(t('fs_dependency', program=program))
        if os.geteuid() != 0 and not fuse_access_ready():
            raise Error(t('fuse_setup_required'))
        default = path is None or default_home
        path = self._home(target) if path is None else normalized(path)
        destination = self.root / target / path.lstrip('/')
        with self.locked() as data:
            self.manager.require(target)
            self._directory(target, path)
            for entry in self._entries(data, target):
                if overlaps(path, entry['path']):
                    raise Error(t('fs_overlap', path=path, existing=entry['path']))
            if any(overlaps(str(destination), item['destination']) for item in mounts() if item['destination'] != '/' and str(self.root) in (item['destination'], *[str(p) for p in Path(item['destination']).parents])):
                raise Error(t('fs_conflict', path=destination))
            entry = dict(id=uuid.uuid4().hex, project=self.project, target=target, path=path,
                         destination=str(destination), default=default, source='', work_created=False)
            work = self.state / entry['id']
            started = time.monotonic()
            try:
                self._prepare_mount(data, entry, work)
                listener = self._start_listener(data, entry, work)
                # Both readiness waits consume the same original timeout budget.
                waiting = time.monotonic()
                deadline = waiting + self.timeout
                connection = self._wait('mountfs', target, lambda: self._listener_details(listener, work),
                    final=False, started=waiting, deadline=deadline, ready_state='waiting')
                sshfs = self._start_sshfs(data, entry, work, connection)
                actual = self._wait('mountfs', target, lambda: self._mount_observation(entry, listener, sshfs, work),
                    final=False, started=waiting, deadline=deadline)
                entry['mount_id'] = actual['id']
                self._save(data)
                diagnostics = ''.join((work/name).read_text() for name in ('listener.err', 'sshfs.err') if (work/name).exists())
            except BaseException:
                self.manager.emit(dict(action='mountfs', target=target, status='error', observation='residual', elapsed=time.monotonic()-started))
                try:
                    self._remove(data, entry)
                except (Error, OSError) as exc:
                    self.manager.emit(dict(action='mountfs', target=target, status='error', observation='residual', elapsed=0, native_stderr=str(exc)))
                raise
            self.manager.emit(dict(action='mountfs', target=target, status='ok', scope='function', observation='mounted', elapsed=time.monotonic()-started, native_stderr=diagnostics))
        return str(destination)

    def _owned_helper(self, pid, entry, kind):
        try:
            proc = Path('/proc') / str(pid)
            if proc.stat().st_uid != os.getuid():
                return False
            args = proc.joinpath('cmdline').read_bytes().rstrip(b'\0').decode().split('\0')
            if kind == 'listener':
                suffix = ['file', 'mount', 'local:' + entry['target'], '--listen', '127.0.0.1:0', '--auth-user', 'mas-' + entry['id']]
                return Path(args[0]).name == 'lxc' and args[-len(suffix):] == suffix
            return Path(args[0]).name == 'sshfs' and args[1:4] == [entry['source'], entry['destination'], '-f']
        except (OSError, UnicodeError):
            return False

    def _helpers(self, entry, kind):
        recorded = entry.get(kind)
        if recorded and alive(recorded) and not self._owned_helper(recorded['pid'], entry, kind):
            raise Error(t('fs_state_invalid', path=self.state))
        identities = []
        for proc in Path('/proc').iterdir():
            if proc.name.isdigit() and self._owned_helper(int(proc.name), entry, kind):
                identity = process_identity(int(proc.name))
                if identity:
                    identities.append(identity)
        return identities

    def _remove(self, data, entry):
        started = time.monotonic()
        outcome = 'error'
        try:
            self._cleanup(data, entry, started)
            outcome = 'ok'
        finally:
            self.manager.emit(dict(action='unmountfs', target=entry['target'], status=outcome, scope='function',
                observation='unmounted' if outcome == 'ok' else 'residual', elapsed=time.monotonic()-started))

    def _cleanup(self, data, entry, started):
        helpers = {kind: self._helpers(entry, kind) for kind in ('sshfs', 'listener')}
        actual = self._actual(entry)
        if actual:
            if not self._matching(entry, actual):
                raise Error(t('fs_conflict', path=entry['destination']))
            try:
                result = subprocess.run(['fusermount3', '-u', entry['destination']], text=True, capture_output=True, timeout=self.timeout)
            except subprocess.TimeoutExpired as exc:
                raise Error(t('fs_timeout', target=entry['target'])) from exc
            if result.returncode:
                raise Error(result.stderr.strip() or t('fs_unmount_failed'))
            self._wait('unmountfs', entry['target'], lambda: not self._actual(entry), final=False)
            if result.stderr:
                self.manager.emit(dict(action='unmountfs', target=entry['target'], status='waiting', observation='unmounted', elapsed=0, native_stderr=result.stderr))
        for kind in ('sshfs', 'listener'):
            for identity in helpers[kind]:
                if self._owned_helper(identity['pid'], entry, kind):
                    self._terminate(identity, lambda: self.manager.emit(dict(action='unmountfs', target=entry['target'], status='waiting', observation='waiting', elapsed=time.monotonic()-started)))
        if entry.get('prepared'):
            self._reclaim(data, Path(entry['destination']))
        elif entry.get('created'):
            self._reclaim(data, Path(entry['created'][-1]))
        work = self.state / entry['id']
        if work.exists():
            if not entry.get('work_created', True):
                raise Error(t('fs_conflict', path=work))
            # Only the private per-mount connection files, never container data.
            for name in ('listener.out', 'listener.err', 'sshfs.out', 'sshfs.err', 'known_hosts'):
                (work/name).unlink(missing_ok=True)
            work.rmdir()
        data['mounts'].remove(entry)
        self._save(data)

    def unmount(self, target, path=None):
        self._target(target, recovery=True)
        with self.locked() as data:
            entries = self._entries(data, target)
            if path is None:
                defaults = [e for e in entries if e['default']]
                if len(defaults) > 1:
                    raise Error(t('fs_default_ambiguous'))
                path = defaults[0]['path'] if defaults else self._home(target)
            path = normalized(path)
            entry = next((e for e in entries if e['path'] == path), None)
            if entry is None:
                raise Error(t('fs_not_mounted', path=path, paths=', '.join(e['path'] for e in entries) or '-'))
            self._remove(data, entry)
