"""Run one case: geometry and mesh, OpenFOAM case setup, and the steady wind flow.

Usage, from the repository root with the venv active and OpenFOAM loaded (`of`):
    python -m cfd.run_case --config configs/default.yaml

Everything goes into cases/<case_id>/, which is deleted and recreated on every
run. Each OpenFOAM tool writes its output to cases/<case_id>/log.<tool>, and the
key results are saved in cases/<case_id>/summary.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from cfd.case_setup import set_patch_types, write_case_files
from cfd.config import CaseConfig, ConfigError, load_config
from geometry.generate import generate

CASES = Path("cases")


def _run(cmd: list[str], case_dir: Path, log_name: str | None = None) -> str:
    """Run a command in the case folder and return its output; raise if it fails."""
    log = case_dir / f"log.{log_name or cmd[0]}"
    with log.open("w") as out:
        result = subprocess.run(cmd, cwd=case_dir, stdout=out, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise RuntimeError(f"`{' '.join(cmd)}` failed (exit code {result.returncode}), see {log}")
    return log.read_text(errors="replace")


def prepare(cfg: CaseConfig, case_dir: Path) -> None:
    """Mesh the geometry, convert the mesh for OpenFOAM and write all case files."""
    if case_dir.exists():
        shutil.rmtree(case_dir)
    generate(cfg, case_dir)  # writes case_dir/mesh.msh
    write_case_files(cfg, case_dir)
    _run(["gmshToFoam", "mesh.msh"], case_dir)
    set_patch_types(case_dir)
    _run(["topoSet"], case_dir)  # cellZone "room"
    _run(["renumberMesh", "-overwrite"], case_dir)  # faster linear solvers
    if "Failed" in _run(["checkMesh"], case_dir):
        raise RuntimeError(f"checkMesh found mesh problems, see {case_dir / 'log.checkMesh'}")


def solve(cfg: CaseConfig, case_dir: Path) -> None:
    """Steady wind flow with simpleFoam, in parallel if n_procs > 1."""
    n = cfg.flow.n_procs
    if n == 1:
        _run(["simpleFoam"], case_dir)
        return
    _run(["decomposePar", "-force"], case_dir)
    _run(["mpirun", "-np", str(n), "simpleFoam", "-parallel"], case_dir, "simpleFoam")
    _run(["reconstructPar", "-latestTime"], case_dir)
    for processor_dir in case_dir.glob("processor*"):
        shutil.rmtree(processor_dir)


def _last_value(path: Path) -> float:
    """Last number in the last data row of a postProcessing .dat file."""
    rows = [line.split() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    return float(rows[-1][-1])


def summarize(cfg: CaseConfig, case_dir: Path) -> dict:
    log = (case_dir / "log.simpleFoam").read_text(errors="replace")
    converged = re.search(r"SIMPLE solution converged in (\d+) iterations", log)
    iterations = int(converged.group(1)) if converged else int(re.findall(r"^Time = (\d+)", log, re.M)[-1])
    residuals = {}
    for field, value in re.findall(r"Solving for (\w+), Initial residual = ([\d.e+-]+)", log):
        residuals[field] = float(value)  # keeps the last (final) value per field
    n_cells = int(re.search(r"^\s+cells:\s+(\d+)", (case_dir / "log.checkMesh").read_text(), re.M).group(1))

    post = case_dir / "postProcessing"
    flows = {name: _last_value(post / f"{name}Flow" / "0" / "surfaceFieldValue.dat") for name in ("window1", "window2")}
    return {
        "case_id": cfg.case_id,
        "n_cells": n_cells,
        "iterations": iterations,
        "converged": bool(converged),
        "final_residuals": {k: float(f"{v:.2e}") for k, v in residuals.items()},
        "room_mean_speed_ms": round(_last_value(post / "roomAverage" / "0" / "volFieldValue.dat"), 4),
        "window_net_inflow_m3h": {k: round(v * 3600, 1) for k, v in flows.items()},
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Mesh and solve the steady wind flow for one case.")
    parser.add_argument("--config", required=True, type=Path, help="case YAML file, e.g. configs/default.yaml")
    args = parser.parse_args(argv)
    if "WM_PROJECT_DIR" not in os.environ:
        raise SystemExit("OpenFOAM is not loaded: run `of` (or source /opt/OpenFOAM/OpenFOAM-v2606/etc/bashrc) first")
    try:
        cfg = load_config(args.config)
        case_dir = CASES / cfg.case_id
        started = time.perf_counter()
        prepare(cfg, case_dir)
        meshed = time.perf_counter()
        solve(cfg, case_dir)
        solved = time.perf_counter()
    except ConfigError as error:
        raise SystemExit(f"Invalid configuration: {error}")
    except RuntimeError as error:
        raise SystemExit(f"Case failed: {error}")

    summary = summarize(cfg, case_dir)
    summary["mesh_seconds"] = round(meshed - started, 1)
    summary["solve_seconds"] = round(solved - meshed, 1)
    (case_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    for key, value in summary.items():
        print(f"{key:>22}: {value}")


if __name__ == "__main__":
    main()
