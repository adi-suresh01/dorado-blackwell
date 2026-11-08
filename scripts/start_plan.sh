#!/usr/bin/env bash
# Starts a plan on the issue's live pod in the background and returns. The pod's price, provider and id come from
# the harness ledger, so every verdict carries the rate that pod was actually rented at.
#
# usage: start_plan.sh HARNESS_REPO ISSUE PLAN_NAME [matrix.sh args...]
#   e.g. start_plan.sh ~/Desktop/sm120-kit dorado-h100 single-gpu --device cuda:0
# setsid detaches the plan from the ssh session, as the harness does for its own jobs, so the call returns.
# Progress: harness ssh ISSUE -- tail -n 5 results/ISSUE/PLAN_NAME.log
set -euo pipefail

repo=$(cd "$1" && pwd)
issue=$2
plan=$3
shift 3
ledger=$repo/issues/$issue/harness-ledger.json
read -r rate provider pod_id gpu reserved < <(python3 - "$ledger" <<'PYEOF'
import json, sys
live = [p for p in json.load(open(sys.argv[1]))["pods"] if p.get("state") == "live"]
if not live:
    sys.exit("no live pod in the ledger")
p = live[-1]
print(p["rate_usd_hr"], p.get("provider", "runpod"), p["id"], p["gpu"].replace(" ", "_"), p.get("reserved_at"))
PYEOF
)
# shellcheck source=pins.env
source "$(dirname "$0")/pins.env"
source_text="${provider} ${gpu//_/ } pod ${pod_id}, rate at reservation ${reserved} (harness ledger)"
kit=issues/$issue/kit
out=results/$issue/runs
remote=$(printf 'mkdir -p %q && PRICE_USD_HR=%q PRICE_SOURCE=%q PROVIDER=%q POD_ID=%q IMAGE=%q setsid nohup bash %q/scripts/matrix.sh %q/scripts/plans/%q.tsv --out %q --work /workspace/dorado' \
    "$out" "$rate" "$source_text" "$provider" "$pod_id" "$IMAGE" "$kit" "$kit" "$plan" "$out")
for a in "$@"; do remote+=" $(printf '%q' "$a")"; done
remote+=" > results/$issue/$plan.log 2>&1 < /dev/null &"
(cd "$repo" && harness/target/release/harness ssh "$issue" -- "$remote")
echo "started $plan on $issue at \$${rate}/hr; log: results/$issue/$plan.log"
