#!/usr/bin/env python3
"""Writes results/q4_pileups.csv: per-CpG 5mC/5hmC shifts between pairs of runs, per sample and coverage floor,
plus each run's score against the synthetic constructs' ground truth.

Pairs: every GPU against the RTX 5090 for the same config (a GPU swap), and two same-GPU config changes on the
5090 (chunk size; SUP variable chunks off), for scale. Pileups come from pileup.sh (run r1 of each config).

usage: q4_table.py [--runs runs] [--out results/q4_pileups.csv]
"""

import argparse
import csv
from pathlib import Path

from compare_pileups import fasta, is_cpg, pileup, score, stats, truth

GPUS = {"NVIDIA-GeForce-RTX-5090": "RTX 5090", "NVIDIA-RTX-PRO-6000-Blackwell-Server-Edition": "RTX PRO 6000 Server",
        "NVIDIA-H100-PCIe": "H100 PCIe"}
CONFIGS = ["q4-sup52-mods-short-b256", "q3-hac52-mods-short", "q4-hac60-mods-short-b256"]
KNOBS = [("q3-hac52-mods-short", "q3-hac52-mods-short-c3000", "chunk size 3000 vs default (HAC v5.2)"),
         ("q4-sup52-mods-short-b256", "q3-sup52-mods-short-fixedchunk", "variable chunks off vs on (SUP v5.2)")]
SAMPLES = ["5mC_rep1", "5hmC_rep1", "control_rep1"]
HERE = Path(__file__).resolve().parent


def run_dir(runs, gpu, config):
    hits = sorted(Path(runs).glob(f"{gpu}_{config}_r1_*"))
    return hits[0] if hits else None


def shifts(ref, a, b, code, min_cov):
    diffs = []
    for key in a.keys() & b.keys():
        if not is_cpg(ref, *key):
            continue
        ca, cb = a[key].get(code), b[key].get(code)
        if ca and cb and ca[0] >= min_cov and cb[0] >= min_cov:
            diffs.append(cb[1] - ca[1])
    return stats(diffs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="results/q4_pileups.csv")
    args = ap.parse_args()
    refdir = HERE.parent / "references"
    ref = fasta(refdir / "all_5mers.fa")
    truths = {"5mC_rep1": ("m", truth(refdir / "all_5mers_5mC_sites.bed")),
              "5hmC_rep1": ("h", truth(refdir / "all_5mers_5hmC_sites.bed"))}
    pairs = []
    for config in CONFIGS:
        for gpu in GPUS:
            if gpu != "NVIDIA-GeForce-RTX-5090":
                pairs.append((f"GPU swap: RTX 5090 -> {GPUS[gpu]}", config,
                              run_dir(args.runs, "NVIDIA-GeForce-RTX-5090", config), run_dir(args.runs, gpu, config)))
    for base, other, label in KNOBS:
        pairs.append((f"same GPU (RTX 5090): {label}", base, run_dir(args.runs, "NVIDIA-GeForce-RTX-5090", base),
                      run_dir(args.runs, "NVIDIA-GeForce-RTX-5090", other)))
    cols = ["comparison", "config", "sample", "min_cov", "mod", "cpg_sites", "mean_abs_diff_pts", "p99_abs_diff_pts",
            "max_abs_diff_pts", "sites_over_1pt", "truth_pct_a", "truth_pct_b", "proxy"]
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for label, config, da, db in pairs:
            if not da or not db:
                continue
            for sample in SAMPLES:
                pa, pb = da / f"pileup.{sample}.bed", db / f"pileup.{sample}.bed"
                if not (pa.exists() and pb.exists()):
                    continue
                a, b = pileup(pa), pileup(pb)
                for min_cov in (20, 500):
                    for code, name in (("m", "5mC"), ("h", "5hmC")):
                        s = shifts(ref, a, b, code, min_cov)
                        ta = tb = ""
                        if sample in truths and truths[sample][0] == code:
                            sa, sb = (score(x, truths[sample][1], code, min_cov) for x in (a, b))
                            ta = f"{sa['mean_pct_at_true_sites']:.2f}" if sa["mean_pct_at_true_sites"] else ""
                            tb = f"{sb['mean_pct_at_true_sites']:.2f}" if sb["mean_pct_at_true_sites"] else ""
                        fmt = lambda k: f"{s[k]:.3f}" if k in s else ""
                        w.writerow([label, config, sample, min_cov, name, s["sites"], fmt("mean_abs_diff_pct"),
                                    fmt("p99_abs_diff_pct"), fmt("max_abs_diff_pct"), s.get("sites_over_1pct", ""),
                                    ta, tb, True])
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
