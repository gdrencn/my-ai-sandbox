"""Install the latest official Node.js LTS inside a new Ubuntu instance only."""
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import urllib.request

BASE = 'https://nodejs.org/dist/'
ARCHES = {'x86_64': 'x64', 'aarch64': 'arm64'}


def fetch(url, limit):
    with urllib.request.urlopen(url, timeout=60) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Node.js response exceeds the size limit: ' + url)
    return data


def latest_lts(index, architecture):
    versions = []
    for item in index:
        match = re.fullmatch(r'v([0-9]+)\.([0-9]+)\.([0-9]+)', item.get('version', ''))
        if match and isinstance(item.get('lts'), str) and item['lts']:
            versions.append((tuple(map(int, match.groups())), item))
    if not versions:
        raise ValueError('The official Node.js index contains no LTS release')
    item = max(versions, key=lambda value: value[0])[1]
    if 'linux-' + architecture not in item.get('files', []):
        raise ValueError('Latest official Node.js LTS has no Linux build for ' + architecture)
    return item['version']


def main(prefix=Path('/usr/local/lib/nodejs'), executable_dir=Path('/usr/local/bin')):
    architecture = ARCHES.get(platform.machine())
    if architecture is None:
        raise ValueError('Unsupported architecture for official Node.js LTS: ' + platform.machine())
    version = latest_lts(json.loads(fetch(BASE + 'index.json', 4 * 1024 * 1024)), architecture)
    filename = 'node-' + version + '-linux-' + architecture + '.tar.xz'
    release = BASE + version + '/'
    sums = fetch(release + 'SHASUMS256.txt', 1024 * 1024).decode('ascii')
    matches = [line.split()[0] for line in sums.splitlines()
               if len(line.split()) == 2 and line.split()[1] == filename]
    if len(matches) != 1 or not re.fullmatch(r'[0-9a-f]{64}', matches[0]):
        raise ValueError('Missing or invalid official SHA-256 for ' + filename)
    prefix.mkdir(parents=True, exist_ok=True)
    destination = prefix / filename.removesuffix('.tar.xz')
    if destination.exists():
        raise ValueError('Node.js destination already exists: ' + str(destination))
    with tempfile.TemporaryDirectory(prefix='.mas-node-', dir=prefix) as directory:
        stage = Path(directory)
        archive = stage / filename
        digest = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(release + filename, timeout=60) as source, archive.open('wb') as output:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > 256 * 1024 * 1024:
                    raise ValueError('Node.js archive exceeds the size limit')
                output.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != matches[0]:
            raise ValueError('Node.js archive SHA-256 does not match the official manifest')
        subprocess.run(['tar', '-xJf', str(archive), '-C', str(stage),
                        '--no-same-owner', '--no-same-permissions'], check=True)
        unpacked = stage / destination.name
        if subprocess.check_output([str(unpacked/'bin/node'), '--version'], text=True).strip() != version:
            raise ValueError('Downloaded Node.js executable has an unexpected version')
        unpacked.rename(destination)
    executable_dir.mkdir(parents=True, exist_ok=True)
    for name in ('node', 'npm', 'npx'):
        path = executable_dir/name
        if path.exists() or path.is_symlink():
            raise ValueError('Refusing to overwrite an existing command: ' + str(path))
        path.symlink_to(destination/'bin'/name)
    npm = subprocess.check_output([str(executable_dir/'npm'), '--version'], text=True).strip()
    record = dict(version=version, architecture=architecture, source=release+filename,
                  sha256=matches[0], npm=npm)
    (prefix/'mas-lts.json').write_text(json.dumps(record, sort_keys=True) + '\n')
    print(json.dumps(record, sort_keys=True))


if __name__ == '__main__':
    main()
