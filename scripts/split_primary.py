#!/usr/bin/env python3
"""Keeps primary alignments only, sorts and indexes them, and optionally splits them per sample.

modkit counts a read once per site; when a read also has a supplementary alignment over the same site, which record
it takes depends on read order, and Dorado's output order is not stable. Two runs with identical calls and identical
alignments gave different pileups until supplementary and secondary records were dropped here.

usage: split_primary.py UNSORTED.bam OUT_PREFIX [SAMPLES.tsv.gz]
  writes OUT_PREFIX.bam (+ .bai) and, with SAMPLES, OUT_PREFIX.<sample>.bam per sample in the read-id table
"""

import gzip
import os
import sys

import pysam


def main(unsorted, prefix, samples=None):
    primary = f"{prefix}.primary.tmp.bam"
    by_name = f"{prefix}.byname.tmp.bam"
    pysam.view("-b", "-F", "0x904", "-o", primary, unsorted, catch_stdout=False)
    # modkit 0.6.4 is order-dependent among reads that start at the same position, even single-threaded: two BAMs
    # with identical records in a different order gave pileups 1-2 reads apart at 4,800x sites. A name sort first
    # makes the coordinate sort's tie order a function of the records alone.
    pysam.sort("-n", "-o", by_name, primary)
    pysam.sort("-o", f"{prefix}.bam", by_name)
    pysam.index(f"{prefix}.bam")
    os.remove(primary)
    os.remove(by_name)
    if not samples:
        return
    sample_of = dict(line.rstrip("\n").split("\t") for line in gzip.open(samples, "rt"))
    with pysam.AlignmentFile(f"{prefix}.bam") as bam:
        outs = {s: pysam.AlignmentFile(f"{prefix}.{s}.bam", "wb", template=bam)
                for s in sorted(set(sample_of.values()))}
        for r in bam:
            # A read Dorado split (an adapter mid-read) comes out under a new id, with its parent's id in `pi`.
            rid = r.get_tag("pi") if r.has_tag("pi") else r.query_name
            outs[sample_of[rid]].write(r)
    for s, out in outs.items():
        out.close()
        pysam.index(f"{prefix}.{s}.bam")


if __name__ == "__main__":
    main(*sys.argv[1:])
