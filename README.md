# dorado-blackwell

Benchmarks and reproducibility checks for Nanopore basecalling with native methylation (5mC_5hmC) on NVIDIA
Blackwell GPUs (RTX 5090, RTX PRO 6000) vs H100, with a focus on short, cfDNA-length reads (~170 bp).

Results and the one-page summary are in [WRITEUP.md](WRITEUP.md). Short version: RTX 5090 and RTX PRO 6000 give
byte-identical calls on every config, an H100 shifts per-CpG levels by well under a point on average, SUP on 155 bp
reads needs Dorado 2.1's variable chunk sizes, and the dorado#1507 crash did not reproduce in a 3 h run on 2x 5090.
All data are proxies, not cfDNA.

## Questions

1. Crash: does sup + 5mC_5hmC crash on Blackwell (dorado#1507)? Minimal repro and workaround.
2. Throughput: samples/s by GPU and model (hac v5.2, sup v5.2, hac v6.0), with and without mods (dorado#1640).
3. Short reads: ~170 bp reads vs normal-length reads at matched total signal.
4. Concordance: do basecalls and methylation calls change across GPUs, repeat runs, or batch sizes (dorado#1625)?

## Data (all proxies: no public R10.4.1 5 kHz cfDNA raw signal was found)

| Subset | Source | Reads | Samples | Why |
|---|---|---:|---:|---|
| `short-155bp` | ONT open data `modbase-validation_2024.10/subset/` 5mC_rep1, 5hmC_rep1, control_rep1 | 473,185 | 1,046,600,811 | 155 bp synthetic constructs, cfDNA length, with 5mC/5hmC ground truth |
| `long-hg002` | ONT open data `giab_2025.01` HG002 PAW70337, file `_5` | 3,574 | 1,046,754,761 | genomic DNA, normal read lengths, matched total samples |
| `tiny-*` | first 2,000 short reads and matched long reads | | | laptop dry runs |
| soak | HG002 PAW70337 files `_131` to `_136` (`subsets/soak.txt`), unsubsetted | 605,807 | 1.47e11 | dorado#1507 crash soaks |

Both sources are R10.4.1, 5 kHz, SQK-LSK114. Checked and rejected: GEO GSE317007 (cfDNA, BAM/FASTQ only, no raw
signal), Zenodo 6642503 (R9.4.1, processed only), ONT's CliveOME cfDNA (raw, but 4 kHz). `subsets/<id>/` holds
each subset's read ids, per-read sample of origin, sources with sha256, and manifest; pods rebuild every subset from
the S3 sources and refuse to run unless reads, samples and the read-id digest match.

## Pins (`scripts/pins.env`)

- Dorado 2.1.2 (latest), Linux build sha256 `f4ed83ac...` (hashed here; ONT publishes none). Bundles CUDA 12.8;
  `bin/dorado` carries native sm_120 code (`logs/stage0/fatbin-archs-dorado-2.1.2-linux-x64.txt`).
- Dorado 1.4.0 for the dorado#1507 soaks only.
- Models: hac@v5.2.0, sup@v5.2.0, hac@v6.0.0 (2.1.2 has no DNA sup@v6.0.0), with 5mC_5hmC@v2 (v5.2) and @v1 (v6);
  sup@v5.2.0 4mC_5mC@v1 and 6mA@v1 for the 5 h soak only.
- Base image `nvidia/cuda:12.8.1-base-ubuntu24.04` by digest; modkit 0.6.4; pod5 0.3.49; pysam 0.24.1.

## Layout

| Path | Holds |
|---|---|
| `runs/<run_id>/` | One folder per GPU run: command, Dorado log, 1 s nvidia-smi samples, `verdict.json`; pileups for Q4 runs. BAMs are not committed. |
| `results/` | Tables built from the verdicts, and the per-CpG concordance JSONs |
| `logs/<pod>/` | Each pod's environment report, setup and plan logs |
| `subsets/`, `references/` | Subset definitions and manifests; the synthetic constructs' reference and known-site BEDs |
| `scripts/plans/` | Run plans, one row per run |

## Scripts

| Script | Does |
|---|---|
| `run_dorado.sh` | One run: Dorado with `-v`, 1 s nvidia-smi samples, then `make_verdict.py` |
| `make_verdict.py` | `verdict.json` per run (`verdict.schema.json`): host, versions, batching, throughput, padding, cost, call digest |
| `matrix.sh` + `plans/*.tsv` | Runs a plan row by row; skips rows that already have a verdict |
| `pod_setup.sh` | Installs and verifies everything on a pod, rebuilds and checks the subsets, fetches soak data |
| `build_subsets.py`, `pod5_manifest.py` | Pick the matched subsets; describe and verify a subset |
| `concordance.py` | Two runs, read by read: identical sequence, identical MM/ML, per-C-site call flips |
| `pileup.sh`, `split_primary.py`, `compare_pileups.py` | Per-site 5mC/5hmC pileups (primary alignments, no filtering) and their differences; ground-truth scoring |
| `summarize.py`, `tables.py`, `q4_table.py` | `runs/*/verdict.json` -> `results/summary.csv`, `throughput.csv`, `determinism.csv`, `q4_pileups.csv` |
| `outlier_plan.py` | Third repeats for configs whose two repeats disagree on speed |
| `fatbin_arch.py` | Lists the GPU architectures compiled into the Dorado binary |
| `sync_harness.sh`, `start_plan.sh`, `push_kit_file.sh`, `pull_loop.sh`, `collect.sh` | Drive the GPU rental harness ([sm120-kit](https://github.com/adi-suresh01/sm120-kit)): copy the kit, start a plan, pull results |

## Status

All GPU runs done (2026-11-06/08): 117 runs on RTX 5090, RTX PRO 6000 Server, H100 PCIe and 2x RTX 5090, no
crashes, $36.26 of GPU rental. Not tested: a soak longer than 5 h, a soak with the mismatched per-GPU batch sizes
seen in the dorado#1507 crash logs, data-center Blackwell (sm_100), and real cfDNA.
