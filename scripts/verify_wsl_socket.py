#!/usr/bin/env python3
"""Developer regression: create/destroy one disposable WSL, never reboot the host.

Run from an existing WSL with Windows interop:
  python3 scripts/verify_wsl_socket.py --image VERIFIED_ROOTFS --windows-temp /mnt/c/.../Temp
Uses the current dist installer/product. Writes evidence even on failure.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--windows-temp', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    image = args.image.resolve(strict=True)
    name = 'test-' + uuid.uuid4().hex
    storage = Path(tempfile.mkdtemp(prefix='mas-wsl-socket-', dir=args.windows_temp))
    report = dict(distro=name, image_sha256=hashlib.file_digest(image.open('rb'),'sha256').hexdigest(), steps=[], passed=False)
    created = False

    def command(argv, expected=0):
        started = time.monotonic()
        result = subprocess.run(argv, text=True, errors='replace', capture_output=True, timeout=1800)
        report['steps'].append(dict(command=argv, code=result.returncode, elapsed=time.monotonic()-started,
                                    stdout=result.stdout, stderr=result.stderr))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        if expected is not None and result.returncode != expected:
            raise RuntimeError(str(argv)+': '+result.stdout[-2000:]+result.stderr[-2000:])
        return result

    def wsl(script, user='root', expected=0):
        return command(['wsl.exe','-d',name,'-u',user,'--cd','/','--','bash','-lc','set -e; '+script],expected)

    def restart():
        command(['wsl.exe','--terminate',name])
        # The next independent WSL command starts a new instance.
        wsl('test "$(cat /proc/1/comm)" = systemd')

    def check_access(group='lxd'):
        wsl('id; /snap/bin/lxc list; "$HOME/.local/bin/mas" list', user='mascheck')
        wsl('test "$(stat -c %G /var/snap/lxd/common/lxd/unix.socket)" = '+group+
            '; test "$(stat -c %a /var/snap/lxd/common/lxd/unix.socket)" = 660')

    def recreate():
        # This distribution was created above; it contains no user containers.
        wsl('set -e; systemctl stop snap.lxd.daemon.service snap.lxd.daemon.unix.socket; '
            'rm -f /var/snap/lxd/common/lxd/unix.socket; systemctl start snap.lxd.daemon.unix.socket')

    try:
        for file in ('mas.pyz','mas-install.pyz'):
            shutil.copyfile(ROOT/'dist'/file,storage/file)
        win_storage=subprocess.check_output(['wslpath','-w',str(storage/'distro')],text=True).strip()
        win_image=subprocess.check_output(['wslpath','-w',str(image)],text=True).strip()
        command(['wsl.exe','--import',name,win_storage,win_image,'--version','2']); created=True
        wsl("set -e; useradd -m -s /bin/bash mascheck; usermod -aG sudo mascheck; "
            "printf 'mascheck ALL=(ALL) NOPASSWD: ALL\\n' > /etc/sudoers.d/mascheck; chmod 440 /etc/sudoers.d/mascheck; "
            "printf '[boot]\\nsystemd=true\\n[user]\\ndefault=mascheck\\n' > /etc/wsl.conf")
        restart()
        # Bring the disposable image's snapd up to date for the host WSL kernel.
        wsl('apt-get update; apt-get install --only-upgrade -y snapd; snap version')
        source=str(storage)
        wsl('set -e; mkdir -p /opt/mas-test; cp '+shlex.quote(source+'/mas.pyz')+' '+shlex.quote(source+'/mas-install.pyz')+' /opt/mas-test/; chmod 644 /opt/mas-test/*')
        install='python3 /opt/mas-test/mas-install.pyz --product /opt/mas-test/mas.pyz'
        wsl(install,user='mascheck')
        check_access()
        # Reproduce the original permission failure on the known disposable host.
        wsl('rm /etc/systemd/system/snap.lxd.daemon.unix.socket.d/mas.conf; systemctl daemon-reload')
        recreate()
        wsl('stat -c "%U:%G %a" /var/snap/lxd/common/lxd/unix.socket; test "$(stat -c %G /var/snap/lxd/common/lxd/unix.socket)" = root')
        result=wsl('LXD_DIR=/var/snap/lxd/common/lxd /snap/bin/lxc list',user='mascheck',expected=None)
        if result.returncode == 0 or 'permission denied' not in result.stderr:
            raise RuntimeError('Original socket permission failure was not reproduced')
        wsl(install,user='mascheck')
        check_access()
        recreate(); check_access()
        restart(); check_access()
        # A configured non-default administration group must work as well.
        wsl('groupadd maslxd; snap set lxd daemon.group=maslxd')
        wsl(install,user='mascheck')
        check_access('maslxd')
        recreate();check_access('maslxd')
        restart();check_access('maslxd')
        # Ready reinstall must not need sudo; invalidate auth and deny sudo in fixture.
        wsl('rm /etc/sudoers.d/mascheck; gpasswd -d mascheck sudo')
        wsl(install,user='mascheck')
        check_access('maslxd')
        report['passed']=True
    finally:
        if created:
            command(['wsl.exe','--unregister',name])
            report['distro_removed']=True
        shutil.rmtree(storage)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('Isolated WSL socket recreation and restart checks passed: '+str(args.report))


if __name__=='__main__':
    main()
