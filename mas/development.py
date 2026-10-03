"""One-time Ubuntu development environment, provisioned by native cloud-init."""
import json
from .core import CLOUD_INIT_WAIT, Error
from .i18n import t


PACKAGES = (
    'sudo', 'ca-certificates', 'curl', 'wget', 'openssh-client', 'git', 'nodejs', 'npm',
    'python3', 'python3-venv', 'python3-pip', 'python3-dev',
    'build-essential', 'pkg-config', 'ripgrep', 'jq', 'patch', 'file',
    'tar', 'gzip', 'xz-utils', 'zip', 'unzip', 'zstd', 'shellcheck',
)
RECORD = '/var/lib/mas/development.json'


def finish(manager, target, data, identity):
    """Retire first-boot provisioning so imports cannot trigger it again."""
    api = manager.lxd.configuration
    item, etag = api.read(target)
    if item['config'].get('volatile.uuid') != identity:
        raise Error(t('new_identity_changed', target=target))
    if item['config'].get('cloud-init.user-data') != data:
        raise Error(t('development_config_changed', target=target))
    item['config'] = dict(item['config'])
    del item['config']['cloud-init.user-data']
    api.write(target, item, etag)
    current, _ = api.read(target)
    if current['config'].get('volatile.uuid') != identity or 'cloud-init.user-data' in current['config']:
        raise Error(t('development_config_changed', target=target))


def cloud_config():
    # JSON is a YAML subset, avoiding an extra YAML dependency.
    return '#cloud-config\n' + json.dumps(dict(package_update=True,
        package_upgrade=False, packages=list(PACKAGES))) + '\n'


def live_wait():
    """Stream the first-boot log through the existing LXD exec connection."""
    return r'''
(
    while ! test -e /var/log/cloud-init-output.log; do sleep 0.05; done
    exec tail -n +1 --follow=name --retry --sleep-interval=0.05 /var/log/cloud-init-output.log
) &
mas_log_pid=$!
trap 'kill "$mas_log_pid" 2>/dev/null || true; wait "$mas_log_pid" 2>/dev/null || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
''' + CLOUD_INIT_WAIT + r'''
kill "$mas_log_pid" 2>/dev/null || true
wait "$mas_log_pid" 2>/dev/null || true
trap - EXIT INT TERM
'''


def verification():
    """Verify actual capabilities as sandbox and only then save completion."""
    return r'''set -eu
command -v cloud-init >/dev/null || { echo 'Ubuntu cloud-init is required for new-container preparation' >&2; exit 1; }
test "$(. /etc/os-release; printf '%s' "$ID")" = ubuntu || { echo 'Ubuntu is required for new-container preparation' >&2; exit 1; }
CLOUD_INIT_WAIT_LITERAL
trap 'code=$?; if test "$code" -ne 0; then tail -n 60 /var/log/cloud-init-output.log >&2; fi' EXIT
/usr/bin/python3 - <<'PY'
import json, os, subprocess, tempfile
from pathlib import Path
packages = PACKAGES_LITERAL
versions = {}
for name in packages:
    value = subprocess.check_output(['dpkg-query', '-W', '-f=${Status}\t${Version}', name], text=True)
    status, version = value.split('\t', 1)
    if status != 'install ok installed':
        raise RuntimeError('Required package is not installed: ' + name + ': ' + status)
    versions[name] = version
commands = 'sudo curl wget ssh scp sftp git node npm npx python3 pip3 cc c++ make pkg-config rg jq patch file tar gzip xz zip unzip zstd shellcheck'
subprocess.run(['su', '--login', 'sandbox', '-c',
    'set -eu; for name in ' + commands + '; do command -v "$name" >/dev/null || '
    '{ echo "Missing development command: $name" >&2; exit 1; }; done; '
    'node --version; npm --version; python3 --version; '
    'work=$(mktemp -d); trap \'rm -rf -- "$work"\' EXIT; '
    'python3 -m venv "$work/venv"; "$work/venv/bin/python" -m pip --version'], check=True)
record = dict(version=1, packages=versions, node=subprocess.check_output(['node','--version'],text=True).strip(),
              npm=subprocess.check_output(['npm','--version'],text=True).strip())
record['node_source'] = 'ubuntu-apt'
path = Path(RECORD_LITERAL)
path.parent.mkdir(parents=True, exist_ok=True)
with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
    temporary = Path(stream.name)
    json.dump(record, stream, sort_keys=True)
try:
    temporary.chmod(0o644)
    os.replace(temporary, path)
finally:
    temporary.unlink(missing_ok=True)
print(json.dumps(record, sort_keys=True))
PY
'''.replace('CLOUD_INIT_WAIT_LITERAL', CLOUD_INIT_WAIT).replace('PACKAGES_LITERAL', repr(PACKAGES)).replace('RECORD_LITERAL', repr(RECORD))
