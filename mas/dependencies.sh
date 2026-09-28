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
