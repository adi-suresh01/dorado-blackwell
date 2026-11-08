#!/usr/bin/env bash
# One Dorado basecall run -> <out>/<run_id>/{cmd.txt,dorado.log,gpu.csv,calls.bam,run.json,verdict.json}.
# A crash is a result, not a script failure: the run's exit code and error lines go into verdict.json and this
# script still exits 0, so a matrix keeps going. It exits non-zero only when its own inputs are wrong.
set -euo pipefail

usage() {
    cat >&2 <<'EOF'
run_dorado.sh --question Q2 --config q2-sup52-mods-long --repeat 1 --model DIR --data POD5_DIR --subset ID
              [--mods DIR[,DIR]] [--device cuda:all] [--batchsize 0] [--chunksize N] [--overlap N]
              [--mods-batchsize N] [--out runs] [--dorado BIN] [--gpu-tag TAG] [--time-limit S]
              [--bam keep|drop|none] [-- extra dorado args]
--bam: keep calls.bam (default); drop it once its stats are in the verdict; or never write it (soak).
Env: PRICE_USD_HR, PRICE_SOURCE, PROVIDER, POD_ID, IMAGE, DORADO_BUILD_SHA256, MANIFEST (subset manifest json)
EOF
    exit 2
}

question="" config="" repeat="" model="" data="" subset="" mods="" device="" batchsize=0
chunksize="" overlap="" mods_batchsize="" out="runs" dorado="dorado" gpu_tag="" time_limit="" bam=keep
extra=()
while (($#)); do
    case $1 in
        --question) question=$2; shift 2 ;;
        --config) config=$2; shift 2 ;;
        --repeat) repeat=$2; shift 2 ;;
        --model) model=$2; shift 2 ;;
        --data) data=$2; shift 2 ;;
        --subset) subset=$2; shift 2 ;;
        --mods) mods=$2; shift 2 ;;
        --device) device=$2; shift 2 ;;
        --batchsize) batchsize=$2; shift 2 ;;
        --chunksize) chunksize=$2; shift 2 ;;
        --overlap) overlap=$2; shift 2 ;;
        --mods-batchsize) mods_batchsize=$2; shift 2 ;;
        --out) out=$2; shift 2 ;;
        --dorado) dorado=$2; shift 2 ;;
        --gpu-tag) gpu_tag=$2; shift 2 ;;
        --time-limit) time_limit=$2; shift 2 ;;
        --bam) bam=$2; shift 2 ;;
        --) shift; extra=("$@"); break ;;
        *) usage ;;
    esac
done
[[ -n $question && -n $config && -n $repeat && -n $model && -n $data && -n $subset ]] || usage
[[ -d $model ]] || { echo "model dir not found: $model" >&2; exit 2; }
[[ -e $data ]] || { echo "data not found: $data" >&2; exit 2; }
[[ $bam =~ ^(keep|drop|none)$ ]] || usage

now() { python3 -c 'import time; print(f"{time.time():.3f}")'; }
has_nvidia=0
command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1 && has_nvidia=1
if [[ -z $device ]]; then
    device=$([[ $has_nvidia == 1 ]] && echo cuda:all || echo metal)
fi
if [[ -z $gpu_tag ]]; then
    if [[ $has_nvidia == 1 ]]; then
        gpu_tag=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1 | tr -cs 'A-Za-z0-9' '-' | sed 's/-$//')
    else
        gpu_tag=$(uname -m)-local
    fi
fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
run_id="${gpu_tag}_${config}_r${repeat}_${stamp}"
dir="$out/$run_id"
mkdir -p "$dir"

cmd=("$dorado" basecaller "$model" "$data" --device "$device" --batchsize "$batchsize" -v)
[[ -n $mods ]] && cmd+=(--modified-bases-models "$mods")
[[ -n $chunksize ]] && cmd+=(--chunksize "$chunksize")
[[ -n $overlap ]] && cmd+=(--overlap "$overlap")
[[ -n $mods_batchsize ]] && cmd+=(--modified-bases-batchsize "$mods_batchsize")
cmd+=(${extra[@]+"${extra[@]}"})
printf '%q ' "${cmd[@]}" > "$dir/cmd.txt"
echo >> "$dir/cmd.txt"

sampler=""
if [[ $has_nvidia == 1 ]]; then
    # 1 s samples bound peak VRAM and mean power; a shorter interval would load the CPU the basecaller also uses.
    nvidia-smi --query-gpu=timestamp,index,utilization.gpu,memory.used,power.draw,clocks.sm,temperature.gpu \
        --format=csv,noheader,nounits -l 1 > "$dir/gpu.csv" 2>/dev/null &
    sampler=$!
fi

echo "run $run_id: ${cmd[*]}" >&2
bam_out=$dir/calls.bam
[[ $bam == none ]] && bam_out=/dev/null
t0=$(now)
set +e
if [[ -n $time_limit ]]; then
    # A soak ends at its time box with SIGINT, so GNU timeout's 124 marks a run we stopped, not one that crashed.
    timeout --signal=INT --kill-after=120 "$time_limit" "${cmd[@]}" > "$bam_out" 2> "$dir/dorado.log"
else
    "${cmd[@]}" > "$bam_out" 2> "$dir/dorado.log"
fi
rc=$?
set -e
t1=$(now)
[[ -n $sampler ]] && kill "$sampler" 2>/dev/null && wait "$sampler" 2>/dev/null || true

python3 - "$dir/run.json" <<EOF
import json, os, sys
json.dump({
    "run_id": "$run_id", "question": "$question", "config_id": "$config", "repeat": int("$repeat"),
    "started_utc": "$stamp", "exit_code": $rc, "t0": $t0, "t1": $t1,
    "device": "$device", "batchsize": int("$batchsize"),
    "chunksize": int("$chunksize") if "$chunksize" else None,
    "overlap": int("$overlap") if "$overlap" else None,
    "mods_batchsize": int("$mods_batchsize") if "$mods_batchsize" else None,
    "model": "$model", "mods": [m for m in "$mods".split(",") if m], "subset": "$subset", "data": "$data",
    "dorado": "$dorado", "time_limit_s": int("$time_limit") if "$time_limit" else None,
    "env": {k: v for k, v in os.environ.items() if k.startswith(("CUDA_", "DORADO_"))},
}, open(sys.argv[1], "w"), indent=1)
EOF
BAM_POLICY=$bam python3 "$(dirname "$0")/make_verdict.py" "$dir"
echo "run $run_id exit=$rc wall=$(python3 -c "print(round($t1-$t0,1))")s -> $dir/verdict.json" >&2
