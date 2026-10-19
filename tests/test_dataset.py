import csv
import json

import numpy as np
import pytest
import yaml

from sweeps import dataset

# PLAN.md §3, frozen 2026-10-16 (M2): the header must never change by accident
FROZEN = ("case_id,run_id,split,layout,window1_x_m,window1_mode,window1_angle_deg,window1_hinge,window2_x_m,"
          "window2_mode,window2_angle_deg,window2_hinge,wind_speed_ms,status,error_message,method,"
          + ",".join(f"fresh_frac_{t:03d}s" for t in range(30, 601, 30))
          + ",t90_s,tau_s,airflow_m3h,steady_t90_s,steady_tau_s,n_cells,runtime_s,machine,openfoam_version,"
          "git_commit,finished_utc")


def _curve(tau: float) -> np.ndarray:
    t = np.arange(601.0)
    return np.column_stack([t, 1 - np.exp(-t / tau)])


def _write_curve(path, curve):
    path.write_text("time_s,fresh_fraction\n" + "".join(f"{t:.0f},{f:.6f}\n" for t, f in curve))


def _values(tau: float, airflow: float) -> dict:
    t = np.arange(601.0)
    fresh = 1 - np.exp(-t / tau)
    t90 = float(-tau * np.log(0.1)) if -tau * np.log(0.1) <= 600 else float("nan")
    return {"t90_s": t90, "tau_s": tau, "airflow_m3h": airflow, "flow_balance_m3h": 0.0, "tracer_min": 0.0,
            "tracer_max": 1.0, **{f"fresh_frac_{s:03d}s": float(fresh[s]) for s in range(30, 601, 30)}}


@pytest.fixture
def run(tmp_path):
    """A drawn run with three cases (A, B, not run yet) and the result folders of the first two."""
    configs, cases = tmp_path / "configs", tmp_path / "cases"
    (configs / "r").mkdir(parents=True)
    (configs / "r" / "manifest.json").write_text(json.dumps({"split": "train"}))
    windows = {"r_001": ("opposite_walls", "turn", 45.0), "r_002": ("same_wall", "tilt", 6), "r_003": ("adjacent_walls", "turn", 30.0)}
    for case_id, (layout, mode, angle) in windows.items():
        config = {"case_id": case_id, "layout": layout, "wind_speed_ms": 2.5,
                  "window1": {"x_m": 1.5, "mode": mode, "angle_deg": angle, "hinge": "left"},
                  "window2": {"x_m": 3.5, "mode": "turn", "angle_deg": 60.0, "hinge": "right"}}
        (configs / "r" / f"{case_id}.yaml").write_text(yaml.safe_dump(config))
    for case_id, method in (("r_001", "A"), ("r_002", "B")):
        folder = cases / "r" / case_id
        folder.mkdir(parents=True)
        (folder / "config.yaml").write_text((configs / "r" / f"{case_id}.yaml").read_text())
        summary = {"case_id": case_id, "n_cells": 103_500, "method": method, "mesh_seconds": 30.0,
                   "flow_seconds": 300.0, "tracer_seconds": 40.0, **_values(100.0, 3000.0)}
        _write_curve(folder / "fresh_fraction.csv", _curve(100.0))
        if method == "B":
            summary["transient"] = _values(400.0, 900.0)  # slow: t90 not reached in 600 s
            summary["transient_seconds"] = 4000.0
            _write_curve(folder / "fresh_fraction_transient.csv", _curve(400.0))
        (folder / "summary.json").write_text(json.dumps(summary))
    return configs, cases


def _rows(out):
    with (out / "summary.csv").open(newline="") as f:
        return {row["case_id"]: row for row in csv.DictReader(f)}


def _write(run, tmp_path, status=None):
    configs, cases = run
    rows, curves, info = dataset.collect(["r"], configs, cases, status)
    dataset.write(tmp_path / "results", rows, curves, info)
    return _rows(tmp_path / "results"), info


def test_header_is_the_frozen_column_list(run, tmp_path):
    _write(run, tmp_path)
    assert (tmp_path / "results" / "summary.csv").read_text().splitlines()[0] == FROZEN


def test_a_row_and_b_row(run, tmp_path):
    rows, info = _write(run, tmp_path)
    a, b = rows["r_001"], rows["r_002"]
    assert a["status"] == b["status"] == "ok" and a["method"] == "A" and b["method"] == "B"
    assert float(a["tau_s"]) == 100.0 and a["steady_tau_s"] == a["tau_s"] and float(a["airflow_m3h"]) == 3000.0
    # B rows: the results of the transient run, method A's values only in the steady columns
    assert float(b["tau_s"]) == 400.0 and float(b["steady_tau_s"]) == 100.0 and float(b["airflow_m3h"]) == 900.0
    assert float(b["runtime_s"]) == 4370.0
    assert info["runs"]["r"]["not_run_yet"] == 1 and "r_003" not in rows
    assert (tmp_path / "results" / "timeseries" / "r_002.csv").read_text().splitlines()[2] == "1,0.002497"


def test_t90_empty_when_not_reached_and_hinge_none_for_tilted_windows(run, tmp_path):
    rows, _ = _write(run, tmp_path)
    assert rows["r_002"]["t90_s"] == "" and rows["r_002"]["steady_t90_s"] != ""
    assert rows["r_002"]["window1_mode"] == "tilt" and rows["r_002"]["window1_hinge"] == "none"
    assert rows["r_001"]["window1_hinge"] == "left"


def test_a_frozen_tracer_makes_the_row_failed(run, tmp_path):
    configs, cases = run
    curve = _curve(400.0)
    curve[20:, 1] = curve[20, 1]  # the tracer stops changing after 20 s
    _write_curve(cases / "r" / "r_002" / "fresh_fraction_transient.csv", curve)
    rows, info = _write(run, tmp_path)
    assert rows["r_002"]["status"] == "failed" and "tracer froze" in rows["r_002"]["error_message"]
    assert rows["r_002"]["tau_s"] == "" and not (tmp_path / "results" / "timeseries" / "r_002.csv").exists()
    assert info["failed"] == 1 and "r_002" in info["problems"]


@pytest.mark.parametrize("change, message", [
    (lambda c: c.__setitem__((300, 1), c[299, 1] - 0.05), "falls"),
    (lambda c: c.__setitem__((slice(400, None), 1), 1.2), "leaves 0...1"),
])
def test_broken_curves_are_caught(change, message):
    curve = _curve(100.0)
    change(curve)
    assert message in dataset.curve_problem(curve)


def test_smaller_problems_are_reported_but_keep_the_row(run, tmp_path):
    configs, cases = run
    path = cases / "r" / "r_001" / "summary.json"
    summary = json.loads(path.read_text())
    summary.update(flow_balance_m3h=200.0, n_cells=80_000)
    path.write_text(json.dumps(summary))
    rows, info = _write(run, tmp_path)
    assert rows["r_001"]["status"] == "ok"
    assert any("inflow and outflow" in p for p in info["problems"]["r_001"])
    assert any("cells" in p for p in info["problems"]["r_001"])


def test_a_case_without_summary_is_failed_with_the_runner_error(run, tmp_path):
    configs, cases = run
    (cases / "r" / "r_001" / "summary.json").unlink()
    status = {"runner": {"host": "pc", "openfoam": "v2606"}, "runs": [{"run_id": "r", "code": None}],
              "results": [], "failures": [{"case_id": "r_001", "run_id": "r", "error": "timeout after 45 min",
                                            "finished": 0}]}
    rows, _ = _write(run, tmp_path, status)
    assert rows["r_001"]["status"] == "failed" and rows["r_001"]["error_message"] == "timeout after 45 min"
    assert rows["r_001"]["machine"] == "pc" and rows["r_001"]["tau_s"] == ""
