#!/usr/bin/env bash
# Generated from scripts/install.template.sh and mas/locales by scripts/build.py.
set -euo pipefail

# Before Python exists, the bootstrap uses Bash's own terminal input.
# Labels are generated from the same product catalog as the Python menus.
mas_choose_language() (
    local selected=0 key suffix columns rows minimum=@LANGUAGE_MIN_WIDTH@
    if ! { : </dev/tty; } 2>/dev/null; then
        printf '%s\n' @LANGUAGE_TERMINAL_REQUIRED@ >&2
        return 1
    fi
    read -r rows columns < <(stty size </dev/tty)
    if ((columns < minimum || rows < 5)); then
        printf '%s\n' @BOOTSTRAP_TERMINAL_NARROW@ >&2
        return 1
    fi
    printf '\033[?25l' >/dev/tty
    trap 'printf "\033[0m\033[?25h" >/dev/tty' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    printf '%s\n\n\n\n' @LANGUAGE_TITLE@ >/dev/tty
    while true; do
        read -r rows columns < <(stty size </dev/tty)
        if ((columns < minimum || rows < 5)); then
            printf '\n%s\n' @BOOTSTRAP_TERMINAL_NARROW@ >&2
            return 1
        fi
        printf '\033[3A\r\033[2K' >/dev/tty
        if ((selected == 0)); then
            printf '\033[7m❯ ● %s\033[0m\n  ○ %s\n' @LANGUAGE_ZH@ @LANGUAGE_EN@ >/dev/tty
        else
            printf '  ○ %s\n\033[7m❯ ● %s\033[0m\n' @LANGUAGE_ZH@ @LANGUAGE_EN@ >/dev/tty
        fi
        printf '%s\n' @LANGUAGE_KEYS@ >/dev/tty
        IFS= read -rsn1 key </dev/tty || return 1
        case $key in
            '') break ;;
            $'\e')
                suffix=''
                IFS= read -rsn2 -t 0.2 suffix </dev/tty || true
                case $suffix in
                    '[A'|'OA') selected=$(( (selected + 1) % 2 )) ;;
                    '[B'|'OB') selected=$(( (selected + 1) % 2 )) ;;
                    '[C'|'OC') break ;;
                    ''|'[D'|'OD') return 130 ;;
                esac ;;
        esac
    done
    if ((selected == 0)); then printf zh_cn; else printf en_us; fi
)

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
        if mas_language=$(mas_choose_language); then :
        else
            mas_selection_status=$?
            if ((mas_selection_status == 130)); then printf '%s\n' @CANCELLED@ >&2; fi
            exit "$mas_selection_status"
        fi
    done
    export MAS_LANGUAGE=$mas_language
    case $mas_language in
        zh_cn) MAS_APT_SETUP=@APT_SETUP_ZH@; MAS_APT_DONE=@APT_DONE_ZH@; MAS_APT_FAILED=@APT_FAILED_ZH@ ;;
        en_us) MAS_APT_SETUP=@APT_SETUP_EN@; MAS_APT_DONE=@APT_DONE_EN@; MAS_APT_FAILED=@APT_FAILED_EN@ ;;
    esac
@DEPENDENCIES@
    mas_install_dependencies
fi
mas_bootstrap=$(mktemp -d)
trap 'rm -rf "$mas_bootstrap"' EXIT
python3 - "$mas_bootstrap" <<'PY'
from pathlib import Path
import sys, urllib.request
root = Path(sys.argv[1])
base = 'https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/'
for name in ('bootstrap.py', 'mas/config.py', 'mas/i18n.py', 'mas/menu.py', 'mas/output.py', 'mas/text.py', 'mas/diagnostics.py', 'mas/locales/en_us.json', 'mas/locales/zh_cn.json'):
    destination = root / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(base + name, timeout=600) as response:
        destination.write_bytes(response.read())
for name in ('mas/__init__.py', 'mas/locales/__init__.py'):
    (root / name).touch()
PY
python3 "$mas_bootstrap/bootstrap.py" "$@"
