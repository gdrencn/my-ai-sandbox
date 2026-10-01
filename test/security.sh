#!/usr/bin/env bash
# Independent guest probe entry; the Python file owns all boundary checks.
set -euo pipefail

if ! command -v python3 >/dev/null; then
    printf '%s\n' '错误：容器内需要 Python 3.10+；请安装 python3 后重试。' >&2
    exit 2
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 2)'; then
    printf '%s\n' '错误：容器内的 Python 版本必须为 3.10 或更高。' >&2
    exit 2
fi
if [[ $EUID -ne 0 ]] && ! command -v sudo >/dev/null; then
    printf '%s\n' '错误：请以容器 root 运行，或先在容器内安装 sudo。' >&2
    exit 2
fi

mas_probe_work=$(mktemp -d -t mas-guest-download-XXXXXXXX)
trap 'rm -rf -- "$mas_probe_work"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/guest_security_probe.py -o "$mas_probe_work/guest_security_probe.py"

if [[ $EUID -eq 0 ]]; then
    python3 "$mas_probe_work/guest_security_probe.py" "$@"
else
    sudo -- python3 "$mas_probe_work/guest_security_probe.py" "$@"
fi
