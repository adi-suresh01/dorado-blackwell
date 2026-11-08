# Dorado 2.1.2 with 5mC_5hmC on Blackwell vs H100, for cfDNA-length reads

Measured 2026-11-06/08 on rented pods (RunPod; Vast for the 3 h soak): RTX 5090 (32 GB), RTX PRO 6000 Blackwell
Server Edition (96 GB), H100 PCIe (80 GB, 310 W cap), and 2x RTX 5090. Dorado 2.1.2 (Linux build sha256
`f4ed83ac...`; 1.4.0 for one soak), driver 595.91.07 on every RunPod pod (595.99.02 on the Vast box), models
hac@v5.2.0, sup@v5.2.0, hac@v6.0.0 with their 5mC_5hmC models. Data are proxies (no public R10.4.1 5 kHz cfDNA
raw signal exists): 155 bp synthetic constructs with known 5mC/5hmC sites (ONT modbase-validation_2024.10, 473,185
reads) and HG002 genomic reads with the same total signal (1.05e9 samples each). Every config ran at least twice
except the three soaks and two batch-size checks (`-b 512`, and `-b 1024` on 155 bp reads), which ran once; 116
runs, no crashes, $22.28 of GPU rental. Raw verdicts: `runs/`, tables: `results/`.

## Results (proxy data; basecalled samples/s, median of 2 runs; $/Gbase at the rental rate shown)

| GPU (RunPod $/h) | SUP v5.2 + mods, 155 bp | $/Gbase | HAC v5.2 + mods, 155 bp | HAC v6 + mods, long | Calls vs RTX 5090 |
|---|---:|---:|---:|---:|---|
| RTX 5090 ($1.19) | 1.65e7 | 0.37 | 6.86e7 | 3.38e7 (6.68e7 at `-b 2048`) | reference |
| RTX PRO 6000 Server ($2.49) | 1.92e7 | 0.66 | 5.79e7 | 8.22e7 | byte-identical |
| H100 PCIe ($2.89) | 1.47e7 | 1.00 | 2.44e7 | 6.16e7 | per-CpG shift 0.04-0.26 pts (mean) |
| 2x RTX 5090 ($2.38) | 3.50e7 | 0.35 | - | - | byte-identical |

## Findings

1. **Swapping an RTX 5090 for an RTX PRO 6000 does not change calls; swapping in an H100 does, slightly.** The
   5090 and PRO 6000 (both sm_120; data-center Blackwell, sm_100, was not tested) gave byte-identical calls
   (sequence, MM and ML tags) on every config, as did repeat runs, every batch size tried (256 to 4864) and 1 vs 2
   GPUs. H100 PCIe vs either card: 36-57% of reads have identical sequence and 0.24-0.38% of CpG sites flip call,
   but per-CpG levels at 500x+ (212-273 sites) move by a mean of 0.04-0.18 points for 5mC (max 1.9) and 0.07-0.26
   for 5hmC (max 2.8), and SUP scores the same at the known 5mC sites (93.66% vs 93.67%). At 20x+ (305-559 sites),
   closer to cfDNA depth, the shift is a mean of 0.10-0.28 points for 5mC (max 5.8) and 0.16-0.45 for 5hmC (max
   7.4), while a 20-read site already has a sampling SD of up to 11 points (binomial, at 50%). All sites are on the
   synthetic constructs. One Dorado chunking flag on one GPU moves the same sites as much or more (5hmC max 3.5-4.6
   points at 500x+).
2. **On 155 bp reads, SUP needs Dorado 2.1's variable chunk sizes.** With `--disable-variable-chunk-sizes`, SUP +
   5mC_5hmC on short reads drops 2.2-2.5x on every GPU (5090: 1.65e7 to 6.5e6 samples/s) and the calls change. With
   them on, short reads run at 85-93% of the long-read speed for SUP + mods. Mods cost more on short reads: HAC v5.2
   + 5mC_5hmC runs at 38-44% of its no-mods speed on 155 bp reads vs 64-69% on long reads (all three GPUs).
3. **Per dollar the RTX 5090 wins; per GPU the RTX PRO 6000.** Against H100 PCIe on long reads without mods, the
   PRO 6000 is 1.22x on SUP v5.2 but 1.50-1.52x on HAC v5.2 and HAC v6, so SUP gains least from Blackwell
   (dorado#1640's pattern), but HAC v6 does gain on 2.1.2. Two 5090s ran SUP + mods 2.1x faster than one; they were
   a different machine with the same CPU model, so read that as about 2x.
4. **HAC v6 + 5mC_5hmC on a 32 GB RTX 5090 needs `-b 2048` for long reads.** At Dorado's pick (2624) the
   basecaller holds 28.2 of the 28.7 GB Dorado allows itself, the mods model is starved, and the GPU runs at 41% of
   the PRO 6000's speed. `-b 2048` doubles it to 6.7e7 samples/s (81% of the PRO 6000) with byte-identical calls
   (1536: 5.5e7, 1024: 4.1e7). On 155 bp reads the default is already the fastest (6.75e7 vs 4.0e7 at 1024, n=1).
5. **The dorado#1507 crash (sup@v5.2 + mods on 2x RTX 5090) did not reproduce, including a 3 h run of 2.1.2.**
   Same model pair, `--device cuda:all`, HG002 reads. First machine, 1.47e11 samples (605,807 reads): 2.1.2 ran
   65 min at 3.78e7 samples/s and 1.4.0, the reporter's version, 72 min at 3.41e7, both ending when the six POD5
   files ran out (exit 0). Then 2.1.2 ran the full 3 h box (stopped by us) on a second 2x 5090 machine, over the
   same files listed 4 times: both GPUs 100% busy at batch 352, memory flat from the first to the last 45 min (GPU0
   28,947 to 29,014 MiB of 32,607), no error lines (n=1; samples/s not logged, since the box stops Dorado before
   its summary). The reporter's crashes came after 1.5-10 h, so 3 h does not rule it out. In all three of their
   crash logs (1.1.1 and 1.4.0) the two 5090s took different batch sizes from Dorado's start-up benchmark, and in
   the one with memory lines a GPU sat at 29.5 of its 30.5 GB budget (batch 736). Ours took 224 on both under
   1.4.0 (17.9 GB); 2.1.2 skips the benchmark and uses 352 from its built-in table on both (28.2 GB, also clean).

## What to run

- GPU: an RTX 5090 is the cheapest per gigabase at these rates (SUP + mods: 1.8x less than the PRO 6000, 2.5-2.7x
  less than the H100 PCIe; these runs kept every GPU 92-99% busy, so the ratios reflect the GPUs, not the hosts).
  An RTX PRO 6000 is the fastest single card for SUP and the only one here with room for every model at its
  default batch size. Both give the same calls, so a fleet can mix them.
- Model: sup@v5.2.0 + 5mC_5hmC@v2 on Dorado 2.1 or later with default chunking. On a 32 GB card running
  hac@v6.0.0 + 5mC_5hmC@v1 on long reads, add `-b 2048`.
- Reproducibility: pin the Dorado build, models and every flag per assay version; never change chunk options
  mid-study; log the GPU architecture with each sample; keep runs from different architectures (here H100 vs
  RTX 5090 / PRO 6000) apart in a longitudinal comparison, or re-call them on one architecture.
- Crash (dorado#1507): no verified fix, since it did not reproduce here; 2.1.2 ran 3 h clean on 2x 5090 with both
  GPUs at the same batch size. Mitigations from the batch-size pattern in finding 5, untested against the crash:
  on a 2x 5090 box, run 2.1.2 (one batch size from its table for both GPUs) or pass a fixed `-b` so both GPUs
  match. Restart a crashed run with `--resume-from <partial.bam>`, which skips reads already written.

## Repro

```
git clone https://github.com/adi-suresh01/dorado-blackwell && cd dorado-blackwell
source scripts/pins.env                                   # versions, URLs, sha256s
bash scripts/pod_setup.sh .                               # on a Linux GPU box: Dorado, models, subsets (verified)
bash scripts/matrix.sh scripts/plans/single-gpu.tsv --out runs --work /workspace/dorado --device cuda:0
python scripts/tables.py                                  # results/throughput.csv, results/determinism.csv
scripts/pileup.sh runs/<run> references/all_5mers.fa subsets/short-155bp/samples.tsv.gz <dorado> <python> <modkit>
python scripts/q4_table.py                                # results/q4_pileups.csv
```

## Caveats

- Proxies, not cfDNA: synthetic 155 bp constructs and HG002 genomic DNA. Fragment-length mix, adapters and
  methylation patterns of real plasma cfDNA will differ.
- One host per GPU, with different CPUs: Ryzen 9 9950X (5090, and the 2x 5090 on a separate machine), EPYC 9355
  (PRO 6000), Xeon 8352Y 2.2 GHz (H100); the 3 h soak ran on a third 5090 machine (EPYC 7402P, 500 W cap). HAC
  short-read + mods runs are partly CPU-bound (GPU use 70%, 55%, 35%), so the H100 PCIe HAC short-read numbers
  mostly measure its host; SUP runs kept every GPU 92-99% busy. H100 PCIe is not H100 SXM, the part Dorado is
  tuned for.
- Each run is 1.05e9 samples (10-70 s) apart from the soaks; costs use RunPod's rate at rental and Dorado's own
  basecalling time.
- On the 5090, the first run of three HAC configs on 155 bp reads (`q3-hac52-short`, `q3-hac60-short`,
  `q3-hac52-mods-short-c3000`) was 1.8-4x slower than the others with identical calls, so pod timing noise (likely
  a cold page cache or a results pull on the same CPU; not confirmed). A third run matched the second within 5%,
  and those configs report the median of 3.
- Per-CpG comparisons need a fixed read order: modkit 0.6.4 pileups of identical calls differed until reads were
  sorted by name before position (`scripts/split_primary.py`).
