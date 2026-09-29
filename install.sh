#!/usr/bin/env bash
# Generated from scripts/install.template.sh and mas/locales by scripts/build.py.
set -euo pipefail

# Before Python exists, the bootstrap uses Bash's own terminal input.
# Labels are generated from the same product catalog as the Python menus.
mas_choose_language() {
    local selected=0 key suffix
    printf '\033[?25l' >/dev/tty
    trap 'printf "\033[?25h" >/dev/tty' RETURN
    printf '%s\n\n\n\n' '请选择界面语言 / Select interface language' >/dev/tty
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
                    '[A'|'OA') selected=$(( (selected + 1) % 2 )) ;;
                    '[B'|'OB') selected=$(( (selected + 1) % 2 )) ;;
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
    case $mas_language in
        zh_cn) MAS_APT_SETUP='环境准备'; MAS_APT_DONE='依赖准备完成'; MAS_APT_FAILED='依赖准备失败' ;;
        en_us) MAS_APT_SETUP=Setup; MAS_APT_DONE='Dependency preparation completed'; MAS_APT_FAILED='Dependency preparation failed' ;;
    esac
# Shared by the pre-Python bootstrap and the Python installer. Bash built-ins
# handle presentation so preparing Python itself uses the same dependency flow.
mas_missing_dependencies() {
    command -v python3 >/dev/null || printf '%s\n' python3
    if ! command -v lxd >/dev/null && [[ ! -x /snap/bin/lxd ]]; then
        command -v snap >/dev/null || printf '%s\n' snapd
    fi
    command -v sshfs >/dev/null || printf '%s\n' sshfs
    return 0
}

mas_apt_render() {
    local line normal active=0 package_list=0 partial=0 complete status width=${COLUMNS:-80}
    while true; do
        # A native prompt need not end in a newline. Flush partial text rather
        # than hiding a question while apt waits for terminal input.
        complete=1
        if IFS= read -r -t 0.1 line; then
            status=0
        else
            status=$?
            complete=0
            if [[ -z $line ]]; then
                ((status > 128)) && continue
                break
            fi
        fi
        line=${line//$'\r'/}
        normal=0
        case $line in
            ''|Hit:*|Get:*|Ign:*|'Reading package lists'*|'Building dependency tree'*|'Reading state information'*|'Solving dependencies'*|\
            'The following '*|'Suggested packages:'|'Recommended packages:'|'Need to get '*|'After this operation,'*|\
            'Fetched '*|'Selecting previously unselected package '*|'Preparing to unpack '*|'Unpacking '*|\
            'Setting up '*|'Processing triggers for '*|'(Reading database '*|'Scanning '*|\
            'All packages are up to date.'|'Reading changelogs'*|'Extracting templates from packages:'*) normal=1 ;;
        esac
        # Package lists and apt's numeric summary are normal output; unmatched
        # text, including diagnostics on either stream, remains visible.
        if [[ $package_list -eq 1 && $line =~ ^[[:space:]]+[a-z0-9][a-z0-9.+:~_\ -]*$ ]] ||
           [[ $line =~ ^[0-9]+\ upgraded, ]]; then normal=1; fi
        if [[ $line != [[:space:]]* ]]; then package_list=0; fi
        case $line in 'The following '*|'Suggested packages:'|'Recommended packages:') package_list=1 ;; esac
        if [[ $line =~ [Ww][Aa][Rr][Nn][Ii][Nn][Gg]|[Ee][Rr][Rr][Oo][Rr]|[Ff][Aa][Ii][Ll][Ee][Dd]|^[WE]:|^Err: ]]; then
            normal=0; package_list=0
        fi
        if ((!complete || partial)); then normal=0; fi
        if ((normal)); then
            if [[ -t 1 && -n $line ]]; then
                printf '\r\033[2K%s' "${line:0:width-1}"
                active=1
            fi
        else
            if ((active)); then printf '\r\033[2K'; active=0; fi
            printf '%s' "$line"
            if ((complete)); then printf '\n'; fi
        fi
        partial=$(( !complete ))
    done
    if ((partial)); then printf '\n'; fi
    if ((active)); then printf '\r\033[2K'; fi
    return 0
}

mas_run_apt() {
    local log result input
    local -a privilege=()
    [[ $EUID -eq 0 ]] || privilege=(sudo)
    log=$(mktemp)
    if ! { exec {input}</dev/tty; } 2>/dev/null; then exec {input}</dev/null; fi
    printf '%s: apt-get %s\n' "${MAS_APT_SETUP:-Preparing dependencies}" "$*"
    # sudo uses its controlling terminal normally; no password interception or
    # standalone authentication command. APT runs in C locale for classification.
    if "${privilege[@]}" env LC_ALL=C apt-get -o Dpkg::Use-Pty=0 -o APT::Color=0 "$@" <&"$input" 2>&1 |
        tee "$log" | mas_apt_render; then
        result=0
    else
        result=${PIPESTATUS[0]}
        [[ $result -ne 0 ]] || result=1
    fi
    if ((result)); then
        printf '%s: apt-get %s\n' "${MAS_APT_FAILED:-Dependency preparation failed}" "$*" >&2
        cat "$log" >&2
    else
        printf '%s: apt-get %s\n' "${MAS_APT_DONE:-Dependency preparation completed}" "$*"
    fi
    exec {input}<&-
    rm -f "$log"
    return "$result"
}

mas_install_dependencies() {
    local -a packages=()
    mapfile -t packages < <(mas_missing_dependencies)
    ((${#packages[@]})) || return 0
    mas_run_apt update || return $?
    mas_run_apt install -y "${packages[@]}"
}

    mas_install_dependencies
fi
mas_bootstrap=$(mktemp -d)
trap 'rm -rf "$mas_bootstrap"' EXIT
python3 - "$mas_bootstrap" <<'PY'
from pathlib import Path
import sys, urllib.request
root = Path(sys.argv[1])
base = 'https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/'
for name in ('bootstrap.py', 'mas/config.py', 'mas/i18n.py', 'mas/menu.py', 'mas/output.py', 'mas/diagnostics.py', 'mas/locales/en_us.json', 'mas/locales/zh_cn.json'):
    destination = root / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(base + name, timeout=600) as response:
        destination.write_bytes(response.read())
for name in ('mas/__init__.py', 'mas/locales/__init__.py'):
    (root / name).touch()
PY
python3 "$mas_bootstrap/bootstrap.py" "$@"
