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
import dataclasses
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from analysis.metrics import fresh_fraction_curve, read_series, tracer_bounds, tracer_metrics
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


def _run_solver(solver: str, case_dir: Path, n_procs: int, reconstruct: list[str],
                log_name: str | None = None, decompose: bool = True) -> None:
    """Run a solver, in parallel if n_procs > 1 (decompose=False continues an existing decomposition)."""
    if n_procs == 1:
        _foam([solver], case_dir, log_name)
        return
    if decompose:
        _foam(["decomposePar", "-force"], case_dir)
    # --bind-to none: let the OS spread processes over all cores, also when two cases run at once
    _foam(["mpirun", "--bind-to", "none", "-np", str(n_procs), solver, "-parallel"], case_dir, log_name or solver)
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
    flows = {w: read_series(post / f"{w}Flow", "surfaceFieldValue.dat")[-1, -1] for w in ("window1", "window2")}
    return {
        "n_cells": n_cells,
        "iterations": iterations,
        "converged": bool(converged),
        "final_residuals": {k: float(f"{v:.2e}") for k, v in residuals.items()},
        "room_mean_speed_ms": round(float(read_series(post / "roomAverage", "volFieldValue.dat")[-1, -1]), 4),
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


def _save_curve(path: Path, t: np.ndarray, fresh: np.ndarray, duration_s: float) -> None:
    """Store the fresh_fraction curve every second (the solvers write every time step)."""
    seconds = np.arange(0, duration_s + 1e-9, 1.0)
    curve = np.column_stack([seconds, np.interp(seconds, t, fresh)])
    np.savetxt(path, curve, delimiter=",", header="time_s,fresh_fraction", comments="", fmt=["%.0f", "%.6f"])


def tracer_summary(cfg: CaseConfig, case_dir: Path, tracer_dir: Path) -> dict:
    t, fresh = fresh_fraction_curve(tracer_dir)
    _save_curve(case_dir / "fresh_fraction.csv", t, fresh, cfg.flow.tracer_duration_s)
    c_min, c_max = tracer_bounds(tracer_dir)
    room_max = read_series(tracer_dir / "postProcessing" / "roomTracerMax", "volFieldValue.dat")
    metrics = tracer_metrics(t, fresh, cfg.flow.tracer_duration_s)
    return {
        **{k: round(v, 4) for k, v in metrics.items()},
        "room_max_tracer_end": round(float(room_max[-1, -1]), 4),
        "tracer_min": float(f"{c_min:.3g}"),
        "tracer_max": float(f"{c_max:.6g}"),
    }


# --- Stage 3 (comparison, PLAN.md §5 option B): time-varying flow with the tracer ----


def prepare_transient(cfg: CaseConfig, case_dir: Path) -> Path:
    """Transient case in case_dir/transient, starting from the steady solution."""
    transient_dir = case_dir / "transient"
    if transient_dir.exists():
        shutil.rmtree(transient_dir)
    write_case_files(cfg, transient_dir, "transient")
    shutil.copytree(case_dir / "constant", transient_dir / "constant")
    steady = case_dir / _latest_time(case_dir)
    for field in ("U", "p", "k", "omega", "nut", "phi"):
        shutil.copy(steady / field, transient_dir / "0" / field)
    _foam(["setFields"], transient_dir)  # C = 1 in the room
    return transient_dir


def _is_time(folder: Path) -> bool:
    return folder.is_dir() and re.fullmatch(r"[\d.e+-]+", folder.name) is not None


def resume_transient(transient_dir: Path) -> tuple[int, str]:
    """Prepare an interrupted parallel transient run to continue from its last complete save point.

    Returns the number of processors and the log name for the continued run.
    """
    processors = sorted(transient_dir.glob("processor*"))
    if not processors:
        raise RuntimeError(f"nothing to resume in {transient_dir} (no processor folders)")
    # A save point is complete only if it has U. Folders with only the tracer C came from
    # a write-setting bug (fixed) and are not needed; later folders are computed again.
    for processor in processors:
        for folder in filter(_is_time, processor.iterdir()):
            if not (folder / "U").exists():
                shutil.rmtree(folder)
    restart = max((f.name for f in processors[0].iterdir() if _is_time(f)), key=float)
    control = transient_dir / "system" / "controlDict"
    control.write_text(re.sub(r"^startFrom\s+\w+;", "startFrom       latestTime;", control.read_text(), flags=re.M))
    monitors = transient_dir / "system" / "monitors"
    text = monitors.read_text()
    if "writeControl    writeTime;" not in text.split("roomTracer")[0]:
        text = re.sub(r"(tracer\s*\{[^}]*?timeStart[^\n]*\n)", r"\1    writeControl    writeTime;\n", text, count=1)
        monitors.write_text(text)
    n_resumes = len(list(transient_dir.glob("log.pimpleFoam.resume*")))
    print(f"resuming {transient_dir} from t = {restart} s on {len(processors)} processors")
    return len(processors), f"pimpleFoam.resume{n_resumes + 1}"


def _transient_log_times(transient_dir: Path) -> tuple[list[float], float]:
    """Time steps over the first run and all resumes (steps computed twice counted once), and wall time."""
    logs = [transient_dir / "log.pimpleFoam", *sorted(transient_dir.glob("log.pimpleFoam.resume*"))]
    times: list[float] = []
    wall = 0.0
    for log in logs:
        text = log.read_text(errors="replace")
        steps = [float(t) for t in re.findall(r"^Time = ([\d.e+-]+)", text, re.M)]
        if steps:
            times = [t for t in times if t < steps[0]] + steps
        clocks = re.findall(r"ClockTime = ([\d.e+-]+) s", text)
        wall += float(clocks[-1]) if clocks else 0.0
    return times, wall


def transient_summary(cfg: CaseConfig, case_dir: Path, transient_dir: Path) -> dict:
    spinup = cfg.flow.transient_spinup_s
    t, fresh = fresh_fraction_curve(transient_dir, release_time=spinup)
    _save_curve(case_dir / "fresh_fraction_transient.csv", t, fresh, cfg.flow.tracer_duration_s)
    c_min, c_max = tracer_bounds(transient_dir)
    times, wall = _transient_log_times(transient_dir)
    n_steps, end_time = len(times), times[-1]  # the end time may be shortened during a run
    summary = {k: round(v, 4) for k, v in tracer_metrics(t, fresh, cfg.flow.tracer_duration_s).items()}
    for window in ("window1", "window2"):
        flow = read_series(transient_dir / "postProcessing" / f"{window}Flow", "surfaceFieldValue.dat")
        flow = flow[flow[:, 0] > spinup, -1] * 3600  # m^3/h, after the spin-up
        summary[f"{window}_net_inflow_mean_m3h"] = round(float(flow.mean()), 1)
        summary[f"{window}_net_inflow_std_m3h"] = round(float(flow.std()), 1)
    return {
        **summary,
        "tracer_min": float(f"{c_min:.3g}"),
        "tracer_max": float(f"{c_max:.6g}"),
        "tracer_simulated_s": round(end_time - spinup, 1),  # curve values after this repeat the last value
        "time_steps": n_steps,
        "mean_time_step_s": round(end_time / max(n_steps, 1), 4),
        "solver_wall_seconds": round(wall, 1),
    }


# --- Command line ----------------------------------------------------------------


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Simulate wind flow and air replacement for one case.")
    parser.add_argument("--config", required=True, type=Path, help="case YAML file, e.g. configs/default.yaml")
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument("--tracer-only", action="store_true", help="reuse the existing flow result, rerun the tracer")
    stage.add_argument("--transient", action="store_true",
                       help="comparison run with time-varying flow, starting from the existing flow result (slow)")
    parser.add_argument("--resume", action="store_true",
                        help="with --transient: continue an interrupted run from its last complete save point")
    parser.add_argument("--procs", type=int, help="CPU cores for this run (overrides flow.n_procs in the config)")
    args = parser.parse_args(argv)
    if "WM_PROJECT_DIR" not in os.environ:
        raise SystemExit("OpenFOAM is not loaded: run `of` (or source /opt/OpenFOAM/OpenFOAM-v2606/etc/bashrc) first")
    try:
        cfg = load_config(args.config)
        if args.procs:
            cfg = dataclasses.replace(cfg, flow=dataclasses.replace(cfg.flow, n_procs=args.procs))
        case_dir = CASES / cfg.case_id
        summary_file = case_dir / "summary.json"
        timings = {}
        if args.tracer_only or args.transient:
            if not summary_file.exists():
                raise RuntimeError(f"no flow result in {case_dir}: run without --tracer-only/--transient first")
            summary = json.loads(summary_file.read_text())
        if args.resume and not args.transient:
            raise RuntimeError("--resume only works together with --transient")
        if args.transient:
            transient_dir = case_dir / "transient"
            if args.resume:
                n_procs, log_name = resume_transient(transient_dir)
                _run_solver("pimpleFoam", transient_dir, n_procs, [], log_name=log_name, decompose=False)
            else:
                prepare_transient(cfg, case_dir)
                _run_solver("pimpleFoam", transient_dir, cfg.flow.n_procs, [])
            summary["transient"] = transient_summary(cfg, case_dir, transient_dir)
            summary_file.write_text(json.dumps(summary, indent=2))
            for key, value in summary["transient"].items():
                if not key.startswith("fresh_frac_") or key.endswith(("060s", "120s", "300s", "600s")):
                    print(f"{key:>30}: {value}")
            return
        if not args.tracer_only:
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
