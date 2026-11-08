#!/usr/bin/env bash
# Prepares a GPU pod: Dorado at the pinned build, the pinned models, a Python venv with pod5 and pysam, and every
# subset rebuilt from its S3 sources and checked against the laptop's manifest. Runs once per pod.
#
# usage: pod_setup.sh KIT_DIR [--soak-files N] [--soak-copies K] [--with-dorado VERSION]
#   KIT_DIR holds scripts/, subsets/ and references/ (a copy of this repo's). --soak-files also downloads the first
#   N HG002 PAW70337 POD5 files listed in subsets/soak.txt for the crash soak (dorado#1507), unsubsetted.
#   --soak-copies lists each soak file K times in the soak folder (symlinks), so one Dorado process can run longer
#   than the downloaded signal lasts; the crash needs one long-lived process, and Dorado 2.1.2 does not skip
#   repeated read ids (3 links to one 2,000-read file gave 6,000 reads on the laptop).
#   --with-dorado installs another pinned release beside the main one (pins.env DORADO_<x_y_z>_LINUX_*).
set -euo pipefail

kit=$(cd "$1" && pwd)
shift
soak_files=0
soak_copies=1
extra_versions=()
while (($#)); do
    case $1 in
        --soak-files) soak_files=$2; shift 2 ;;
        --soak-copies) soak_copies=$2; shift 2 ;;
        --with-dorado) extra_versions+=("$2"); shift 2 ;;
        *) echo "unknown argument $1" >&2; exit 2 ;;
    esac
done
# shellcheck source=pins.env
source "$kit/scripts/pins.env"
W=${WORKDIR:-/workspace/dorado}
mkdir -p "$W"/{dl,models,subsets,soak}

fetch() {  # url dest sha256: resumable, then verified, so a half-written file is never used
    local url=$1 dest=$2 want=$3
    if [[ -f $dest ]] && echo "$want  $dest" | sha256sum -c --status; then
        return 0
    fi
    curl -fL --retry 5 --retry-delay 5 -C - -o "$dest" "$url"
    echo "$want  $dest" | sha256sum -c --status || { echo "sha256 mismatch: $dest" >&2; exit 1; }
}

install_dorado() {  # version url sha256: the archive (3.2-3.5 GB) is deleted once unpacked to spare the volume
    local ver=$1 url=$2 sha=$3
    if [[ ! -x $W/dorado-$ver-linux-x64/bin/dorado ]]; then
        fetch "$url" "$W/dl/dorado-$ver.tar.gz" "$sha"
        tar -xzf "$W/dl/dorado-$ver.tar.gz" -C "$W"
        rm "$W/dl/dorado-$ver.tar.gz"
    fi
    "$W/dorado-$ver-linux-x64/bin/dorado" --version
}

echo "== dorado $DORADO_VERSION"
install_dorado "$DORADO_VERSION" "$DORADO_LINUX_URL" "$DORADO_LINUX_SHA256"
D=$W/dorado-$DORADO_VERSION-linux-x64/bin/dorado
for ver in ${extra_versions[@]+"${extra_versions[@]}"}; do
    url_var="DORADO_${ver//./_}_LINUX_URL"
    sha_var="DORADO_${ver//./_}_LINUX_SHA256"
    [[ -n ${!url_var:-} && -n ${!sha_var:-} ]] || { echo "dorado $ver is not pinned in pins.env" >&2; exit 1; }
    install_dorado "$ver" "${!url_var}" "${!sha_var}"
done

echo "== modkit $MODKIT_VERSION"
fetch "$MODKIT_URL" "$W/dl/modkit.tar.gz" "$MODKIT_SHA256"
if [[ ! -x $W/modkit ]]; then
    tar -xzf "$W/dl/modkit.tar.gz" -C "$W/dl"
    cp "$(find "$W/dl" -maxdepth 2 -type f -name modkit | head -n 1)" "$W/modkit"
fi
"$W/modkit" --version

echo "== python venv"
if [[ ! -x $W/venv/bin/python ]]; then
    python3 -m venv "$W/venv"
    "$W/venv/bin/pip" install -q "pod5==$POD5_VERSION" "pysam==$PYSAM_VERSION"
fi
"$W/venv/bin/python" -c "import pod5, pysam; print('pod5', pod5.__version__, 'pysam', pysam.__version__)"

echo "== models"
for m in "$M_HAC52" "$M_SUP52" "$M_HAC60" "$M_HAC52_5MC5HMC" "$M_SUP52_5MC5HMC" "$M_HAC60_5MC5HMC" \
        "$M_SUP52_4MC5MC" "$M_SUP52_6MA"; do
    [[ -d $W/models/$m ]] || "$D" download --model "$m" --models-directory "$W/models" 2>&1 | tail -n 1
done
ls "$W/models"

echo "== subsets"
py=$W/venv/bin/python
"$py" - "$kit/subsets/sources.json" "$W/dl" <<'EOF' > "$W/dl/fetch.tsv"
import json, sys
for name, s in json.load(open(sys.argv[1])).items():
    print(s["url"], f"{sys.argv[2]}/{name}", s["sha256"], sep="\t")
EOF
while IFS=$'\t' read -r url dest sha; do
    fetch "$url" "$dest" "$sha"
done < "$W/dl/fetch.tsv"
for sdir in "$kit"/subsets/*/; do
    id=$(basename "$sdir")
    [[ -f $sdir/manifest.json ]] || continue
    out=$W/subsets/$id
    mkdir -p "$out"
    if [[ ! -f $out/manifest.json ]]; then
        inputs=$("$py" -c "import json,sys; print(' '.join('$W/dl/'+s['file'] for s in json.load(open('$sdir/sources.json'))['sources']))")
        gunzip -c "$sdir/read_ids.txt.gz" > "$out/read_ids.txt"
        # shellcheck disable=SC2086
        "$W/venv/bin/pod5" filter $inputs --ids "$out/read_ids.txt" --output "$out/$id.pod5" --force-overwrite \
            > "$out/filter.log" 2>&1
        rm "$out/read_ids.txt"
        source_text=$("$py" -c "import json; print(json.load(open('$sdir/manifest.json'))['source'])")
        "$py" "$kit/scripts/pod5_manifest.py" "$out" --subset-id "$id" --source "$source_text" --proxy \
            --check "$sdir/manifest.json" > /dev/null
    fi
    echo "subset $id ok: $("$py" -c "import json; m=json.load(open('$out/manifest.json')); print(m['reads'], 'reads', m['total_samples'], 'samples')")"
done

if ((soak_files > 0)); then
    echo "== soak data ($soak_files files)"
    head -n "$soak_files" "$kit/subsets/soak.txt" | while read -r url; do
        dest=$W/soak/$(basename "$url")
        [[ -f $dest ]] || curl -fL --retry 5 --retry-delay 5 -o "$dest" "$url"
        for ((k = 2; k <= soak_copies; k++)); do
            ln -sfn "$(basename "$url")" "$W/soak/copy${k}_$(basename "$url")"
        done
    done
    du -sh "$W/soak"
    echo "soak folder lists $(find "$W/soak" -name '*.pod5' | wc -l) POD5 files ($soak_files downloaded x $soak_copies)"
fi
df -h "$W" | tail -n 1
echo "setup done"
