"""Air-replacement metrics from the tracer curve (PLAN.md §3).

fresh_fraction(t) = 1 - (room average of the tracer C) is the share of the
original indoor air that has been replaced by outdoor air at time t.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.optimize import curve_fit

CURVE_STEP_S = 30  # the dataset stores fresh_fraction every 30 s


def read_dat(path: Path) -> np.ndarray:
    """Numeric rows of an OpenFOAM postProcessing .dat file (comment lines skipped)."""
    rows = [line.split() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    return np.array(rows, dtype=float)


def read_series(function_dir: Path, filename: str) -> np.ndarray:
    """All rows of one function object's output, also across restarts of the run.

    After a restart at time T, OpenFOAM writes into a new folder named T. Rows of
    the earlier folders from T on were computed again, so they are dropped.
    """
    starts = sorted((d for d in function_dir.iterdir() if d.is_dir()), key=lambda d: float(d.name))
    parts = []
    for i, folder in enumerate(starts):
        data = read_dat(folder / filename)
        if data.size and i + 1 < len(starts):
            data = data[data[:, 0] < float(starts[i + 1].name)]
        if data.size:
            parts.append(data)
    return np.vstack(parts)


def fresh_fraction_curve(tracer_dir: Path, release_time: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Time [s] since the tracer release and fresh_fraction, starting at 0 with an unreplaced room."""
    data = read_series(tracer_dir / "postProcessing" / "roomTracer", "volFieldValue.dat")
    data = data[data[:, 0] > release_time]
    time = np.concatenate([[0.0], data[:, 0] - release_time])
    fresh = np.concatenate([[0.0], 1.0 - data[:, -1]])
    return time, fresh


def first_time_reaching(time: np.ndarray, fresh: np.ndarray, level: float) -> float:
    """First time fresh_fraction reaches `level` (linear interpolation), NaN if never."""
    above = np.nonzero(fresh >= level)[0]
    if len(above) == 0:
        return float("nan")
    i = above[0]
    if i == 0:
        return float(time[0])
    t0, t1, f0, f1 = time[i - 1], time[i], fresh[i - 1], fresh[i]
    return float(t0 + (level - f0) * (t1 - t0) / (f1 - f0))


def time_constant(time: np.ndarray, fresh: np.ndarray) -> float:
    """tau of the best fit fresh_fraction = 1 - exp(-t / tau) (always defined)."""
    guess = first_time_reaching(time, fresh, 1 - np.exp(-1))
    if np.isnan(guess):
        guess = time[-1]
    (tau,), _ = curve_fit(lambda t, tau: 1 - np.exp(-t / tau), time, fresh, p0=[max(guess, 1.0)],
                          bounds=(1e-3, 1e6))
    return float(tau)


def tracer_metrics(time: np.ndarray, fresh: np.ndarray, duration_s: float) -> dict:
    """The dataset values of PLAN.md §3 that come from the tracer curve."""
    metrics = {"t90_s": first_time_reaching(time, fresh, 0.9), "tau_s": time_constant(time, fresh)}
    for t in range(CURVE_STEP_S, int(duration_s) + 1, CURVE_STEP_S):
        metrics[f"fresh_frac_{t:03d}s"] = float(np.interp(t, time, fresh))
    return metrics


def tracer_bounds(tracer_dir: Path) -> tuple[float, float]:
    """Smallest and largest tracer value anywhere during the run (should stay within 0...1)."""
    data = read_series(tracer_dir / "postProcessing" / "tracerRange", "fieldMinMax.dat")
    return float(data[:, -2].min()), float(data[:, -1].max())
