#!/usr/bin/env bash
# Host-assisted entry; probe logic remains in the two shared Python files.
set -euo pipefail
if ! command -v python3 >/dev/null || ! python3 -c 'import sys;sys.exit(0 if sys.version_info >= (3,10) else 2)'; then
    printf '%s\n' '错误：宿主需要 Python 3.10 或更高版本。' >&2
    exit 2
fi
mas_host_probe_work=$(mktemp -d -t mas-host-download-XXXXXXXX)
trap 'rm -rf -- "$mas_host_probe_work"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
for mas_host_probe_file in guest_security_probe.py host_security_probe.py; do
    curl -fsSL "https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/$mas_host_probe_file" -o "$mas_host_probe_work/$mas_host_probe_file"
done
python3 "$mas_host_probe_work/host_security_probe.py" "$@"
