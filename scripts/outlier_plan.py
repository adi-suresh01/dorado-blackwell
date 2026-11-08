#!/usr/bin/env python3
"""Writes a plan of third repeats for configs whose two repeats disagree on samples/s by more than RATIO.

The calls of such pairs were identical, so the gap is timing noise on the pod (a cold page cache, a results pull
compressing files on the same CPU), not Dorado. A third run with a warm cache shows which repeat was the outlier.

usage: outlier_plan.py PLAN.tsv RUNS_DIR GPU_NAME OUT.tsv [--ratio 1.15]
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("runs")
    ap.add_argument("gpu")
    ap.add_argument("out")
    ap.add_argument("--ratio", type=float, default=1.15)
    args = ap.parse_args()
    rates = defaultdict(dict)
    for p in Path(args.runs).glob("*/verdict.json"):
        v = json.loads(p.read_text())
        if v["host"]["gpu_name"] == args.gpu and v["throughput"]["samples_per_s"]:
            rates[v["config_id"]][v["repeat"]] = v["throughput"]["samples_per_s"]
    noisy = {c for c, r in rates.items() if 1 in r and 2 in r and 3 not in r
             and max(r[1], r[2]) / min(r[1], r[2]) > args.ratio}
    rows = []
    for line in Path(args.plan).read_text().splitlines():
        f = line.split("\t")
        if line.startswith("#") or len(f) < 11 or f[1] not in noisy or f[2] != "1":
            continue
        f[2] = "3"
        rows.append("\t".join(f))
    header = (f"# Third repeats for configs whose r1 and r2 samples/s differ by more than {args.ratio}x on {args.gpu}\n"
              "# (written by outlier_plan.py; same columns as the source plan)\n")
    Path(args.out).write_text(header + "".join(r + "\n" for r in rows))
    print(f"{len(rows)} configs to repeat: {', '.join(sorted(noisy)) or 'none'}")


if __name__ == "__main__":
    main()
