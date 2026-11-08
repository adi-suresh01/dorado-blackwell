#!/usr/bin/env python3
"""Writes manifest.json for a directory of POD5 files: what make_verdict.py reports as the run's data.

The read-id digest identifies a subset across machines: the pod rebuilds a subset from the same source file and
read-id list, and the digest, read count and total samples must all match the laptop's before any run.

usage: pod5_manifest.py DIR --subset-id ID --source TEXT [--proxy | --no-proxy] [--check EXPECTED.json]
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pod5


def summarize(directory):
    ids, total, rates, lengths = [], 0, set(), []
    for path in sorted(Path(directory).glob("*.pod5")):
        with pod5.Reader(path) as reader:
            for read in reader.reads():
                ids.append(str(read.read_id))
                n = read.num_samples
                total += n
                lengths.append(n)
                rates.add(read.run_info.sample_rate)
    ids.sort()
    lengths.sort()
    pct = lambda p: lengths[min(len(lengths) - 1, int(p * len(lengths)))] if lengths else None
    return {
        "reads": len(ids),
        "total_samples": total,
        "sample_rate_hz": rates.pop() if len(rates) == 1 else None,
        "sample_rates_seen": sorted(rates) if len(rates) > 1 else None,
        "read_ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
        "samples_per_read": {"min": pct(0), "p10": pct(0.1), "median": pct(0.5), "p90": pct(0.9),
                             "max": lengths[-1] if lengths else None},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--subset-id", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--proxy", action=argparse.BooleanOptionalAction, required=True,
                    help="--proxy when the reads are not cfDNA")
    ap.add_argument("--check", help="manifest the laptop wrote; exit 1 unless reads, samples and ids match")
    args = ap.parse_args()
    manifest = {"subset_id": args.subset_id, "source": args.source, "proxy": args.proxy,
                **summarize(args.directory)}
    if args.check:
        want = json.loads(Path(args.check).read_text())
        keys = ("reads", "total_samples", "read_ids_sha256", "sample_rate_hz")
        bad = [k for k in keys if want.get(k) != manifest.get(k)]
        if bad:
            print(f"subset {args.subset_id} differs from {args.check} in {bad}", file=sys.stderr)
            sys.exit(1)
    out = Path(args.directory) / "manifest.json"
    out.write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
