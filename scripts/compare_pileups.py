#!/usr/bin/env python3
"""Compares two modkit pileups site by site: how far the per-site 5mC and 5hmC percentages move between runs.

Sites are (contig, position, strand); a site counts only with at least --min-cov valid calls in both pileups, since a
percentage over a handful of reads moves by itself. CpG sites (C then G on the reference) are reported apart from
all C sites. With --truth BEDs it also scores each pileup against the known modified positions of the synthetic
constructs: the mean percent called at true sites and at the other C sites.

usage: compare_pileups.py A.bed B.bed --ref REF.fa --label-a X --label-b Y [--min-cov 20]
                          [--truth-5mC BED] [--truth-5hmC BED] [--json out.json]
"""

import argparse
import json
import statistics


def fasta(path):
    seqs, name = {}, None
    for line in open(path):
        line = line.strip()
        if line.startswith(">"):
            name = line[1:].split()[0]
            seqs[name] = []
        elif name:
            seqs[name].append(line.upper())
    return {k: "".join(v) for k, v in seqs.items()}


def pileup(path):
    """{(contig, pos, strand): {code: (valid_cov, percent_modified)}}, modkit bedMethyl, tab or space separated."""
    sites = {}
    for line in open(path):
        f = line.split()
        if len(f) < 11:
            continue
        sites.setdefault((f[0], int(f[1]), f[5]), {})[f[3]] = (int(f[9]), float(f[10]))
    return sites


def is_cpg(ref, contig, pos, strand):
    s = ref.get(contig, "")
    if strand == "+":
        return s[pos:pos + 2] == "CG"
    return pos >= 1 and s[pos - 1:pos + 1] == "CG"  # the G of a CpG on the plus strand is the minus-strand C


def truth(path):
    return {(f[0], int(f[1]), f[5]) for f in (l.split() for l in open(path)) if len(f) >= 6}


def stats(diffs):
    if not diffs:
        return {"sites": 0}
    a = sorted(abs(d) for d in diffs)
    return {"sites": len(a), "mean_abs_diff_pct": statistics.fmean(a), "median_abs_diff_pct": a[len(a) // 2],
            "p99_abs_diff_pct": a[min(len(a) - 1, int(0.99 * len(a)))], "max_abs_diff_pct": a[-1],
            "mean_signed_diff_pct": statistics.fmean(diffs),
            "sites_over_1pct": sum(x > 1 for x in a), "sites_over_5pct": sum(x > 5 for x in a)}


def score(sites, true_sites, code, min_cov):
    hit, other = [], []
    for key, codes in sites.items():
        if code in codes and codes[code][0] >= min_cov:
            (hit if key in true_sites else other).append(codes[code][1])
    mean = lambda xs: statistics.fmean(xs) if xs else None
    return {"true_sites": len(hit), "mean_pct_at_true_sites": mean(hit), "mean_pct_at_other_sites": mean(other)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--ref", required=True)
    ap.add_argument("--label-a", required=True)
    ap.add_argument("--label-b", required=True)
    ap.add_argument("--min-cov", type=int, default=20)
    ap.add_argument("--truth-5mC")
    ap.add_argument("--truth-5hmC")
    ap.add_argument("--json")
    args = ap.parse_args()
    ref, a, b = fasta(args.ref), pileup(args.a), pileup(args.b)
    out = {"a": args.label_a, "b": args.label_b, "min_cov": args.min_cov}
    for code, name in (("m", "5mC"), ("h", "5hmC")):
        for context in ("CpG", "all_C"):
            diffs = []
            for key in a.keys() & b.keys():
                if context == "CpG" and not is_cpg(ref, *key):
                    continue
                ca, cb = a[key].get(code), b[key].get(code)
                if ca and cb and ca[0] >= args.min_cov and cb[0] >= args.min_cov:
                    diffs.append(cb[1] - ca[1])
            out[f"{name}_{context}"] = stats(diffs)
    for code, name, path in (("m", "5mC", args.truth_5mC), ("h", "5hmC", args.truth_5hmC)):
        if path:
            t = truth(path)
            out[f"truth_{name}"] = {args.label_a: score(a, t, code, args.min_cov),
                                    args.label_b: score(b, t, code, args.min_cov)}
    text = json.dumps(out, indent=1)
    if args.json:
        open(args.json, "w").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
