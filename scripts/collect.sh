#!/usr/bin/env bash
# Pulls an issue's results from its live pod and copies them into this repo: runs/<run_id>/ (BAMs stay
# gitignored) and logs/<issue>/ (setup and plan logs, env report), then refreshes results/summary.csv.
#
# usage: collect.sh HARNESS_REPO ISSUE [--no-pull]
set -euo pipefail

repo=$(cd "$1" && pwd)
issue=$2
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
if [[ ${3:-} != --no-pull ]]; then
    (cd "$repo" && harness/target/release/harness pull "$issue")
fi
src=$repo/results/$issue
mkdir -p "$root/runs" "$root/logs/$issue"
[[ -d $src/runs ]] && rsync -a "$src/runs/" "$root/runs/"
rsync -a --exclude runs --exclude '*.bam' "$src/" "$root/logs/$issue/"
"$root/tools/venv/bin/python" "$here/summarize.py" --runs "$root/runs" --out "$root/results/summary.csv"
