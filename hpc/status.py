"""status.json for the dashboard (HPC_PLAN.md §6): the same numbers as analysis.monitor, as data.

Built only when it is published (every few minutes), so reading logs here costs little.
JSON has no NaN, so "not reached" values (t90) become null.
"""

from __future__ import annotations

import json
import math
import os
import re
import socket
import time
from pathlib import Path

import psutil

from hpc.state import TERMINAL, Case, State

SCHEMA = 1
DEFAULT_MINUTES = {"A": 7.0, "B": 80.0}  # per case with 2 slots on the simulation PC, until real ones exist
SERIES_POINTS = 120


def clean(value):
    """NaN and infinity -> None, recursively (JSON.parse in the browser rejects NaN)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def _thin(values: list, n: int = SERIES_POINTS) -> list:
    if len(values) <= n:
        return values
    step = len(values) / n
    return [values[int(i * step)] for i in range(n - 1)] + [values[-1]]


def _tail(path: Path, size: int = 65536) -> str:
    """The end of a possibly very large log file."""
    try:
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - size))
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def _last_number(pattern: str, text: str) -> float | None:
    found = re.findall(pattern, text, re.M)
    try:
        return float(found[-1]) if found else None
    except ValueError:
        return None


def _dat(path_dir: Path, name: str) -> list[list[float]]:
    """All rows of an OpenFOAM postProcessing table (all restart folders joined)."""
    rows = []
    for file in sorted(path_dir.glob(f"*/{name}"), key=lambda p: float(p.parent.name) if p.parent.name[0].isdigit() else 0):
        for line in file.read_text(errors="replace").splitlines():
            if line and not line.startswith("#"):
                try:
                    rows.append([float(v) for v in line.split()])
                except ValueError:
                    continue
    return rows


def _residual_series(case_dir: Path) -> list[float]:
    """Initial residual of p per iteration of the steady flow (postProcessing/residuals)."""
    files = list((case_dir / "postProcessing" / "residuals").glob("*/solverInfo.dat"))
    if not files:
        return []
    lines = files[0].read_text(errors="replace").splitlines()
    header = next((l for l in lines if l.startswith("# Time")), "").lstrip("# ").split()
    if "p_initial" not in header:
        return []
    col = header.index("p_initial")
    values = []
    for line in lines:
        if line and not line.startswith("#"):
            parts = line.split()
            try:
                values.append(float(parts[col]))
            except (IndexError, ValueError):
                continue
    return _thin(values)


def _replaced_series(stage_dir: Path) -> list[float]:
    """Share of the room air replaced so far, in % (1 - room-average tracer)."""
    rows = _dat(stage_dir / "postProcessing" / "roomTracer", "volFieldValue.dat")
    return _thin([round(100 * (1 - r[-1]), 2) for r in rows])


def case_progress(case_dir: Path) -> dict:
    """Stage (mesh, flow, tracer, transient), progress 0-1 and a short series to plot."""
    stages = [("transient", case_dir / "transient", "log.pimpleFoam"),
              ("tracer", case_dir / "tracer", "log.tracerFoam"),
              ("flow", case_dir, "log.simpleFoam")]
    for stage, folder, log_name in stages:
        log = folder / log_name
        if not log.exists():
            continue
        text = _tail(log)
        now = _last_number(r"^Time = ([\d.e+-]+)", text)
        try:
            end = _last_number(r"^endTime\s+([\d.e+-]+);", (folder / "system" / "controlDict").read_text())
        except OSError:
            end = None
        progress = min(now / end, 1.0) if now is not None and end else None
        if stage == "flow":
            series = {"label": "residual p", "log": True, "values": _residual_series(case_dir)}
        else:
            series = {"label": "air replaced [%]", "log": False, "values": _replaced_series(folder)}
        return {"stage": stage, "progress": progress, "series": series}
    meshing = any(case_dir.glob("log.*")) if case_dir.exists() else False
    return {"stage": "mesh" if meshing else "starting", "progress": None, "series": None}


def _summary(case_dir: Path) -> dict:
    try:
        return json.loads((case_dir / "summary.json").read_text())
    except (OSError, ValueError):
        return {}


def case_result(case: Case, case_dir: Path) -> dict:
    """The dataset values of a finished case: method B's for same-wall cases (decision M1)."""
    summary = _summary(case_dir)
    final = summary.get("transient", {}) if case.method == "B" else summary
    return {"case_id": case.case_id, "run_id": case.run_id, "layout": case.layout, "method": case.method,
            "wind_speed_ms": case.wind_speed_ms, "t90_s": final.get("t90_s"), "tau_s": final.get("tau_s"),
            "airflow_m3h": final.get("airflow_m3h"), "seconds": case.seconds, "finished": case.finished,
            "status": case.status}


def machine(path: Path) -> dict:
    memory = psutil.virtual_memory()
    return {"cpu": [round(v) for v in psutil.cpu_percent(percpu=True)],
            "ram_used_gb": round((memory.total - memory.available) / 2**30, 1),
            "ram_total_gb": round(memory.total / 2**30, 1),
            "disk_free_gb": round(psutil.disk_usage(str(path)).free / 2**30),
            "load": [round(v, 2) for v in os.getloadavg()]}


def run_summary(state: State, run_id: str, now: float) -> dict:
    run = state.runs[run_id]
    cases = state.cases_of(run_id)
    counts = {s: sum(c.status == s for c in cases) for s in ("done", "running", "pending", "failed", "skipped")}
    minutes = {}
    for method in ("A", "B"):
        times = [c.seconds / 60 for c in cases if c.status == "done" and c.method == method and c.seconds]
        minutes[method] = sum(times) / len(times) if times else DEFAULT_MINUTES[method]
    work = sum(minutes[c.method] for c in cases if c.status == "pending")
    work += sum(max(minutes[c.method] - (now - c.started) / 60, 0) for c in cases if c.status == "running" and c.started)
    left = not all(c.status in TERMINAL for c in cases)
    hours = max((now - run.started) / 3600, 1e-6)
    return {"run_id": run_id, "counts": counts, "total": len(cases), "started": run.started, "finished": run.finished,
            "per_hour": round(counts["done"] / hours, 1), "minutes_per_case": {k: round(v, 1) for k, v in minutes.items()},
            "eta": round(now + work * 60 / max(run.slots, 1)) if left else None,
            "code": run.code[:7], "slots": run.slots, "procs": run.procs}


def build(state: State, cases_dir: Path, runner: dict, latest: dict | None, log_tail, now: float | None = None) -> dict:
    """The whole status; `log_tail(case)` gives the last log lines of a case (for failures)."""
    now = now or time.time()
    by_time = sorted((c for c in state.cases.values() if c.status in ("done", "failed") and c.finished),
                     key=lambda c: c.finished, reverse=True)
    running = []
    for c in sorted(state.running(), key=lambda c: c.started or 0):
        running.append({"case_id": c.case_id, "run_id": c.run_id, "layout": c.layout, "method": c.method,
                        "attempt": c.attempts, "elapsed_s": round(now - c.started) if c.started else None,
                        **case_progress(cases_dir / c.case_id)})
    failures = [{"case_id": c.case_id, "run_id": c.run_id, "attempts": c.attempts, "error": c.error,
                 "status": c.status, "log_tail": log_tail(c)}
                for c in state.cases.values() if c.error and c.status in ("failed", "pending")]
    status = {
        "schema": SCHEMA, "updated": round(now), "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "runner": {"host": socket.gethostname(), "openfoam": os.environ.get("WM_PROJECT_VERSION"), **runner},
        "machine": machine(cases_dir.parent),
        "runs": [run_summary(state, run_id, now) for run_id in state.runs],
        "running": running,
        "finished": [case_result(c, cases_dir / c.case_id) for c in by_time[:30]],
        "results": [case_result(c, cases_dir / c.case_id) for c in by_time if c.status == "done"],
        "failures": failures[-20:],
        "events": state.events[-50:][::-1],
        "latest": latest,
    }
    return clean(status)
