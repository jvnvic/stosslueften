"""Collect the finished cases of sweep runs into the dataset (DATASET_PLAN.md §3, PLAN.md §3).

Usage, from the repository root (any OS; OpenFOAM is not needed):
    python -m sweeps.dataset --hpc --runs train-v1 train-a-v1 train-a-turn-v1
    python -m sweeps.dataset --runs train-v1 --cases cases     # cases run on this machine with cfd.queue

--hpc fetches two branches from origin and reads them without checking anything out:
hpc-results (the result files of every case) and hpc-status (machine, code commit and finish
time of every case). With --cases, the case folders are read from that folder instead
(<cases>/<run_id>/<case_id>/ or <cases>/<case_id>/), and those four columns stay empty.

Writes, from scratch every time (results/README.md, the data dictionary, is kept):
    results/summary.csv               one row per case, the frozen columns of PLAN.md §3
    results/timeseries/<case_id>.csv  time_s, fresh_fraction every 1 s from 0 to 600 s (ok rows)
    results/dataset_info.json         runs, code commits, counts and the problems found

Every case is checked. A result that is known to be wrong (a frozen tracer, a curve outside 0...1)
makes its row `failed`, with the reason in `error_message`. Smaller problems are only printed;
with --strict any problem stops the writer before anything is written.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import shutil
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

CURVE_COLUMNS = [f"fresh_frac_{t:03d}s" for t in range(30, 601, 30)]
INPUT_COLUMNS = ["layout", "window1_x_m", "window1_mode", "window1_angle_deg", "window1_hinge",
                 "window2_x_m", "window2_mode", "window2_angle_deg", "window2_hinge", "wind_speed_ms"]
COLUMNS = ["case_id", "run_id", "split", *INPUT_COLUMNS, "status", "error_message", "method", *CURVE_COLUMNS,
           "t90_s", "tau_s", "airflow_m3h", "steady_t90_s", "steady_tau_s",
           "n_cells", "runtime_s", "machine", "openfoam_version", "git_commit", "finished_utc"]

DURATION_S = 600
MEDIUM_MESH_CELLS = 103_000  # PLAN.md §6
MAX_FROZEN_S = 10   # seconds without any change of fresh_fraction (below 0.99) before a curve counts as frozen
MAX_DIP = 0.005     # fresh_fraction may fall by this much (numerical noise), not more
BOUNDS_TOL = 0.02   # tracer overshoot allowed beyond 0...1
MAX_IMBALANCE = 0.02  # |inflow - outflow| relative to the inflow


@dataclass
class Case:
    """What the writer knows about one case."""

    case_id: str
    run_id: str
    split: str
    drawn: Path                        # the case file of the run (configs/sweep/<run>/<case_id>.yaml)
    folder: Path | None = None         # its result folder, None if it has not run
    runner: dict = field(default_factory=dict)   # machine, commit, finish time (HPC runner only)
    problems: list[str] = field(default_factory=list)


# --- reading -------------------------------------------------------------------------------

def git(*args: str, binary: bool = False):
    out = subprocess.run(["git", *args], capture_output=True, check=True).stdout
    return out if binary else out.decode()


def fetch_hpc(dest: Path) -> tuple[Path, dict]:
    """Fetch the runner's two branches; returns the extracted results folder and status.json."""
    git("fetch", "--quiet", "origin", "hpc-results", "hpc-status")
    archive = git("archive", "origin/hpc-results", "results", binary=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data")
    return dest / "results", json.loads(git("show", "origin/hpc-status:status.json"))


def full_commit(short: str | None) -> str:
    if not short:
        return ""
    try:
        return git("rev-parse", "--verify", "--quiet", f"{short}^{{commit}}").strip() or short
    except subprocess.CalledProcessError:
        return short


def runner_info(status: dict) -> dict[str, dict]:
    """Per case id: machine, OpenFOAM version, code commit, finish time and error, from status.json."""
    runner = status.get("runner", {})
    commits = {run["run_id"]: full_commit(run.get("code")) for run in status.get("runs", [])}
    info = {}
    for entry in status.get("results", []) + status.get("failures", []):
        finished = entry.get("finished")
        info[entry["case_id"]] = {
            "machine": runner.get("host") or "",
            "openfoam_version": runner.get("openfoam") or "",
            "git_commit": commits.get(entry.get("run_id"), ""),
            "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(finished)) if finished else "",
            "error": entry.get("error") or "",
        }
    return info


def find_cases(runs: list[str], configs: Path, cases: Path, runner: dict[str, dict]) -> list[Case]:
    found = []
    for run_id in runs:
        folder = configs / run_id
        manifest = folder / "manifest.json"
        if not manifest.exists():
            raise SystemExit(f"no run {run_id}: {manifest} is missing (draw it with python -m sweeps.generate)")
        split = json.loads(manifest.read_text())["split"]
        for drawn in sorted(folder.glob(f"{run_id}_*.yaml")):
            case = Case(drawn.stem, run_id, split, drawn, runner=runner.get(drawn.stem, {}))
            for candidate in (cases / run_id / case.case_id, cases / case.case_id):
                if candidate.is_dir():
                    case.folder = candidate
                    break
            found.append(case)
    return found


def read_curve(path: Path) -> np.ndarray:
    """time_s, fresh_fraction rows of a curve file written by cfd.run_case."""
    return np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)


# --- checks ------------------------------------------------------------------------------------

def curve_problem(curve: np.ndarray) -> str | None:
    """Why a fresh_fraction curve cannot be used, or None if it is fine."""
    time_s, fresh = curve[:, 0], curve[:, 1]
    if len(time_s) != DURATION_S + 1 or not np.allclose(time_s, np.arange(DURATION_S + 1)):
        return f"curve does not have one value per second from 0 to {DURATION_S} s"
    if fresh.min() < -BOUNDS_TOL or fresh.max() > 1 + BOUNDS_TOL:
        return f"curve leaves 0...1 ({fresh.min():.3f} to {fresh.max():.3f})"
    if np.diff(fresh).min() < -MAX_DIP:
        return f"curve falls by {-np.diff(fresh).min():.3f} at some point"
    # The tracer solver stops iterating when its first residual is below its tolerance. In very weak
    # flows that happens every time step, and the tracer stays as it was: steps without any change.
    frozen = int(np.sum((np.diff(fresh) == 0) & (fresh[1:] < 0.99)))
    if frozen > MAX_FROZEN_S:
        return f"tracer froze: no change in {frozen} of {DURATION_S} s (tracer solver skipped its iterations)"
    return None


def inputs(config: dict) -> dict:
    """The input columns from a case config; a tilted window has hinge `none` (PLAN.md §3)."""
    row = {"layout": config["layout"], "wind_speed_ms": config["wind_speed_ms"]}
    for name in ("window1", "window2"):
        window = config[name]
        row[f"{name}_x_m"] = window["x_m"]
        row[f"{name}_mode"] = window["mode"]
        row[f"{name}_angle_deg"] = window["angle_deg"]
        row[f"{name}_hinge"] = window["hinge"] if window["mode"] == "turn" else "none"
    return row


def number(value) -> str:
    """A value for the CSV: empty for missing or NaN, numbers without trailing noise."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, float):
        return f"{value:.6g}" if abs(value) < 1e6 else f"{value:.0f}"
    return str(value)


def build_row(case: Case) -> tuple[dict, np.ndarray | None]:
    """The CSV row of one finished case and the curve for its time series (None if failed)."""
    drawn = yaml.safe_load(case.drawn.read_text())
    used_path = case.folder / "config.yaml"
    used = yaml.safe_load(used_path.read_text()) if used_path.exists() else drawn
    row = {"case_id": case.case_id, "run_id": case.run_id, "split": case.split, **inputs(used),
           **{k: case.runner.get(k, "") for k in ("machine", "openfoam_version", "git_commit", "finished_utc")}}
    if inputs(used) != inputs(drawn):
        case.problems.append("the config that ran differs from the drawn case file (the CSV uses the one that ran)")
    method = "B" if used["layout"] == "same_wall" else "A"  # decision M1, PLAN.md §5
    row["method"] = method

    def failed(reason: str) -> tuple[dict, None]:
        row.update(status="failed", error_message=reason)
        return row, None

    try:
        summary = json.loads((case.folder / "summary.json").read_text())
    except (OSError, ValueError):
        reason = case.runner.get("error") or "no summary.json"
        tail = case.folder / "log_tail.txt"
        if not case.runner.get("error") and tail.exists():
            lines = [line for line in tail.read_text().splitlines() if line.strip()]
            reason = lines[-1][:200] if lines else reason
        return failed(reason)
    if summary.get("method", "A") != method:
        case.problems.append(f"summary.json says method {summary.get('method')}, expected {method}")
    if method == "B" and "transient" not in summary:
        return failed("method B result missing (transient stage did not finish)")
    final = summary["transient"] if method == "B" else summary
    curve_file = case.folder / ("fresh_fraction_transient.csv" if method == "B" else "fresh_fraction.csv")
    if not curve_file.exists():
        return failed(f"{curve_file.name} missing")
    curve = read_curve(curve_file)
    if reason := curve_problem(curve):
        case.problems.append(reason)
        return failed(reason)

    # checks that do not invalidate the values
    if final.get("tracer_min", 0) < -BOUNDS_TOL or final.get("tracer_max", 1) > 1 + BOUNDS_TOL:
        case.problems.append(f"tracer left its bounds: {final.get('tracer_min')} to {final.get('tracer_max')}")
    airflow, balance = final.get("airflow_m3h"), final.get("flow_balance_m3h")
    if airflow and balance is not None and abs(balance) > MAX_IMBALANCE * airflow:
        case.problems.append(f"inflow and outflow differ by {balance} m3/h of {airflow} m3/h")
    n_cells = summary.get("n_cells")
    if n_cells and abs(n_cells / MEDIUM_MESH_CELLS - 1) > 0.1:
        case.problems.append(f"{n_cells} cells, more than 10 % from the medium mesh ({MEDIUM_MESH_CELLS})")

    steady_t90, steady_tau = summary.get("t90_s"), summary.get("tau_s")
    if method == "B" and (case.folder / "fresh_fraction.csv").exists():
        if reason := curve_problem(read_curve(case.folder / "fresh_fraction.csv")):
            case.problems.append(f"method A curve: {reason}; steady columns left empty")
            steady_t90 = steady_tau = None
    seconds = [summary.get(k) for k in ("mesh_seconds", "flow_seconds", "tracer_seconds", "transient_seconds")]
    row.update(status="ok", error_message="", **{c: final.get(c) for c in CURVE_COLUMNS},
               t90_s=final.get("t90_s"), tau_s=final.get("tau_s"), airflow_m3h=airflow,
               steady_t90_s=steady_t90, steady_tau_s=steady_tau, n_cells=n_cells,
               runtime_s=round(sum(s for s in seconds if s), 1))
    return row, curve


# --- writing -----------------------------------------------------------------------------------

def write(out: Path, rows: list[dict], curves: dict[str, np.ndarray], info: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(out / "timeseries", ignore_errors=True)
    (out / "timeseries").mkdir()
    with (out / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for row in sorted(rows, key=lambda r: r["case_id"]):
            writer.writerow([number(row.get(c)) for c in COLUMNS])
    for case_id, curve in curves.items():
        lines = ["time_s,fresh_fraction"] + [f"{t:.0f},{f:.6f}" for t, f in curve]
        (out / "timeseries" / f"{case_id}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "dataset_info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


def collect(runs: list[str], configs: Path, cases: Path, status: dict | None) -> tuple[list[dict], dict, dict]:
    """Rows, curves of the ok rows, and dataset_info for the given runs."""
    all_cases = find_cases(runs, configs, cases, runner_info(status) if status else {})
    rows, curves = [], {}
    for case in all_cases:
        if case.folder is None:
            continue
        row, curve = build_row(case)
        rows.append(row)
        if curve is not None:
            curves[case.case_id] = curve
    info_runs = {}
    for run_id in runs:
        of_run = [c for c in all_cases if c.run_id == run_id]
        run_rows = [r for r in rows if r["run_id"] == run_id]
        info_runs[run_id] = {
            "split": of_run[0].split if of_run else None,
            "cases": len(of_run), "ok": sum(r["status"] == "ok" for r in run_rows),
            "failed": sum(r["status"] == "failed" for r in run_rows),
            "not_run_yet": sum(c.folder is None for c in of_run),
            "code_commits": sorted({r["git_commit"] for r in run_rows if r["git_commit"]}),
        }
    info = {
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "writer_commit": full_commit("HEAD"),
        "source": "hpc-results and hpc-status branches" if status else str(cases),
        "runs": info_runs,
        "rows": len(rows), "ok": len(curves), "failed": len(rows) - len(curves),
        "failed_cases": {r["case_id"]: r["error_message"] for r in rows if r["status"] == "failed"},
        "problems": {c.case_id: c.problems for c in all_cases if c.problems},
    }
    return rows, curves, info


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Collect finished sweep cases into results/summary.csv.")
    parser.add_argument("--runs", nargs="+", required=True, help="run ids, e.g. train-v1 test-v1")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--hpc", action="store_true", help="read the HPC runner's branches from origin")
    source.add_argument("--cases", type=Path, help="folder with the case folders (e.g. cases)")
    parser.add_argument("--configs", type=Path, default=Path("configs/sweep"), help="where the runs are drawn")
    parser.add_argument("--out", type=Path, default=Path("results"))
    parser.add_argument("--strict", action="store_true", help="stop on any problem, write nothing")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        cases, status = fetch_hpc(Path(tmp)) if args.hpc else (args.cases, None)
        rows, curves, info = collect(args.runs, args.configs, cases, status)

    for case_id, problems in info["problems"].items():
        for problem in problems:
            print(f"  {case_id}: {problem}")
    if args.strict and info["problems"]:
        raise SystemExit(f"--strict: {len(info['problems'])} case(s) with problems, nothing written")
    write(args.out, rows, curves, info)
    print(f"wrote {args.out}/summary.csv: {info['rows']} rows, {info['ok']} ok, {info['failed']} failed")
    for run_id, run in info["runs"].items():
        print(f"  {run_id} ({run['split']}): {run['ok']} ok, {run['failed']} failed, {run['not_run_yet']} not run yet")


if __name__ == "__main__":
    main()
