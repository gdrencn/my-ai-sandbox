#!/usr/bin/env bash
# Generated from scripts/install.template.sh and mas/locales by scripts/build.py.
set -euo pipefail

# Before Python exists, the bootstrap uses Bash's own terminal input.
# Labels are generated from the same product catalog as the Python menus.
mas_choose_language() {
    local selected=0 key suffix
    printf '\033[?25l' >/dev/tty
    trap 'printf "\033[?25h" >/dev/tty' RETURN
    printf '%s\n\n\n\n' '语言 / Language' >/dev/tty
    while true; do
        printf '\033[3A\r\033[2K' >/dev/tty
        if ((selected == 0)); then
            printf '\033[7m❯ ● %s\033[0m\n  ○ %s\n' '简体中文 (zh_cn)' 'English (en_us)' >/dev/tty
        else
            printf '  ○ %s\n\033[7m❯ ● %s\033[0m\n' '简体中文 (zh_cn)' 'English (en_us)' >/dev/tty
        fi
        printf '%s\n' '↑/↓ 选择 · Enter/→ 确定 · Esc/← 返回' >/dev/tty
        IFS= read -rsn1 key </dev/tty || return 1
        case $key in
            '') break ;;
            $'\e')
                suffix=''
                IFS= read -rsn2 -t 0.2 suffix </dev/tty || true
                case $suffix in
                    '[A'|'OA') selected=0 ;;
                    '[B'|'OB') selected=1 ;;
                    '[C'|'OC') break ;;
                    ''|'[D'|'OD') return 130 ;;
                esac ;;
        esac
    done
    if ((selected == 0)); then printf zh_cn; else printf en_us; fi
}

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
        mas_language=$(mas_choose_language)
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
for name in ('bootstrap.py', 'mas/config.py', 'mas/i18n.py', 'mas/menu.py', 'mas/locales/en_us.json', 'mas/locales/zh_cn.json'):
    destination = root / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(base + name, timeout=600) as response:
        destination.write_bytes(response.read())
for name in ('mas/__init__.py', 'mas/locales/__init__.py'):
    (root / name).touch()
PY
python3 "$mas_bootstrap/bootstrap.py" "$@"
