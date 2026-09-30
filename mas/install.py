"""First-install setup. Existing LXD installations and profiles are preserved."""

from importlib.resources import files
import grp
import json

import os
from pathlib import Path
import pwd
import re
import shutil
import shlex
import subprocess
import sys
import tempfile

from .core import Error, LXD

from .i18n import t, Parser
from .diagnostics import cleanup_scope, emit_native, diagnostic_lines, failure_text
from . import __version__


def run(args, privileged=False, capture=False, display=True, label=None):
    if privileged and os.geteuid() != 0 and args[0] != "sudo":
        args = ["sudo", *args]
    if display:
        print(t("setup_command", command=" ".join(args)), flush=True)
    tty = None
    try:
        if privileged and os.geteuid() != 0 and not sys.stdin.isatty():
            try:
                tty = open("/dev/tty")
            except OSError:
                pass  # sudo itself decides whether and how authentication is needed.
        result = subprocess.run(args, stdin=tty, text=True, capture_output=capture, timeout=1800)
    except subprocess.TimeoutExpired as exc:
        raise Error(t('setup_timeout')) from exc
    finally:
        if tty:
            tty.close()
    if result.returncode:
        raise Error(failure_text(result.stdout, result.stderr) or t("setup_failed", command=label or " ".join(args)))
    if capture:
        emit_native('\n'.join(diagnostic_lines(result.stdout or '', result.stderr or '')))
    return result.stdout or ""


def dependency_script():
    return files('mas').joinpath('dependencies.sh').read_text()


def prepare_dependencies():
    script = dependency_script()
    packages = subprocess.check_output(['bash', '-c', script + '\nmas_missing_dependencies'], text=True).splitlines()
    if packages:
        labels = {name: t(key) for name, key in (
            ('MAS_APT_SETUP', 'apt_setup'), ('MAS_APT_DONE', 'apt_done'), ('MAS_APT_FAILED', 'apt_failed'))}
        assignments = '\n'.join(name + '=' + shlex.quote(value) for name, value in labels.items())
        run(['bash', '-o', 'pipefail', '-c', assignments + '\n' + script + '\nmas_install_dependencies'], display=False, label=t('apt_setup'))


def enable_fuse_access(path=Path('/etc/fuse.conf')):
    """Called with system privilege; preserve existing host FUSE configuration."""
    from .filesystems import fuse_access_ready
    if fuse_access_ready(path):
        return
    if path.is_symlink():
        raise Error(t('fuse_config_symlink', path=path))
    original = path.read_text() if path.exists() else ''
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.mas-fuse-')
    with cleanup_scope(lambda: Path(temporary).unlink(missing_ok=True)):
        with os.fdopen(fd, 'w') as stream:
            stream.write(original + ('\n' if original and not original.endswith('\n') else '') + 'user_allow_other\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        if path.exists():
            info = path.stat()
            os.chown(temporary, info.st_uid, info.st_gid)
        os.replace(temporary, path)


def prepare_fuse_access():
    from .filesystems import fuse_access_ready
    if fuse_access_ready():
        return
    print(t('fuse_setup'), flush=True)
    code = ('import sys;sys.path.insert(0,' + repr(str(Path(__file__).resolve().parent.parent)) + ');'
            'from mas.install import enable_fuse_access;enable_fuse_access()')
    run([sys.executable, '-c', code], privileged=True, display=False, label=t('fuse_setup'))


def prepare_socket_access():
    from .socket_access import daemon_group, properties, ready
    group = daemon_group()
    if ready(group, properties(run)):
        return group
    print(t('socket_setup'), flush=True)
    code = ('import sys;sys.path.insert(0,' + repr(str(Path(__file__).resolve().parent.parent)) + ');'
            'from mas.install import run;from mas.socket_access import configure;configure(run)')
    run([sys.executable, '-c', code], privileged=True, display=False, label=t('socket_setup'))
    if not ready(group, properties(run)):
        raise Error(t('socket_wait_failed'))
    return group


def stable_channel(info):
    candidates = []
    for line in info.splitlines():
        match = re.match(r"\s+(\S+/stable):\s+(\d+(?:\.\d+)+)(?:\S*)\s", line)
        if match:
            channel, version = match.groups()
            candidates.append((tuple(map(int, version.split("."))), channel != "latest/stable", channel))
    if not candidates:
        raise Error(t('stable_missing'))
    return max(candidates)[2]


def prepare_system():
    if sys.version_info < (3, 10):
        raise Error(t('python_required'))
    os_release = Path("/etc/os-release").read_text()
    if not re.search(r'^ID=["\']?ubuntu["\']?$', os_release, re.M):
        raise Error(t('ubuntu_required'))
    if Path("/proc/1/comm").read_text().strip() != "systemd":
        raise Error(t('systemd_required'))
    executable = shutil.which("lxd") or ("/snap/bin/lxd" if Path("/snap/bin/lxd").exists() else None)
    prepare_dependencies()
    prepare_fuse_access()
    if not executable:
        run(["systemctl", "enable", "--now", "snapd.socket"], privileged=True)
        run(["snap", "wait", "system", "seed.loaded"], privileged=True)
        channel = stable_channel(run(["snap", "info", "lxd"], capture=True))
        run(["snap", "install", "lxd", "--channel=" + channel], privileged=True)
    group = prepare_socket_access()
    if os.geteuid() != 0:
        username = pwd.getpwuid(os.getuid()).pw_name
        if username not in group.gr_mem and os.getgid() != group.gr_gid:
            run(["usermod", "-aG", group.gr_name, username], privileged=True)
        return group.gr_gid not in os.getgroups() and os.getgid() != group.gr_gid
    return False


def initialize():
    lxd = LXD(timeout=1800)
    def default_profile():
        profiles = json.loads(lxd.command(["profile", "list", "local:", "--format=json"]))
        profile = next((item for item in profiles if item["name"] == "default"), None)
        if profile is None:
            raise Error(t('profile_missing'))
        return profile
    pools = json.loads(lxd.command(["storage", "list", "local:", "--format=json"]))
    profile = default_profile()
    networks = json.loads(lxd.command(["network", "list", "local:", "--format=json"]))
    if not pools and not lxd.instances() and not profile.get("devices") and not profile.get("config"):
        if any(network.get("managed") for network in networks):
            raise Error(t('network_existing'))
        executable = shutil.which("lxd") or "/snap/bin/lxd"
        run([executable, "init", "--auto", "--storage-backend=dir"])
        profile = default_profile()
    devices = list(profile.get("devices", {}).values())
    if not any(d.get("type") == "disk" and d.get("path") == "/" for d in devices):
        raise Error(t('root_disk_missing'))
    if not any(d.get("type") == "nic" for d in devices):
        raise Error(t('nic_missing'))


def configure_path(home=None, shell=None):
    """Persist one guarded block in the startup files used by the login shell."""
    home = Path(home) if home is not None else Path.home()
    shell = Path(shell or pwd.getpwuid(os.getuid()).pw_shell).name
    destination = home / ".local/bin"
    if shell == "bash":
        login = next((home / name for name in (".bash_profile", ".bash_login", ".profile")
                      if (home / name).exists()), home / ".profile")
        files = [login, home / ".bashrc"]
    elif shell == "zsh":
        directory = Path(os.environ.get("ZDOTDIR") or home)
        files = [directory / ".zprofile", directory / ".zshrc"]
    elif shell in ("sh", "dash"):
        files = [home / ".profile"]
    else:
        raise Error(t("unsupported_shell", shell=shell))
    begin, end = "# >>> my-ai-sandbox PATH >>>", "# <<< my-ai-sandbox PATH <<<"
    block = (begin + "\ncase \":${PATH-}:\" in\n    *" + shlex.quote(":" + str(destination) + ":") +
             "*) ;;\n    *) export PATH=" + shlex.quote(str(destination)) + ':"${PATH-}" ;;\nesac\n' + end + "\n")
    plans = []
    for path in files:
        if path.is_symlink():
            raise Error(t('path_startup_conflict', path=path))
        original = path.read_text() if path.exists() else ""
        if begin in original or end in original:
            lines = original.splitlines()
            if (lines.count(begin) != 1 or lines.count(end) != 1
                    or original.count(begin) != 1 or original.count(end) != 1
                    or lines.index(begin) >= lines.index(end)):
                raise Error(t('path_block_invalid', path=path))
            pattern = '^' + re.escape(begin) + r"\n.*?^" + re.escape(end) + r"(?:\n|$)"
            updated = re.sub(pattern, lambda _: block, original, flags=re.S | re.M)
        else:
            updated = original.rstrip("\n") + "\n\n" + block
        plans.append((path, original, updated))
    for path, original, updated in plans:
        if updated != original:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.' + path.name + '.mas-', dir=path.parent)
            with cleanup_scope(lambda: Path(name).unlink(missing_ok=True)):
                with os.fdopen(fd, 'w') as output:
                    output.write(updated)
                    output.flush()
                    os.fsync(output.fileno())
                info = path.stat() if path.exists() else None
                os.chmod(name, info.st_mode & 0o777 if info else 0o644)
                if info:
                    os.chown(name, info.st_uid, info.st_gid)
                if path.is_symlink() or (path.read_text() if path.exists() else '') != original:
                    raise Error(t('path_startup_conflict', path=path))
                os.replace(name, path)
    os.environ["PATH"] = str(destination) + os.pathsep + os.environ.get("PATH", "")


def install_file(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + destination.name + ".", dir=destination.parent)
    temporary = Path(name)
    with cleanup_scope(lambda: temporary.unlink(missing_ok=True)):
        with os.fdopen(fd, "wb") as output, open(source, "rb") as incoming:
            shutil.copyfileobj(incoming, output)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o755)
        temporary.replace(destination)


def group_refresh_required():
    if os.geteuid() == 0:
        return False
    from .socket_access import daemon_group
    group = daemon_group()
    return group.gr_gid not in os.getgroups() and os.getgid() != group.gr_gid


def refreshed_command(command):
    username = pwd.getpwuid(os.getuid()).pw_name
    from .config import path
    # Preserve only the explicit preference location when sudo refreshes groups.
    preferences = ["XDG_CONFIG_HOME=" + str(path().parent.parent)]
    if os.environ.get("ZDOTDIR"):
        preferences.append("ZDOTDIR=" + os.environ["ZDOTDIR"])
    return ["sudo", "-u", username, "--", "env", *preferences, *command]


def finish(product):
    initialize()
    destination = Path.home() / ".local/bin/mas"
    install_file(product, destination)
    configure_path()
    print(t("installed", path=destination), flush=True)
    print(t("path_configured"), flush=True)
    return 0


def install(product):
    if prepare_system():
        code = ("import sys;sys.path.insert(0," + repr(str(Path(__file__).resolve().parent.parent)) + ");"
                "from mas.install import finish;raise SystemExit(finish(" + repr(str(product)) + "))")
        run(refreshed_command([sys.executable, "-c", code]), privileged=True)
        print(t('new_terminal'))
        return 0
    return finish(product)


def main(argv=None):
    parser = Parser(description=t("help_installer"))
    parser.add_argument("--version", action="version", version=__version__, help=t("help_version"))
    parser.add_argument("--product", type=Path, required=True, help=t("help_install_product"))
    args = parser.parse_args(argv)
    try:
        version = subprocess.check_output([sys.executable, str(args.product), "--version"], text=True, timeout=600).strip()
        if version != __version__:
            raise Error(t("product_mismatch"))
        return install(args.product.resolve())
    except (Error, OSError, subprocess.SubprocessError) as exc:
        print(t("install_failed", error=exc), file=sys.stderr)
        return 1
