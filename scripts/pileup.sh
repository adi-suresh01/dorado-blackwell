#!/usr/bin/env bash
# Aligns one run's calls.bam to a reference and writes modkit per-site pileups: <run_dir>/pileup.bed for all reads,
# and with a samples table pileup.<sample>.bed per sample, for scoring against each sample's own ground truth.
#
# Only primary alignments go in, in an order fixed by the records alone (split_primary.py says why both matter).
# --no-filtering keeps every call: modkit's default pass threshold is estimated from each BAM's own probabilities,
# so two runs would be filtered at different thresholds and a difference between them could come from the filter.
# With both, byte-identical calls from two GPUs gave byte-identical pileups.
#
# usage: pileup.sh RUN_DIR REF.fa SAMPLES.tsv.gz|- DORADO_BIN PYTHON MODKIT...
#   MODKIT is the command that runs modkit, e.g. /workspace/dorado/modkit, or on the laptop
#   docker run --rm --platform linux/amd64 -v "$root:$root" ubuntu:24.04 $root/tools/modkit-linux/.../modkit
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
run_dir=$(cd "$1" && pwd)
ref=$(cd "$(dirname "$2")" && pwd)/$(basename "$2")
samples=$3
dorado=$4
py=$5
shift 5
modkit=("$@")

"$dorado" aligner "$ref" "$run_dir/calls.bam" > "$run_dir/aligned.unsorted.bam" 2> "$run_dir/aligner.log"
if [[ $samples == - ]]; then
    "$py" "$here/split_primary.py" "$run_dir/aligned.unsorted.bam" "$run_dir/aligned"
else
    "$py" "$here/split_primary.py" "$run_dir/aligned.unsorted.bam" "$run_dir/aligned" "$samples"
fi
rm "$run_dir/aligned.unsorted.bam"
for bam in "$run_dir"/aligned*.bam; do
    tag=$(basename "$bam" .bam)
    tag=${tag#aligned}
    "${modkit[@]}" pileup "$bam" "$run_dir/pileup$tag.bed" --ref "$ref" --no-filtering \
        --log-filepath "$run_dir/modkit$tag.log" > /dev/null 2>&1
    echo "$run_dir/pileup$tag.bed: $(wc -l < "$run_dir/pileup$tag.bed") sites"
done
