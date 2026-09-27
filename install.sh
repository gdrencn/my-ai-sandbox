#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null; then
    sudo apt-get update </dev/tty
    sudo apt-get install -y python3 </dev/tty
fi
mas_bootstrap=$(mktemp)
trap 'rm -f "$mas_bootstrap"' EXIT
python3 - "$mas_bootstrap" <<'PY'
import sys, urllib.request
with urllib.request.urlopen('https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/bootstrap.py', timeout=600) as response:
    with open(sys.argv[1], 'wb') as output:
        output.write(response.read())
PY
python3 "$mas_bootstrap" "$@"
