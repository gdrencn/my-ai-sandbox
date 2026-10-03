"""One-time Ubuntu development environment, provisioned by native cloud-init."""
import json
from importlib.resources import files
from .core import CLOUD_INIT_WAIT, Error
from .i18n import t


PACKAGES = (
    'sudo', 'ca-certificates', 'curl', 'wget', 'openssh-client', 'git',
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
    path = '/var/lib/mas/install-node-lts.py'
    return '#cloud-config\n' + json.dumps(dict(package_update=True,
        package_upgrade=False, packages=list(PACKAGES),
        write_files=[dict(path=path, permissions='0644',
                          content=files('mas').joinpath('node_setup.py').read_text())],
        runcmd=[['/usr/bin/python3', path]])) + '\n'


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
official = json.loads(Path('/usr/local/lib/nodejs/mas-lts.json').read_text())
if record['node'] != official['version'] or record['npm'] != official['npm']:
    raise RuntimeError('Installed Node.js/npm do not match the verified official LTS')
record['node_lts'] = official
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
