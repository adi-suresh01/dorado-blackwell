#!/usr/bin/env bash
# Copies this kit (scripts/, subsets/, references/) into a GPU harness issue folder, which is what the harness uploads to a
# pod, and writes the folder's setup.sh. This repo stays the only source: rerun after any change here.
#
# usage: sync_harness.sh HARNESS_REPO ISSUE [pod_setup.sh args...]
#   e.g. sync_harness.sh ~/Desktop/sm120-kit dorado-5090x2 --soak-files 5 --with-dorado 1.4.0
set -euo pipefail

repo=$(cd "$1" && pwd)
issue=$2
shift 2
src=$(cd "$(dirname "$0")/.." && pwd)
dest=$repo/issues/$issue
[[ -f $dest/harness.toml ]] || { echo "no $dest/harness.toml" >&2; exit 1; }
mkdir -p "$dest/kit"
rsync -a --delete --exclude '__pycache__' "$src/scripts" "$src/subsets" "$src/references" "$dest/kit/"
{
    echo '#!/usr/bin/env bash'
    echo '# Written by dorado-blackwell/scripts/sync_harness.sh; edit that repo, not this file.'
    echo 'set -euo pipefail'
    echo 'here=$(cd "$(dirname "$0")" && pwd)'
    printf 'bash "$here/kit/scripts/pod_setup.sh" "$here/kit"'
    # printf with no arguments still prints its format once, which would pass pod_setup.sh an empty argument.
    (($#)) && printf ' %q' "$@"
    echo
} > "$dest/setup.sh"
du -sh "$dest/kit" | sed "s|$repo/||"
