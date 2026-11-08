#!/usr/bin/env bash
# Copies one kit file to a live pod (the harness uploads the kit only at `up`), and checks its sha256 there.
# Never use it on a script a running plan is executing: bash reads a script as it runs, so a rewrite mid-run
# breaks the run.
#
# usage: push_kit_file.sh HARNESS_REPO ISSUE LOCAL_FILE KIT_RELATIVE_PATH
#   e.g. push_kit_file.sh ~/Desktop/sm120-kit dorado-h100 /tmp/redo.tsv scripts/plans/redo.tsv
set -euo pipefail

repo=$(cd "$1" && pwd)
issue=$2
local_file=$3
rel=$4
want=$(shasum -a 256 "$local_file" | cut -d' ' -f1)
b64=$(base64 < "$local_file" | tr -d '\n')
dest=issues/$issue/kit/$rel
(cd "$repo" && harness/target/release/harness ssh "$issue" -- \
    "mkdir -p \"\$(dirname $dest)\" && echo $b64 | base64 -d > $dest && echo '$want  $dest' | sha256sum -c --status && echo 'pushed $rel'") \
    2>&1 | grep -v '^{"ts"'
