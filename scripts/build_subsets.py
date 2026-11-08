#!/usr/bin/env python3
"""Picks the read ids of the short and long subsets, with matched total signal samples, and writes them out.

short: every signal_positive read with SHORT_MIN..SHORT_MAX samples in the short source files (155 bp synthetic
       constructs with known 5mC/5hmC sites, so about 1,900-2,100 samples each).
long:  signal_positive reads of at least LONG_MIN samples from the long source files, in read-id order, until their
       total first reaches the short subset's total.
tiny-short / tiny-long: the first TINY reads of short, and long reads matched to them, for a laptop dry run.

Matching total samples, not reads, means each subset asks the GPU for the same amount of signal; any throughput gap
between them comes from read length (padding, batching), not from the amount of work.

For each subset it writes subsets/<id>/read_ids.txt.gz and sources.json, and, when --build is given, the subset
POD5 at data/subsets/<id>/<id>.pod5 plus its manifest.json (pod5_manifest.py), which pods check against.

usage: build_subsets.py --short F.pod5... --long F.pod5... --sources sources.json [--build]
"""

import argparse
import gzip
import json
import subprocess
import sys
from pathlib import Path

import pod5

SHORT_MIN, SHORT_MAX = 1000, 6000
LONG_MIN = 50000
TINY = 2000
HERE = Path(__file__).resolve().parent


SAMPLE_OF = {}  # read id -> source file stem (5mC_rep1, control_rep1, ...), for per-sample pileups


def reads(paths):
    """(read_id, samples) of every signal_positive read, sorted by read id so the pick is reproducible."""
    out = []
    for path in paths:
        with pod5.Reader(path) as reader:
            for r in reader.reads():
                if r.end_reason.name == "signal_positive":
                    out.append((str(r.read_id), r.num_samples))
                    SAMPLE_OF[str(r.read_id)] = Path(path).stem
    return sorted(out)


def match(candidates, target):
    picked, total = [], 0
    for rid, n in candidates:
        if total >= target:
            break
        picked.append((rid, n))
        total += n
    return picked, total


def write(root, subset_id, picked, sources, note):
    d = root / "subsets" / subset_id
    d.mkdir(parents=True, exist_ok=True)
    ids = sorted(rid for rid, _ in picked)
    with gzip.open(d / "read_ids.txt.gz", "wt") as f:
        f.write("\n".join(ids) + "\n")
    with gzip.open(d / "samples.tsv.gz", "wt") as f:
        f.write("".join(f"{rid}\t{SAMPLE_OF[rid]}\n" for rid in ids))
    (d / "sources.json").write_text(json.dumps({"subset_id": subset_id, "note": note, "reads": len(ids),
                                                "total_samples": sum(n for _, n in picked),
                                                "sources": sources}, indent=1) + "\n")
    return d


def build(root, subset_id, inputs, proxy_note):
    out = root / "data" / "subsets" / subset_id
    out.mkdir(parents=True, exist_ok=True)
    ids = out / "read_ids.txt"
    with gzip.open(root / "subsets" / subset_id / "read_ids.txt.gz", "rt") as f:
        ids.write_text(f.read())
    pod5_file = out / f"{subset_id}.pod5"
    pod5_file.unlink(missing_ok=True)
    # Every id must be found: a subset missing reads would no longer match the other machines' copies.
    pod5_cli = Path(sys.executable).parent / "pod5"
    subprocess.run([str(pod5_cli), "filter", *map(str, inputs), "--ids", str(ids), "--output", str(pod5_file),
                    "--force-overwrite"], check=True)
    ids.unlink()
    subprocess.run([sys.executable, str(HERE / "pod5_manifest.py"), str(out), "--subset-id", subset_id,
                    "--source", proxy_note, "--proxy"], check=True, stdout=subprocess.DEVNULL)
    return pod5_file


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--short", nargs="+", required=True)
    ap.add_argument("--long", nargs="+", required=True)
    ap.add_argument("--sources", required=True, help="json: {file name: {url, sha256}} for every source file")
    ap.add_argument("--root", default=str(HERE.parent))
    ap.add_argument("--build", action="store_true")
    args = ap.parse_args()
    root = Path(args.root)
    src = json.loads(Path(args.sources).read_text())
    pick_src = lambda paths: [src[Path(p).name] | {"file": Path(p).name} for p in paths]

    short_all = reads(args.short)
    short = [(r, n) for r, n in short_all if SHORT_MIN <= n <= SHORT_MAX]
    target = sum(n for _, n in short)
    long_all = [(r, n) for r, n in reads(args.long) if n >= LONG_MIN]
    long_, long_total = match(long_all, target)
    if long_total < target:
        sys.exit(f"long sources hold {long_total} samples in reads >= {LONG_MIN}, short subset needs {target}")
    tiny_short = short[:TINY]
    tiny_long, _ = match(long_all, sum(n for _, n in tiny_short))

    short_note = ("ONT open data modbase-validation_2024.10 subset/ (155 bp synthetic constructs, 5mC/5hmC "
                  f"ground truth), signal_positive reads of {SHORT_MIN}-{SHORT_MAX} samples; proxy, not cfDNA")
    long_note = ("ONT open data giab_2025.01 HG002 PAW70337 (genomic DNA), signal_positive reads of "
                 f">= {LONG_MIN} samples in read-id order, total matched to the short subset; proxy, not cfDNA")
    plan = [("short-155bp", short, args.short, short_note), ("long-hg002", long_, args.long, long_note),
            ("tiny-short", tiny_short, args.short, short_note + "; first 2000 reads"),
            ("tiny-long", tiny_long, args.long, long_note + "; matched to tiny-short")]
    for subset_id, picked, inputs, note in plan:
        write(root, subset_id, picked, pick_src(inputs), note)
        total = sum(n for _, n in picked)
        print(f"{subset_id}: {len(picked)} reads, {total} samples")
        if args.build:
            print("  built", build(root, subset_id, inputs, note))
    print(f"short candidates outside {SHORT_MIN}-{SHORT_MAX}: {len(short_all) - len(short)} of {len(short_all)}")


if __name__ == "__main__":
    main()
