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
