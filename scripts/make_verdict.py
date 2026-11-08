#!/usr/bin/env python3
"""Builds <run_dir>/verdict.json (schema: verdict.schema.json) from run.json, dorado.log, gpu.csv and calls.bam.

Every field comes from this run's own files or the host it ran on. Anything that cannot be read is null, never a
guess. pysam is optional: without it the BAM fields are null and summarize.py fills them later on the laptop.
"""

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

# Lines that mean the process died or a GPU call failed, as opposed to Dorado's per-read [error] warnings.
FATAL = re.compile(
    r"CUDA error|cudaError|CUBLAS_STATUS|illegal memory access|out of memory|terminate called|Segmentation fault|"
    r"Aborted|core dumped|what\(\):|\[critical\]",
    re.IGNORECASE,
)
ERROR = re.compile(r"\[(error|critical)\]", re.IGNORECASE)


def sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def first(pattern, text, cast=str):
    m = re.search(pattern, text)
    return cast(m.group(1)) if m else None


def parse_log(text):
    batch_lines = [l.strip() for l in text.splitlines() if re.search(r"batch ?size|chunk ?size", l, re.I)
                   and "Trying batch size" not in l]
    # Without timings for this GPU and model Dorado says so and probes sizes ("Trying batch size N"); with them
    # (CUDA, 2.1.2) it only logs "Fastest capped+limited batch size", picked from the table without probing.
    if "No batch size timings" in text or "Trying batch size" in text:
        from_table = False
    elif "Fastest capped+limited batch size" in text:
        from_table = True
    else:
        from_table = None
    fatal = [l.strip() for l in text.splitlines() if FATAL.search(l)]
    errors = [l.strip() for l in text.splitlines() if ERROR.search(l)]
    # The final choice only: auto selection also logs every size it tries. CUDA logs "cuda:N using chunk size X,
    # batch size Y" per device (the first device's is taken; log_lines keeps all); Metal logs "set batch size to".
    cuda = re.search(r"using chunk size (\d+), batch size (\d+)", text)
    batch = (int(cuda.group(2)) if cuda else
             first(r"Final batch size\D*(\d+)", text, int) or first(r"set batch size to (\d+)", text, int))
    chunk = int(cuda.group(1)) if cuda else first(r"BasecallerNode chunk size (\d+)", text, int)
    return {
        "batchsize_used": batch,
        "chunksize_used": chunk,
        "from_table": from_table,
        "batch_lines": batch_lines[:40],
        "reads": first(r"Simplex reads basecalled:\s*(\d+)", text, int),
        "samples_per_s": first(r"Basecalled @ Samples/s:\s*([0-9.eE+-]+)", text, float),
        "padding_samples_per_s": first(r"Including Padding @ Samples/s:\s*([0-9.eE+-]+)", text, float),
        "finished_ms": first(r"Finished in \(ms\):\s*(\d+)", text, int),
        "fatal": fatal,
        "errors": (fatal + [e for e in errors if e not in fatal])[:10],
    }


def host_facts(device):
    facts = {"provider": os.environ.get("PROVIDER"), "pod_id": os.environ.get("POD_ID"),
             "image": os.environ.get("IMAGE"), "gpu_name": None, "gpu_count": None, "driver_version": None,
             "cuda_driver_version": None, "compute_cap": None, "vram_mib": None, "power_limit_w": None,
             "gpu_uuids": [], "cpu_model": None, "cpu_threads": os.cpu_count(), "host_ram_gib": None,
             "kernel": platform.release()}
    q = sh("nvidia-smi", "--query-gpu=index,name,driver_version,compute_cap,memory.total,uuid,power.limit",
           "--format=csv,noheader,nounits")
    if q:
        rows = [[c.strip() for c in r.split(",")] for r in q.splitlines()]
        if device.startswith("cuda:") and device != "cuda:all":
            wanted = set(device[5:].split(","))
            rows = [r for r in rows if r[0] in wanted] or rows
        facts.update(gpu_name=rows[0][1], gpu_count=len(rows), driver_version=rows[0][2], compute_cap=rows[0][3],
                     vram_mib=int(float(rows[0][4])), gpu_uuids=[r[5] for r in rows])
        try:
            facts["power_limit_w"] = float(rows[0][6])
        except ValueError:
            pass
        facts["cuda_driver_version"] = first(r"CUDA Version:\s*([\d.]+)", sh("nvidia-smi") or "")
    if platform.system() == "Darwin":
        facts["cpu_model"] = sh("sysctl", "-n", "machdep.cpu.brand_string")
        mem = sh("sysctl", "-n", "hw.memsize")
        facts["host_ram_gib"] = round(int(mem) / 2**30, 1) if mem else None
        if device == "metal":
            facts.update(gpu_name=facts["cpu_model"], gpu_count=1, provider=facts["provider"] or "local")
    else:
        cpuinfo = Path("/proc/cpuinfo").read_text(errors="replace") if Path("/proc/cpuinfo").exists() else ""
        facts["cpu_model"] = first(r"model name\s*:\s*(.+)", cpuinfo)
        meminfo = Path("/proc/meminfo").read_text() if Path("/proc/meminfo").exists() else ""
        kb = first(r"MemTotal:\s*(\d+)", meminfo, int)
        facts["host_ram_gib"] = round(kb / 2**20, 1) if kb else None
    return facts


def gpu_stats(path):
    if not path.exists():
        return None, None, None
    mem, util, power = [], [], []
    for row in path.read_text().splitlines():
        cols = [c.strip() for c in row.split(",")]
        if len(cols) < 5:
            continue
        for value, bucket in ((cols[3], mem), (cols[2], util), (cols[4], power)):
            try:
                bucket.append(float(value))
            except ValueError:
                pass
    mean = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    return (int(max(mem)) if mem else None), mean(util), mean(power)


def bam_stats(path):
    """Read count, bases, MM-tag count, mean qs, and a digest of every call, sorted by read id."""
    empty = {"reads_out": None, "bases_out": None, "reads_with_mm": None, "mean_qscore": None,
             "records_sha256": None}
    if not path.exists() or path.stat().st_size == 0:
        return empty
    try:
        import pysam
    except ImportError:
        return empty
    records, bases, with_mm, qs = [], 0, 0, []
    try:
        with pysam.AlignmentFile(str(path), "rb", check_sq=False) as bam:
            for r in bam:
                if r.is_secondary or r.is_supplementary:
                    continue
                seq = r.query_sequence or ""
                bases += len(seq)
                mm = r.get_tag("MM") if r.has_tag("MM") else (r.get_tag("Mm") if r.has_tag("Mm") else None)
                ml = list(r.get_tag("ML")) if r.has_tag("ML") else None
                with_mm += mm is not None
                if r.has_tag("qs"):
                    qs.append(float(r.get_tag("qs")))
                records.append((r.query_name, seq, mm, ml))
    except (ValueError, OSError):
        # A crash mid-run leaves a truncated BAM; its partial counts would look like a slow run.
        return empty
    digest = hashlib.sha256()
    for rec in sorted(records, key=lambda x: x[0]):
        digest.update(json.dumps(rec, separators=(",", ":")).encode())
        digest.update(b"\n")
    return {"reads_out": len(records), "bases_out": bases, "reads_with_mm": with_mm,
            "mean_qscore": round(sum(qs) / len(qs), 3) if qs else None, "records_sha256": digest.hexdigest()}


def main(run_dir):
    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text())
    log = (run_dir / "dorado.log").read_text(errors="replace") if (run_dir / "dorado.log").exists() else ""
    parsed = parse_log(log)
    wall = round(run["t1"] - run["t0"], 3)
    peak_vram, util, power = gpu_stats(run_dir / "gpu.csv")
    bam = bam_stats(run_dir / "calls.bam")

    manifest_path = os.environ.get("MANIFEST") or str(Path(run["data"]) / "manifest.json")
    manifest = json.loads(Path(manifest_path).read_text()) if Path(manifest_path).exists() else {}

    # GNU timeout exits 124 when it stopped the command at the run's time box.
    time_limited = run.get("time_limit_s") is not None and run["exit_code"] == 124
    usd_hr = float(os.environ["PRICE_USD_HR"]) if os.environ.get("PRICE_USD_HR") else None
    usd_run = round(usd_hr * wall / 3600, 5) if usd_hr is not None else None
    usd_per_gbase = (round(usd_run / (bam["bases_out"] / 1e9), 4)
                     if usd_run is not None and bam["bases_out"] else None)
    useful = (round(parsed["samples_per_s"] / parsed["padding_samples_per_s"], 5)
              if parsed["samples_per_s"] and parsed["padding_samples_per_s"] else None)
    reads_per_s = (round(parsed["reads"] / (parsed["finished_ms"] / 1000), 2)
                   if parsed["reads"] and parsed["finished_ms"] else None)

    verdict = {
        "schema_version": 1,
        "run_id": run["run_id"],
        "question": run["question"],
        "config_id": run["config_id"],
        "repeat": run["repeat"],
        "started_utc": run["started_utc"],
        "host": host_facts(run["device"]),
        "dorado": {
            "version": sh(run["dorado"], "--version") or "unknown",
            "build_sha256": os.environ.get("DORADO_BUILD_SHA256"),
            "simplex_model": Path(run["model"]).name,
            "mods_models": [Path(m).name for m in run["mods"]],
        },
        "args": {
            "command": (run_dir / "cmd.txt").read_text().split(),
            "device": run["device"],
            "batchsize_requested": run["batchsize"],
            "chunksize_requested": run["chunksize"],
            "overlap_requested": run["overlap"],
            "mods_batchsize_requested": run["mods_batchsize"],
            "env": run["env"],
        },
        "data": {
            "subset_id": run["subset"],
            "proxy": manifest.get("proxy", True),
            "source": manifest.get("source", "unknown"),
            "reads": manifest.get("reads"),
            "total_samples": manifest.get("total_samples"),
            "sample_rate_hz": manifest.get("sample_rate_hz"),
            "read_ids_sha256": manifest.get("read_ids_sha256"),
        },
        "result": {
            "exit_code": run["exit_code"],
            "time_limited": time_limited,
            "crashed": (run["exit_code"] != 0 and not time_limited) or bool(parsed["fatal"]),
            "error_lines": parsed["errors"],
            "wall_s": wall,
            "dorado_finished_ms": parsed["finished_ms"],
        },
        "batching": {
            "batchsize_used": parsed["batchsize_used"],
            "chunksize_used": parsed["chunksize_used"],
            "batchsize_from_benchmark_table": parsed["from_table"],
            "log_lines": parsed["batch_lines"],
        },
        "throughput": {
            "samples_per_s": parsed["samples_per_s"],
            "padding_samples_per_s": parsed["padding_samples_per_s"],
            "useful_fraction": useful,
            "reads_per_s": reads_per_s,
            "peak_vram_mib": peak_vram,
            "mean_gpu_util_pct": util,
            "mean_power_w": power,
        },
        "cost": {
            "usd_hr": usd_hr,
            "usd_hr_source": os.environ.get("PRICE_SOURCE"),
            "usd_run": usd_run,
            "usd_per_gbase": usd_per_gbase,
        },
        "output": {"bam": "calls.bam" if (run_dir / "calls.bam").exists() else None, **bam},
    }
    notes = []
    if not manifest:
        notes.append(f"no subset manifest at {manifest_path}; data fields unknown, proxy assumed")
    policy = os.environ.get("BAM_POLICY", "keep")
    if policy == "drop" and (run_dir / "calls.bam").exists():
        # Stats and the call digest are already in the verdict; the BAM itself is only needed for pileups.
        (run_dir / "calls.bam").unlink()
        verdict["output"]["bam"] = None
        notes.append("calls.bam deleted on the pod after its stats were recorded")
    elif policy == "none":
        verdict["output"]["bam"] = None
        notes.append("calls not written (soak run); read counts come from Dorado's log only")
    if notes:
        verdict["notes"] = "; ".join(notes)
    (run_dir / "verdict.json").write_text(json.dumps(verdict, indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
