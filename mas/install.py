"""First-install setup. Existing LXD installations and profiles are preserved."""

import grp
import json

import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys

from .core import Error, LXD

from .i18n import t


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


def finish(product, tester=None, run_tests=False, test_args=None):
    initialize()
    destination = Path.home() / ".local/bin"
    destination.mkdir(parents=True, exist_ok=True)
    for source, name in ((product, "mas"), (tester, "mas-test")):
        if source:
            temporary = destination / ("." + name + ".installing")
            shutil.copyfile(source, temporary)
            temporary.chmod(0o755)
            temporary.replace(destination / name)
    print(t("installed", path=destination / "mas"), flush=True)
    if str(destination) not in os.environ.get("PATH", "").split(os.pathsep):
        print(t('add_path'), flush=True)
    if run_tests:
        return subprocess.call([sys.executable, str(destination / "mas-test"), *(test_args or [])])
    return 0


def install(product, tester=None, run_tests=False, test_args=None):
    if prepare_system():
        # sudo creates a fresh process with the user's updated supplementary groups.
        # It does not run the product or tests as root.
        username = pwd.getpwuid(os.getuid()).pw_name
        code = ("import os,sys;os.environ['XDG_CONFIG_HOME']=" + repr(str(Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"))) + ";sys.path.insert(0," + repr(str(product)) + ");"
                "from mas.install import finish;raise SystemExit(finish(" + repr(str(product)) + "," +
                repr(str(tester) if tester else None) + "," + repr(run_tests) + "," + repr(test_args) + "))")
        run(["sudo", "-u", username, "--", sys.executable, "-c", code], privileged=True)
        print(t('new_terminal'))
        return 0
    return finish(product, tester, run_tests, test_args)
