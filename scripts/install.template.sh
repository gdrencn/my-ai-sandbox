#!/usr/bin/env bash
# Generated from scripts/install.template.sh and mas/locales by scripts/build.py.
set -euo pipefail

if ! command -v python3 >/dev/null; then
    mas_language=${MAS_LANGUAGE:-}
    mas_arguments=("$@")
    for ((mas_i=0; mas_i<${#mas_arguments[@]}; mas_i++)); do
        case ${mas_arguments[$mas_i]} in
            --language) mas_language=${mas_arguments[$((mas_i+1))]:-} ;;
            --language=*) mas_language=${mas_arguments[$mas_i]#*=} ;;
        esac
    done
    while [[ $mas_language != en_us && $mas_language != zh_cn ]]; do
        printf '%s' @LANGUAGE_PROMPT@ >/dev/tty
        read -r mas_language </dev/tty
        case $mas_language in 1|'') mas_language=en_us ;; 2) mas_language=zh_cn ;; esac
    done
    export MAS_LANGUAGE=$mas_language
    if [[ $EUID -eq 0 ]]; then
        apt-get update
        apt-get install -y python3
    else
        sudo -v </dev/tty
        sudo apt-get update </dev/tty
        sudo apt-get install -y python3 </dev/tty
    fi
fi
mas_bootstrap=$(mktemp -d)
trap 'rm -rf "$mas_bootstrap"' EXIT
python3 - "$mas_bootstrap" <<'PY'
from pathlib import Path
import sys, urllib.request
root = Path(sys.argv[1])
base = 'https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/'
for name in ('bootstrap.py', 'mas/config.py', 'mas/i18n.py', 'mas/locales/en_us.json', 'mas/locales/zh_cn.json'):
    destination = root / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(base + name, timeout=600) as response:
        destination.write_bytes(response.read())
for name in ('mas/__init__.py', 'mas/locales/__init__.py'):
    (root / name).touch()
PY
python3 "$mas_bootstrap/bootstrap.py" "$@"
