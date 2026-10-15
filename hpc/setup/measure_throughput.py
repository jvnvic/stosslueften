"""How many cases per hour the simulation PC finishes with 2, 3 or 4 cases at the same time (HPC_PLAN.md §8).

Usage, from the repository root with OpenFOAM loaded; takes about 30 min, so start it detached:
    setsid nohup .venv/bin/python -m hpc.setup.measure_throughput > cases/throughput.out 2>&1 &

Each slot runs one copy of configs/demo/demo_1.yaml (method A) through cfd.queue with 4 cores.
The copies are deleted afterwards (use --keep to keep them).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEMO = Path("configs/demo/demo_1.yaml")
WORK = Path("cases/throughput")
CASES = Path("cases")


def make_configs(slots: int) -> list[Path]:
    """One copy of the demo case per slot, each with its own case_id."""
    WORK.mkdir(parents=True, exist_ok=True)
    text = DEMO.read_text()
    paths = []
    for i in range(slots):
        path = WORK / f"throughput_{slots}_{i}.yaml"
        path.write_text(re.sub(r"^case_id: \S+", f"case_id: throughput_{slots}_{i}", text, count=1, flags=re.M))
        paths.append(path)
    return paths


def run_batch(slots: int, procs: int) -> float:
    """Run `slots` cases at the same time (one queue each); returns the wall time in seconds."""
    configs = make_configs(slots)
    started = time.time()
    queues = [subprocess.Popen([sys.executable, "-m", "cfd.queue", "--procs", str(procs), str(c)]) for c in configs]
    for queue in queues:
        queue.wait()
    seconds = time.time() - started
    missing = [c.stem for c in configs if not (CASES / c.stem / "summary.json").exists()]
    if missing:
        raise SystemExit(f"cases failed: {', '.join(missing)} (see cases/<case>.queue.log)")
    return seconds


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Measure cases per hour for several numbers of slots.")
    parser.add_argument("--slots", type=int, nargs="+", default=[2, 3, 4], help="numbers of cases at the same time")
    parser.add_argument("--procs", type=int, default=4, help="cores per case (procs_per_case)")
    parser.add_argument("--keep", action="store_true", help="keep the case folders")
    args = parser.parse_args(argv)

    rows = []
    for slots in args.slots:
        print(f"=== {slots} cases at the same time, {args.procs} cores each   {time.strftime('%H:%M:%S')}", flush=True)
        seconds = run_batch(slots, args.procs)
        rows.append({"slots": slots, "seconds": round(seconds), "cases_per_hour": round(slots / seconds * 3600, 1)})
        print(f"    {seconds:.0f} s for {slots} cases", flush=True)
    best = max(rows, key=lambda r: r["cases_per_hour"])
    # prefer fewer slots unless more slots are clearly (> 5 %) faster: fewer slots leave more room
    choice = next(r for r in rows if r["cases_per_hour"] >= 0.95 * best["cases_per_hour"])

    print(f"\n{'slots':>6}{'time':>10}{'cases/h':>10}")
    for r in rows:
        print(f"{r['slots']:>6}{r['seconds']:>9}s{r['cases_per_hour']:>10}")
    print(f"\nRecommendation: slots: {choice['slots']} with procs_per_case: {args.procs} (method A cases).")
    (CASES / "throughput.json").write_text(json.dumps({"procs": args.procs, "rows": rows, "choice": choice}, indent=2))
    if not args.keep:
        shutil.rmtree(WORK, ignore_errors=True)
        for case_dir in CASES.glob("throughput_*_*"):
            shutil.rmtree(case_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
