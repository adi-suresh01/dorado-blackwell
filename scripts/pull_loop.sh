#!/usr/bin/env bash
# Pulls an issue's results into this repo every EVERY seconds while its pod is live. The pod volume is deleted with
# the pod, at its deadline or on a container failure, so anything not pulled by then is gone. caffeinate keeps the
# laptop awake for the loop. A failed pull only warns; the next round tries again.
#
# usage: pull_loop.sh HARNESS_REPO ISSUE [EVERY_S=600]
set -uo pipefail

repo=$(cd "$1" && pwd)
issue=$2
every=${3:-600}
here=$(cd "$(dirname "$0")" && pwd)
ledger=$repo/issues/$issue/harness-ledger.json
live() {
    python3 -c "import json,sys; sys.exit(0 if any(p.get('state') == 'live' for p in json.load(open('$ledger'))['pods']) else 1)"
}
caffeinate -i -w $$ &
while live; do
    if "$here/collect.sh" "$repo" "$issue" > /dev/null 2>&1; then
        echo "$(date -u +%H:%M:%SZ) pulled $issue"
    else
        echo "$(date -u +%H:%M:%SZ) pull of $issue failed; retrying in ${every}s" >&2
    fi
    sleep "$every"
done
echo "$(date -u +%H:%M:%SZ) $issue has no live pod; loop done"
