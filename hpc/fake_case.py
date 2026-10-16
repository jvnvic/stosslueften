"""Stand-in for `cfd.run_case` for tests and dry runs of the runner (`python -m hpc.runner --fake`).

Same command line and the same result files (summary.json, logs, curves), but seconds instead of
hours and no OpenFOAM. Behaviour per case, set with environment variables:
    HPC_FAKE_SECONDS   run time of each stage (default 1)
    HPC_FAKE_FAIL      comma-separated case ids that fail
    HPC_FAKE_HANG      comma-separated case ids that never finish
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import zlib
from pathlib import Path

import yaml


def _ids(name: str) -> set[str]:
    return {v.strip() for v in os.environ.get(name, "").split(",") if v.strip()}


def _stage(folder: Path, log_name: str, seconds: float, steps: int = 20) -> None:
    """A log with 'Time = …' lines and a controlDict with endTime, like an OpenFOAM run."""
    (folder / "system").mkdir(parents=True, exist_ok=True)
    (folder / "system" / "controlDict").write_text(f"endTime         {steps};\n")
    with (folder / log_name).open("w") as log:
        for step in range(1, steps + 1):
            time.sleep(seconds / steps)
            log.write(f"Time = {step}\n\nsmoothSolver:  Solving for p, Initial residual = {10 ** (-step / 5):.3e}, "
                      f"Final residual = 1e-6, No Iterations 2\nExecutionTime = {step} s  ClockTime = {step} s\n\n")
            log.flush()


def _metrics(case_id: str, scale: float) -> dict:
    tau = (30 + zlib.crc32(case_id.encode()) % 300) * scale
    curve = {f"fresh_frac_{t:03d}s": round(1 - math.exp(-t / tau), 4) for t in range(30, 601, 30)}
    t90 = tau * math.log(10)
    return {**curve, "t90_s": round(t90, 2) if t90 <= 600 else float("nan"), "tau_s": round(tau, 2),
            "airflow_m3h": round(50 / tau * 3600 / 0.55, 1)}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--procs", type=int)
    parser.add_argument("--transient", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--steady-only", action="store_true")
    args = parser.parse_args(argv)
    cfg = yaml.safe_load(args.config.read_text())
    case_id, same_wall = cfg["case_id"], cfg["layout"] == "same_wall"
    seconds = float(os.environ.get("HPC_FAKE_SECONDS", "1"))
    case_dir = Path("cases") / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    print(f"fake case {case_id} ({cfg['layout']})", flush=True)
    if case_id in _ids("HPC_FAKE_HANG"):
        time.sleep(1e6)
    summary_file = case_dir / "summary.json"
    fail = case_id in _ids("HPC_FAKE_FAIL")
    if not args.transient:
        _stage(case_dir, "log.simpleFoam", seconds)
        if fail and not same_wall:  # like run_case: the summary is written only when the stage worked
            print("Case failed: fake failure", flush=True)
            sys.exit(1)
        summary = {"case_id": case_id, "n_cells": 103000, "method": "B" if same_wall else "A",
                   **_metrics(case_id, 1.0)}
        summary_file.write_text(json.dumps(summary, indent=2))
    if fail:  # a same-wall case fails in method B: its method A result stays
        print("Case failed: fake failure", flush=True)
        sys.exit(1)
    if same_wall and not args.steady_only:
        transient = case_dir / "transient"
        _stage(transient, "log.pimpleFoam", seconds)
        (transient / "processor0" / "30").mkdir(parents=True, exist_ok=True)
        (transient / "processor0" / "30" / "U").write_text("save point\n")
        summary = json.loads(summary_file.read_text())
        summary["transient"] = _metrics(case_id, 0.8)
        summary_file.write_text(json.dumps(summary, indent=2))
    print("done", flush=True)


if __name__ == "__main__":
    main()
