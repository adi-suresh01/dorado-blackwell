#!/usr/bin/env python3
"""Collects runs/*/verdict.json into results/summary.csv, one row per run, measured fields only.

A verdict written on a pod without pysam has null BAM fields; this fills them from the pulled calls.bam (and the
cost per gigabase that depends on them) and writes the verdict back, so the CSV and the JSON agree.

usage: summarize.py [--runs runs] [--out results/summary.csv]
"""

import argparse
import csv
import json
from pathlib import Path

from make_verdict import bam_stats

COLUMNS = [
    ("run_id", "run_id"), ("question", "question"), ("config_id", "config_id"), ("repeat", "repeat"),
    ("gpu", "host.gpu_name"), ("gpus", "host.gpu_count"), ("provider", "host.provider"),
    ("driver", "host.driver_version"), ("dorado", "dorado.version"), ("model", "dorado.simplex_model"),
    ("mods", "dorado.mods_models"), ("subset", "data.subset_id"), ("proxy", "data.proxy"),
    ("device", "args.device"), ("batch_req", "args.batchsize_requested"), ("chunk_req", "args.chunksize_requested"),
    ("batch_used", "batching.batchsize_used"), ("chunk_used", "batching.chunksize_used"),
    ("batch_from_table", "batching.batchsize_from_benchmark_table"),
    ("crashed", "result.crashed"), ("exit_code", "result.exit_code"), ("first_error", "result.error_lines"),
    ("wall_s", "result.wall_s"), ("samples_per_s", "throughput.samples_per_s"),
    ("useful_fraction", "throughput.useful_fraction"), ("reads_per_s", "throughput.reads_per_s"),
    ("peak_vram_mib", "throughput.peak_vram_mib"), ("mean_power_w", "throughput.mean_power_w"),
    ("reads_out", "output.reads_out"), ("bases_out", "output.bases_out"), ("mean_qscore", "output.mean_qscore"),
    ("records_sha256", "output.records_sha256"), ("usd_hr", "cost.usd_hr"), ("usd_run", "cost.usd_run"),
    ("usd_per_gbase", "cost.usd_per_gbase"), ("price_source", "cost.usd_hr_source"),
]


def get(d, dotted):
    for key in dotted.split("."):
        d = d.get(key) if isinstance(d, dict) else None
    if isinstance(d, list):
        return d[0] if dotted == "result.error_lines" and d else ";".join(map(str, d))
    return d


def backfill(verdict, run_dir):
    out = verdict["output"]
    if out.get("bam") and out.get("records_sha256") is None:
        stats = bam_stats(run_dir / out["bam"])
        if stats["records_sha256"]:
            out.update(stats)
            cost = verdict["cost"]
            if cost.get("usd_run") is not None and out["bases_out"]:
                cost["usd_per_gbase"] = round(cost["usd_run"] / (out["bases_out"] / 1e9), 4)
            (run_dir / "verdict.json").write_text(json.dumps(verdict, indent=1) + "\n")
    return verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="results/summary.csv")
    args = ap.parse_args()
    rows = []
    for path in sorted(Path(args.runs).glob("*/verdict.json")):
        v = backfill(json.loads(path.read_text()), path.parent)
        rows.append({name: get(v, dotted) for name, dotted in COLUMNS})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[name for name, _ in COLUMNS])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} runs -> {args.out}")


if __name__ == "__main__":
    main()
