#!/usr/bin/env python3
"""Compares the calls in two Dorado BAMs from the same POD5 subset, read by read.

Reads are matched by read id (Dorado's output order is not stable). For every read in both:
  - sequence identical or not; for differing reads, base identity from an edit distance (edlib, if installed)
  - MM/ML tags identical or not
  - for reads with identical sequence, per-C-site modification probabilities: the largest absolute difference,
    and whether the site's call (canonical C, 5mC or 5hmC, whichever is most probable) flips. CpG sites (C then G
    in the read) are reported separately, since a methylation assay reads those.
It also reports each BAM's aggregate CpG 5mC and 5hmC rates, the kind of number a monitoring test tracks over time.

usage: concordance.py A.bam B.bam --label-a X --label-b Y [--json out.json]
"""

import argparse
import json
import sys

import pysam

try:
    import edlib
except ImportError:
    edlib = None

MODS = ("m", "h")


def load(path):
    reads = {}
    with pysam.AlignmentFile(path, "rb", check_sq=False) as bam:
        for r in bam:
            if r.is_secondary or r.is_supplementary:
                continue
            mm = r.get_tag("MM") if r.has_tag("MM") else None
            ml = tuple(r.get_tag("ML")) if r.has_tag("ML") else None
            probs = {}
            for (base, strand, code), sites in (r.modified_bases or {}).items():
                if base == "C" and code in MODS:
                    for pos, q in sites:
                        probs.setdefault(pos, {})[code] = (q + 0.5) / 256
            reads[r.query_name] = (r.query_sequence or "", mm, ml, probs)
    return reads


def site_call(p):
    """0 canonical, 1 5mC, 2 5hmC. A site Dorado left out of MM ('.' mode) is canonical with p(mod) = 0."""
    m, h = p.get("m", 0.0), p.get("h", 0.0)
    return max(((1 - m - h), 0), (m, 1), (h, 2))[1]


def aggregate(reads):
    sites = calls_m = calls_h = 0
    for seq, _, _, probs in reads.values():
        for i, base in enumerate(seq[:-1]):
            if base == "C" and seq[i + 1] == "G":
                sites += 1
                c = site_call(probs.get(i, {}))
                calls_m += c == 1
                calls_h += c == 2
    return {"cpg_sites": sites, "cpg_5mC_rate": calls_m / sites if sites else None,
            "cpg_5hmC_rate": calls_h / sites if sites else None}


def compare(a, b):
    common = sorted(set(a) & set(b))
    out = {"reads_a": len(a), "reads_b": len(b), "reads_common": len(common),
           "reads_only_a": len(set(a) - set(b)), "reads_only_b": len(set(b) - set(a))}
    same_seq = same_tags = 0
    identities = []
    c_sites = c_flips = cpg_sites = cpg_flips = 0
    max_dp = 0.0
    for rid in common:
        sa, mma, mla, pa = a[rid]
        sb, mmb, mlb, pb = b[rid]
        if sa != sb:
            if edlib:
                d = edlib.align(sa, sb)["editDistance"]
                identities.append(1 - d / max(len(sa), len(sb), 1))
            continue
        same_seq += 1
        same_tags += (mma, mla) == (mmb, mlb)
        for i, base in enumerate(sa):
            if base != "C":
                continue
            qa, qb = pa.get(i, {}), pb.get(i, {})
            for code in MODS:
                max_dp = max(max_dp, abs(qa.get(code, 0.0) - qb.get(code, 0.0)))
            flip = site_call(qa) != site_call(qb)
            c_sites += 1
            c_flips += flip
            if i + 1 < len(sa) and sa[i + 1] == "G":
                cpg_sites += 1
                cpg_flips += flip
    n = len(common) or 1
    identities.sort()
    out.update({
        "pct_identical_sequence": 100 * same_seq / n,
        "pct_identical_mm_ml_of_common": 100 * same_tags / n,
        "pct_identical_mm_ml_given_same_sequence": 100 * same_tags / same_seq if same_seq else None,
        "differing_reads_base_identity_median": identities[len(identities) // 2] if identities else None,
        "differing_reads_base_identity_min": identities[0] if identities else None,
        "c_sites_compared": c_sites,
        "pct_c_site_call_flips": 100 * c_flips / c_sites if c_sites else None,
        "cpg_sites_compared": cpg_sites,
        "pct_cpg_site_call_flips": 100 * cpg_flips / cpg_sites if cpg_sites else None,
        "max_abs_mod_prob_diff": max_dp,
    })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--label-a", required=True)
    ap.add_argument("--label-b", required=True)
    ap.add_argument("--json")
    args = ap.parse_args()
    a, b = load(args.a), load(args.b)
    result = {"a": args.label_a, "b": args.label_b, **compare(a, b),
              "aggregate_a": aggregate(a), "aggregate_b": aggregate(b),
              "edit_distance": "edlib" if edlib else "not installed; differing-read identity not computed"}
    text = json.dumps(result, indent=1)
    if args.json:
        open(args.json, "w").write(text + "\n")
    print(text)


if __name__ == "__main__":
    sys.exit(main())
