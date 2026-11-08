#!/usr/bin/env python3
"""Builds the result tables from runs/*/verdict.json: results/throughput.csv and results/determinism.csv.

throughput: one row per (GPU, config) with the median samples/s over its repeats, the spread between repeats, the
  useful (non-padding) fraction, reads/s, and the cost per gigabase at the pod's rental rate.
determinism: one row per config with the call digests per GPU, so identical calls across repeats, batch sizes and
  GPUs show as one digest.

Every input is proxy data (see README); the CSVs carry a proxy column so no table drops the label.

usage: tables.py [--runs runs] [--out results]
"""

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

SHORT = {"NVIDIA GeForce RTX 5090": "RTX 5090", "NVIDIA RTX PRO 6000 Blackwell Server Edition": "RTX PRO 6000 Server",
         "NVIDIA H100 PCIe": "H100 PCIe"}


def gpu_label(v):
    name = SHORT.get(v["host"]["gpu_name"], v["host"]["gpu_name"])
    n = v["host"]["gpu_count"] or 1
    return f"{n}x {name}" if n > 1 else name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    groups = defaultdict(list)
    for p in Path(args.runs).glob("*/verdict.json"):
        v = json.loads(p.read_text())
        if v["question"] == "smoke":
            continue
        groups[(gpu_label(v), v["config_id"])].append(v)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "throughput.csv", "w", newline="") as f:
        w = csv.writer(f)
        # usd_per_gbase uses wall time (model load included, which a 1 GB run magnifies); the steady-state figure
        # uses Dorado's own basecalling time, closer to what a long production job pays per gigabase.
        w.writerow(["gpu", "config", "subset", "proxy", "model", "mods", "batch_used", "repeats", "crashed",
                    "samples_per_s_median", "repeat_spread_pct", "useful_fraction", "reads_per_s_median",
                    "usd_hr", "usd_per_gbase_median", "usd_per_gbase_steady", "dorado"])
        for (gpu, config), vs in sorted(groups.items(), key=lambda x: (x[0][1], x[0][0])):
            rates = [v["throughput"]["samples_per_s"] for v in vs if v["throughput"]["samples_per_s"]]
            reads = [v["throughput"]["reads_per_s"] for v in vs if v["throughput"]["reads_per_s"]]
            cost = [v["cost"]["usd_per_gbase"] for v in vs if v["cost"]["usd_per_gbase"]]
            useful = [v["throughput"]["useful_fraction"] for v in vs if v["throughput"]["useful_fraction"]]
            spread = 100 * (max(rates) - min(rates)) / statistics.median(rates) if len(rates) > 1 else None
            steady = [v["cost"]["usd_hr"] * (v["result"]["dorado_finished_ms"] / 3.6e6) / (v["output"]["bases_out"] / 1e9)
                      for v in vs if v["cost"]["usd_hr"] and v["result"]["dorado_finished_ms"] and v["output"]["bases_out"]]
            v0 = vs[0]
            w.writerow([gpu, config, v0["data"]["subset_id"], v0["data"]["proxy"], v0["dorado"]["simplex_model"],
                        ";".join(v0["dorado"]["mods_models"]), v0["batching"]["batchsize_used"], len(vs),
                        sum(v["result"]["crashed"] for v in vs),
                        f"{statistics.median(rates):.4g}" if rates else "",
                        f"{spread:.1f}" if spread is not None else "",
                        f"{statistics.median(useful):.3f}" if useful else "",
                        f"{statistics.median(reads):.1f}" if reads else "", v0["cost"]["usd_hr"],
                        f"{statistics.median(cost):.4f}" if cost else "",
                        f"{statistics.median(steady):.4f}" if steady else "", v0["dorado"]["version"]])

    by_config = defaultdict(lambda: defaultdict(set))
    for (gpu, config), vs in groups.items():
        for v in vs:
            if v["output"]["records_sha256"]:
                by_config[config][gpu].add(v["output"]["records_sha256"][:12])
    with open(out / "determinism.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["config", "gpu_a", "gpu_b", "identical_calls", "digest_a", "digest_b"])
        for config in sorted(by_config):
            gpus = by_config[config]
            names = sorted(gpus)
            for gpu in names:  # repeats on one GPU
                w.writerow([config, gpu, gpu, len(gpus[gpu]) == 1, ";".join(sorted(gpus[gpu])), ""])
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    w.writerow([config, a, b, gpus[a] == gpus[b] and len(gpus[a]) == 1,
                                ";".join(sorted(gpus[a])), ";".join(sorted(gpus[b]))])
    print(f"{len(groups)} (gpu, config) groups -> {out}/throughput.csv, {out}/determinism.csv")


if __name__ == "__main__":
    main()
