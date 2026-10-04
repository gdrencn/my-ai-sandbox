#!/usr/bin/env bash
# Generated from scripts/install.template.sh and mas/locales by scripts/build.py.
set -euo pipefail

# Before Python exists, the bootstrap uses Bash's own terminal input.
# Labels are generated from the same product catalog as the Python menus.
mas_choose_language() (
    local selected=0 key suffix columns rows minimum=43
    if ! { : </dev/tty; } 2>/dev/null; then
        printf '%s\n' '语言选择需要交互式终端；无人值守安装请指定 --language en_us 或 --language zh_cn。' >&2
        return 1
    fi
    read -r rows columns < <(stty size </dev/tty)
    if ((columns < minimum || rows < 5)); then
        printf '%s\n' '尚未安装 Python 的语言菜单需要至少 43 列、5 行；请扩大终端或显式传入 --language zh_cn / --language en_us。' >&2
        return 1
    fi
    printf '\033[?25l' >/dev/tty
    trap 'printf "\033[0m\033[?25h" >/dev/tty' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    printf '%s\n\n\n\n' '请选择界面语言 / Select interface language' >/dev/tty
    while true; do
        read -r rows columns < <(stty size </dev/tty)
        if ((columns < minimum || rows < 5)); then
            printf '\n%s\n' '尚未安装 Python 的语言菜单需要至少 43 列、5 行；请扩大终端或显式传入 --language zh_cn / --language en_us。' >&2
            return 1
        fi
        printf '\033[3A\r\033[2K' >/dev/tty
        if ((selected == 0)); then
            printf '\033[7m❯ ● %s\033[0m\n  ○ %s\n' '简体中文 (zh_cn)' 'English (en_us)' >/dev/tty
        else
            printf '  ○ %s\n\033[7m❯ ● %s\033[0m\n' '简体中文 (zh_cn)' 'English (en_us)' >/dev/tty
        fi
        printf '%s\n' '↑/↓ 选择 · Enter/→ 确定 · Esc/← 取消' >/dev/tty
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
            if ((mas_selection_status == 130)); then printf '%s\n' '已取消。' >&2; fi
            exit "$mas_selection_status"
        fi
    done
    export MAS_LANGUAGE=$mas_language
    case $mas_language in
        zh_cn) MAS_APT_SETUP='环境准备'; MAS_APT_DONE='依赖准备完成'; MAS_APT_FAILED='依赖准备失败' ;;
        en_us) MAS_APT_SETUP=Setup; MAS_APT_DONE='Dependency preparation completed'; MAS_APT_FAILED='Dependency preparation failed' ;;
    esac
# Shared dependency execution; Python UI is used when available. The Bash
# renderer below is solely the adapter for preparing Python itself.
mas_missing_dependencies() {
    command -v python3 >/dev/null || printf '%s\n' python3
    if ! command -v lxd >/dev/null && [[ ! -x /snap/bin/lxd ]]; then
        command -v snap >/dev/null || printf '%s\n' snapd
    fi
    command -v sshfs >/dev/null || printf '%s\n' sshfs
    return 0
}

# Classify complete lines and incomplete prefixes without losing fragments.
mas_apt_normal() {
    local line=$1 complete=$2 package_list=$3 prefix
    [[ $line =~ [Ww][Aa][Rr][Nn][Ii][Nn][Gg]|[Ee][Rr][Rr][Oo][Rr]|[Ff][Aa][Ii][Ll][Ee][Dd]|^[WE]:|^Err: ]] && return 1
    # Before Python exists, only ASCII normal output can be safely clipped by
    # Bash's character count. Preserve other text as permanent native output.
    [[ $line =~ [^\ -~] ]] && return 1
    [[ -z $line ]] && return 0
    for prefix in 'Hit:' 'Get:' 'Ign:' 'Reading package lists' 'Building dependency tree' \
        'Reading state information' 'Solving dependencies' 'The following ' 'Suggested packages:' \
        'Recommended packages:' 'Need to get ' 'After this operation,' 'Fetched ' \
        'Selecting previously unselected package ' 'Preparing to unpack ' 'Unpacking ' \
        'Setting up ' 'Processing triggers for ' '(Reading database ' 'Scanning ' \
        'All packages are up to date.' 'Reading changelogs' 'Extracting templates from packages:'; do
        [[ $line == "$prefix"* ]] && return 0
        [[ $complete -eq 0 && $prefix == "$line"* ]] && return 0
    done
    [[ $package_list -eq 1 && $line =~ ^[[:space:]]+[a-z0-9][a-z0-9.+:~_\ -]*$ ]] && return 0
    [[ $line =~ ^[0-9]+\ upgraded, ]] && return 0
    return 1
}

# Uses the renderer's local state (Bash dynamic scoping); never runs commands.
mas_apt_emit() {
    local complete=$1
    if ((committed == 0)) && mas_apt_normal "$pending" "$complete" "$package_list"; then
        if [[ -t 1 && -n $pending ]]; then
            # Query the actual output terminal on each update, including resize.
            read -r _ width < <(stty size <&1 2>/dev/null) || width=${COLUMNS:-80}
            [[ $width =~ ^[0-9]+$ ]] && ((width > 1)) || width=80
            printf '\r\033[2K%s' "${pending:0:width-1}"
            active=1
        fi
    else
        if ((active)); then printf '\r\033[2K'; active=0; fi
        printf '%s' "${pending:committed}"
        committed=${#pending}
        if ((complete)); then printf '\n'; fi
    fi
    if ((complete)); then
        [[ $pending == [[:space:]]* ]] || package_list=0
        case $pending in 'The following '*|'Suggested packages:'|'Recommended packages:') package_list=1 ;; esac
        pending=''; committed=0
    fi
}

mas_apt_render() {
    if [[ -n ${MAS_APT_PYTHON:-} && -n ${MAS_APT_ROOT:-} ]]; then
        "$MAS_APT_PYTHON" -c 'import sys;sys.path.insert(0,sys.argv[1]);from mas.output import apt_stream;apt_stream()' "$MAS_APT_ROOT"
        return $?
    fi
    local char status pending='' committed=0 active=0 package_list=0 after_cr=0 width=${COLUMNS:-80}
    while true; do
        if IFS= read -r -N 1 -t 0.1 char; then
            if [[ $char == $'\n' && $after_cr -eq 1 ]]; then after_cr=0; continue; fi
            after_cr=0
            case $char in
                $'\r') after_cr=1; mas_apt_emit 1 ;;
                $'\n') mas_apt_emit 1 ;;
                *) pending+=$char ;;
            esac
        else
            status=$?
            if ((status > 128)); then
                [[ -z $pending ]] || mas_apt_emit 0
                continue
            fi
            [[ -z $pending ]] || mas_apt_emit 1
            break
        fi
    done
    if ((active)); then printf '\r\033[2K'; fi
    return 0
}

mas_apt_execute() {
    local log result
    log=$(mktemp) || return $?
    trap 'rm -f "$log"' EXIT
    if apt-get -o Dpkg::Use-Pty=0 -o APT::Color=0 "$@" 2>&1 | tee "$log" | mas_apt_render; then
        result=0
    else
        result=${PIPESTATUS[0]}
        [[ $result -ne 0 ]] || result=1
        cat "$log" >&2
    fi
    rm -f "$log"
    trap - EXIT
    return "$result"
}

mas_run_apt() {
    local result input worker
    local -a privilege=()
    [[ $EUID -eq 0 ]] || privilege=(sudo)
    # Keep sudo's own output attached to the terminal. Put the output pipeline
    # INSIDE its command, so sudo-rs can establish the foreground group first.
    # Redirected runs are noninteractive; sudo still owns any authentication.
    if [[ -t 1 ]] && { exec {input}</dev/tty; } 2>/dev/null; then :
    else exec {input}</dev/null
    fi
    worker=$(declare -f mas_apt_normal mas_apt_emit mas_apt_render mas_apt_execute)
    worker+=$'\nmas_apt_execute "$@"'
    printf '%s: apt-get %s\n' "${MAS_APT_SETUP:-Preparing dependencies}" "$*"
    if "${privilege[@]}" env LC_ALL=C MAS_APT_PYTHON="${MAS_APT_PYTHON:-}" MAS_APT_ROOT="${MAS_APT_ROOT:-}" \
        bash -o pipefail -c "$worker" mas-apt "$@" <&"$input"; then
        result=0
        printf '%s: apt-get %s\n' "${MAS_APT_DONE:-Dependency preparation completed}" "$*"
    else
        result=$?
        printf '%s: apt-get %s\n' "${MAS_APT_FAILED:-Dependency preparation failed}" "$*" >&2
    fi
    exec {input}<&-
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
for name in ('bootstrap.py', 'mas/config.py', 'mas/i18n.py', 'mas/menu.py', 'mas/output.py', 'mas/text.py', 'mas/diagnostics.py', 'mas/locales/en_us.json', 'mas/locales/zh_cn.json'):
    destination = root / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(base + name, timeout=600) as response:
        destination.write_bytes(response.read())
for name in ('mas/__init__.py', 'mas/locales/__init__.py'):
    (root / name).touch()
PY
python3 "$mas_bootstrap/bootstrap.py"  "$@"
