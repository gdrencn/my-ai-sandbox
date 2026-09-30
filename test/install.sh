#!/usr/bin/env bash
# Generated thin entry; installation and testing live in the shared bootstrap.
set -euo pipefail
mas_entry=$(mktemp)
trap 'rm -f "$mas_entry"' EXIT
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh -o "$mas_entry"
bash "$mas_entry" --channel test "$@"
