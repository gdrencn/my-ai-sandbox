#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 1 ]]; then
    echo 'Usage: bash RESTORE.sh [NEW_DESTINATION]' >&2
    exit 2
fi
bundle_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
destination=${1:-./my-ai-sandbox}
if [[ -e "$destination" || -L "$destination" ]]; then
    echo "Destination already exists; choose a new path: $destination" >&2
    exit 2
fi
for command_name in git sha256sum; do
    command -v "$command_name" >/dev/null || { echo "Required command missing: $command_name" >&2; exit 2; }
done
(
    cd -- "$bundle_dir"
    sha256sum --check SHA256SUMS
)
git -c init.templateDir= clone --branch main -- "$bundle_dir/my-ai-sandbox.git.bundle" "$destination"
git -C "$destination" branch --track release origin/release
git -C "$destination" remote set-url origin https://github.com/gdrencn/my-ai-sandbox.git
git -C "$destination" fsck --full
echo "Restored repository: $destination"
echo 'Read AGENTS.md and handoff/START_HERE.md before new work. No software installation or container operation was performed.'
