"""First-install setup. Existing LXD installations and profiles are preserved."""

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

from .core import Error, LXD

from .i18n import t, Parser
from . import __version__


def run(args, privileged=False, capture=False):
    if privileged and os.geteuid() != 0 and args[0] != "sudo":
        args = ["sudo", *args]
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
        raise Error((result.stderr or "").strip() or t("setup_failed", command=" ".join(args)))
    return result.stdout or ""


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
    if os.geteuid() != 0:
        try:
            group = grp.getgrnam("lxd")
            username = pwd.getpwuid(os.getuid()).pw_name
            needs_group = ((username not in group.gr_mem and os.getgid() != group.gr_gid)
                           or (group.gr_gid not in os.getgroups() and os.getgid() != group.gr_gid))
        except KeyError:
            needs_group = True
        if not executable or needs_group:
            print(t("sudo_auth"), flush=True)
            run(["sudo", "-v"], privileged=True)
    if not executable:
        if not shutil.which("snap"):
            run(["apt-get", "update"], privileged=True)
            run(["apt-get", "install", "-y", "snapd"], privileged=True)
        run(["systemctl", "enable", "--now", "snapd.socket"], privileged=True)
        run(["snap", "wait", "system", "seed.loaded"], privileged=True)
        channel = stable_channel(run(["snap", "info", "lxd"], capture=True))
        run(["snap", "install", "lxd", "--channel=" + channel], privileged=True)
    if os.geteuid() != 0:
        username = pwd.getpwuid(os.getuid()).pw_name
        group = grp.getgrnam("lxd")
        if username not in group.gr_mem and os.getgid() != group.gr_gid:
            run(["usermod", "-aG", "lxd", username], privileged=True)
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
    for path in files:
        original = path.read_text() if path.exists() else ""
        pattern = re.escape(begin) + r".*?" + re.escape(end) + r"\n?"
        updated = re.sub(pattern, lambda _: block, original, flags=re.S) if begin in original else original.rstrip("\n") + "\n\n" + block
        if updated != original:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(updated)
    os.environ["PATH"] = str(destination) + os.pathsep + os.environ.get("PATH", "")


def install_file(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name("." + destination.name + ".installing")
    shutil.copyfile(source, temporary)
    temporary.chmod(0o755)
    temporary.replace(destination)


def group_refresh_required():
    if os.geteuid() == 0:
        return False
    group = grp.getgrnam("lxd")
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
