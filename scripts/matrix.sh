#!/usr/bin/env bash
# Runs a plan (plans/*.tsv) row by row through run_dorado.sh. A row whose config and repeat already have a verdict
# in --out is skipped, so a pod that restarted continues where it stopped.
#
# usage: matrix.sh PLAN.tsv --out DIR --work /workspace/dorado [--device cuda:0] [--only REGEX] [--gpu-tag TAG]
# Env (passed through to every verdict): PRICE_USD_HR, PRICE_SOURCE, PROVIDER, POD_ID, IMAGE
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
plan=$1
shift
out="" work="" device="" only="." gpu_tag=""
while (($#)); do
    case $1 in
        --out) out=$2; shift 2 ;;
        --work) work=$2; shift 2 ;;
        --device) device=$2; shift 2 ;;
        --only) only=$2; shift 2 ;;
        --gpu-tag) gpu_tag=$2; shift 2 ;;
        *) echo "unknown argument $1" >&2; exit 2 ;;
    esac
done
[[ -n $out && -n $work && -f $plan ]] || { echo "usage: matrix.sh PLAN.tsv --out DIR --work DIR" >&2; exit 2; }
# shellcheck source=pins.env
source "$here/pins.env"
export PATH="$work/venv/bin:$PATH"
mkdir -p "$out"

done_already() {  # config repeat
    python3 - "$out" "$1" "$2" <<'EOF'
import json, sys
from pathlib import Path
out, config, repeat = sys.argv[1], sys.argv[2], int(sys.argv[3])
for v in Path(out).glob("*/verdict.json"):
    d = json.loads(v.read_text())
    if d["config_id"] == config and d["repeat"] == repeat:
        sys.exit(0)
sys.exit(1)
EOF
}

grep -v '^#' "$plan" | grep -v '^[[:space:]]*$' | while IFS=$'\t' read -r question config repeat model mods subset \
        batch chunk tlimit dver extra; do
    [[ $config =~ $only ]] || continue
    if done_already "$config" "$repeat"; then
        echo "skip $config r$repeat: verdict exists" >&2
        continue
    fi
    mvar="M_$model"
    args=(--question "$question" --config "$config" --repeat "$repeat" --model "$work/models/${!mvar}"
          --subset "$subset" --batchsize "$batch" --out "$out")
    if [[ $mods != - ]]; then
        # A comma list (SUP52_4MC5MC,SUP52_6MA) runs several mods models at once, as dorado#1507's crashes did.
        paths=()
        IFS=, read -ra modnames <<< "$mods"
        for name in "${modnames[@]}"; do
            modvar="M_$name"
            paths+=("$work/models/${!modvar}")
        done
        args+=(--mods "$(IFS=,; echo "${paths[*]}")")
    fi
    # Only short-read calls feed the per-site pileups; long-read runs keep their stats and call digest in the
    # verdict, and a soak's calls (many GB) are never written.
    if [[ $subset == soak ]]; then
        args+=(--data "$work/soak" --bam none)
        manifest=""
    else
        args+=(--data "$work/subsets/$subset")
        manifest="$work/subsets/$subset/manifest.json"
        [[ $subset == long-* ]] && args+=(--bam drop)
        # On the 5090 the first run over a just-written subset ran 4x slower than its repeat with identical calls:
        # a cold page cache on the pod volume. Reading the subset (1 GB) first keeps disk speed out of samples/s.
        cat "$work/subsets/$subset"/*.pod5 > /dev/null
    fi
    [[ $chunk != - ]] && args+=(--chunksize "$chunk")
    [[ $tlimit != - ]] && args+=(--time-limit "$tlimit")
    [[ -n $device ]] && args+=(--device "$device")
    [[ -n $gpu_tag ]] && args+=(--gpu-tag "$gpu_tag")
    ver=${dver/#-/$DORADO_VERSION}
    args+=(--dorado "$work/dorado-$ver-linux-x64/bin/dorado")
    if [[ $ver == "$DORADO_VERSION" ]]; then
        build_sha=$DORADO_LINUX_SHA256
    else
        shavar="DORADO_${ver//./_}_LINUX_SHA256"
        build_sha=${!shavar:-}
    fi
    [[ $extra != - ]] && args+=(-- $extra)
    MANIFEST=$manifest DORADO_BUILD_SHA256=$build_sha "$here/run_dorado.sh" "${args[@]}" < /dev/null
done
echo "plan $plan done" >&2
