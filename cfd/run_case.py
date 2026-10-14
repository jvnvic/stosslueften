"""Run one case: geometry and mesh, steady wind flow, and air replacement (tracer).

Usage, from the repository root with the venv active and OpenFOAM loaded (`of`):
    python -m cfd.run_case --config configs/default.yaml
    python -m cfd.run_case --config configs/default.yaml --tracer-only   # reuse the flow result

Stages and folders:
1. Flow:   mesh + steady simpleFoam in cases/<case_id>/ (deleted and recreated)
2. Tracer: tracerFoam on the frozen flow in cases/<case_id>/tracer/

Each OpenFOAM tool writes its output to a log.<tool> file in the stage folder.
The results are saved in cases/<case_id>/summary.json and the curve in
cases/<case_id>/fresh_fraction.csv.
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

import numpy as np

from analysis.metrics import fresh_fraction_curve, read_dat, tracer_bounds, tracer_metrics
from cfd.case_setup import set_patch_types, write_case_files
from cfd.config import CaseConfig, ConfigError, load_config
from geometry.generate import generate

CASES = Path("cases")
TRACER_SOLVER = Path(__file__).parent / "solvers" / "tracerFoam"


def _run(cmd: list[str], cwd: Path, log: Path) -> str:
    """Run a command in `cwd`, write its output to `log` and return it; raise if it fails."""
    with log.open("w") as out:
        result = subprocess.run(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise RuntimeError(f"`{' '.join(cmd)}` failed (exit code {result.returncode}), see {log}")
    return log.read_text(errors="replace")


def _foam(cmd: list[str], case_dir: Path, log_name: str | None = None) -> str:
    """Run an OpenFOAM tool in a case folder, logging to log.<tool>."""
    return _run(cmd, case_dir, case_dir / f"log.{log_name or cmd[0]}")


def _run_solver(solver: str, case_dir: Path, n_procs: int, reconstruct: list[str]) -> None:
    """Run a solver, in parallel if n_procs > 1."""
    if n_procs == 1:
        _foam([solver], case_dir)
        return
    _foam(["decomposePar", "-force"], case_dir)
    _foam(["mpirun", "-np", str(n_procs), solver, "-parallel"], case_dir, solver)
    _foam(["reconstructPar", *reconstruct], case_dir)
    for processor_dir in case_dir.glob("processor*"):
        shutil.rmtree(processor_dir)


def _latest_time(case_dir: Path) -> str:
    times = [d.name for d in case_dir.iterdir() if d.is_dir() and re.fullmatch(r"[\d.e+-]+", d.name)]
    return max(times, key=float)


# --- Stage 1: steady wind flow -------------------------------------------------


def prepare_flow(cfg: CaseConfig, case_dir: Path) -> None:
    """Mesh the geometry, convert the mesh for OpenFOAM and write the flow case files."""
    if case_dir.exists():
        shutil.rmtree(case_dir)
    generate(cfg, case_dir)  # writes case_dir/mesh.msh
    write_case_files(cfg, case_dir, "flow")
    _foam(["gmshToFoam", "mesh.msh"], case_dir)
    set_patch_types(case_dir)
    _foam(["topoSet"], case_dir)  # cellZone "room"
    _foam(["renumberMesh", "-overwrite"], case_dir)  # faster linear solvers
    if "Failed" in _foam(["checkMesh"], case_dir):
        raise RuntimeError(f"checkMesh found mesh problems, see {case_dir / 'log.checkMesh'}")


def flow_summary(case_dir: Path) -> dict:
    log = (case_dir / "log.simpleFoam").read_text(errors="replace")
    converged = re.search(r"SIMPLE solution converged in (\d+) iterations", log)
    iterations = int(converged.group(1)) if converged else int(re.findall(r"^Time = (\d+)", log, re.M)[-1])
    residuals = {}
    for field, value in re.findall(r"Solving for (\w+), Initial residual = ([\d.e+-]+)", log):
        residuals[field] = float(value)  # keeps the last (final) value per field
    n_cells = int(re.search(r"^\s+cells:\s+(\d+)", (case_dir / "log.checkMesh").read_text(), re.M).group(1))
    post = case_dir / "postProcessing"
    flows = {w: read_dat(post / f"{w}Flow" / "0" / "surfaceFieldValue.dat")[-1, -1] for w in ("window1", "window2")}
    return {
        "n_cells": n_cells,
        "iterations": iterations,
        "converged": bool(converged),
        "final_residuals": {k: float(f"{v:.2e}") for k, v in residuals.items()},
        "room_mean_speed_ms": round(float(read_dat(post / "roomAverage" / "0" / "volFieldValue.dat")[-1, -1]), 4),
        "window_net_inflow_m3h": {k: round(float(v) * 3600, 1) for k, v in flows.items()},
    }


# --- Stage 2: tracer (air replacement) -----------------------------------------


def _ensure_tracer_solver(case_dir: Path) -> None:
    """Compile tracerFoam once (into $FOAM_USER_APPBIN) if it is not available yet."""
    if shutil.which("tracerFoam") is None:
        _run(["wmake"], TRACER_SOLVER, case_dir / "log.wmake")


def prepare_tracer(cfg: CaseConfig, case_dir: Path) -> Path:
    """Tracer case in case_dir/tracer: same mesh, frozen phi and nut from the steady result."""
    tracer_dir = case_dir / "tracer"
    if tracer_dir.exists():
        shutil.rmtree(tracer_dir)
    write_case_files(cfg, tracer_dir, "tracer")
    shutil.copytree(case_dir / "constant" / "polyMesh", tracer_dir / "constant" / "polyMesh")
    steady = case_dir / _latest_time(case_dir)
    for field in ("phi", "nut"):
        shutil.copy(steady / field, tracer_dir / "0" / field)
    _foam(["setFields"], tracer_dir)  # C = 1 in the room
    return tracer_dir


def tracer_summary(cfg: CaseConfig, case_dir: Path, tracer_dir: Path) -> dict:
    t, fresh = fresh_fraction_curve(tracer_dir)
    # Store the curve every second (the solver writes every time step).
    seconds = np.arange(0, cfg.flow.tracer_duration_s + 1e-9, 1.0)
    curve = np.column_stack([seconds, np.interp(seconds, t, fresh)])
    np.savetxt(case_dir / "fresh_fraction.csv", curve, delimiter=",", header="time_s,fresh_fraction",
               comments="", fmt=["%.0f", "%.6f"])
    c_min, c_max = tracer_bounds(tracer_dir)
    room_max = read_dat(tracer_dir / "postProcessing" / "roomTracerMax" / "0" / "volFieldValue.dat")
    metrics = tracer_metrics(t, fresh, cfg.flow.tracer_duration_s)
    return {
        **{k: round(v, 4) for k, v in metrics.items()},
        "room_max_tracer_end": round(float(room_max[-1, -1]), 4),
        "tracer_min": float(f"{c_min:.3g}"),
        "tracer_max": float(f"{c_max:.6g}"),
    }


# --- Command line ----------------------------------------------------------------


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Simulate wind flow and air replacement for one case.")
    parser.add_argument("--config", required=True, type=Path, help="case YAML file, e.g. configs/default.yaml")
    parser.add_argument("--tracer-only", action="store_true", help="reuse the existing flow result, rerun the tracer")
    args = parser.parse_args(argv)
    if "WM_PROJECT_DIR" not in os.environ:
        raise SystemExit("OpenFOAM is not loaded: run `of` (or source /opt/OpenFOAM/OpenFOAM-v2606/etc/bashrc) first")
    try:
        cfg = load_config(args.config)
        case_dir = CASES / cfg.case_id
        summary_file = case_dir / "summary.json"
        timings = {}
        if args.tracer_only:
            if not summary_file.exists():
                raise RuntimeError(f"no flow result in {case_dir}: run without --tracer-only first")
            summary = json.loads(summary_file.read_text())
        else:
            started = time.perf_counter()
            prepare_flow(cfg, case_dir)
            meshed = time.perf_counter()
            _run_solver("simpleFoam", case_dir, cfg.flow.n_procs, ["-latestTime"])
            timings = {"mesh_seconds": meshed - started, "flow_seconds": time.perf_counter() - meshed}
            summary = {"case_id": cfg.case_id, **flow_summary(case_dir)}

        started = time.perf_counter()
        _ensure_tracer_solver(case_dir)
        tracer_dir = prepare_tracer(cfg, case_dir)
        _run_solver("tracerFoam", tracer_dir, cfg.flow.n_procs, [])
        timings["tracer_seconds"] = time.perf_counter() - started
        summary.update(tracer_summary(cfg, case_dir, tracer_dir))
    except ConfigError as error:
        raise SystemExit(f"Invalid configuration: {error}")
    except RuntimeError as error:
        raise SystemExit(f"Case failed: {error}")

    summary.update({k: round(v, 1) for k, v in timings.items()})
    summary_file.write_text(json.dumps(summary, indent=2))
    for key, value in summary.items():
        if not key.startswith("fresh_frac_") or key.endswith(("060s", "120s", "300s", "600s")):
            print(f"{key:>22}: {value}")


if __name__ == "__main__":
    main()
