"""Live monitor for running simulations: progress, CPU cores and convergence plots.

Usage, from the repository root with the venv active (e.g. in a second terminal):
    python -m analysis.monitor                    # window that updates every 5 s
    python -m analysis.monitor --once status.png  # one snapshot as a picture

It finds the running OpenFOAM solvers (simpleFoam, tracerFoam, pimpleFoam) from
the process list and reads their log and postProcessing files. Closing the
window does not affect the simulations.
"""

from __future__ import annotations

import argparse
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import psutil
from matplotlib.patches import Rectangle

SOLVERS = {
    "simpleFoam": "steady flow",
    "tracerFoam": "tracer on the frozen flow",
    "pimpleFoam": "time-varying flow + tracer",
}
REFRESH_S = 5
CASE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]  # categorical slots 1-3, in fixed order
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]
INK, MUTED, GRID, SURFACE, IDLE = "#0b0b0b", "#52514e", "#e1e0d9", "#fcfcfb", "#c9c7c0"


@dataclass
class RunningCase:
    folder: Path  # working directory of the solver = case (stage) folder
    solver: str
    ranks: list[psutil.Process] = field(default_factory=list)
    history: deque = field(default_factory=lambda: deque(maxlen=120))  # (wall time, simulated time)

    @property
    def name(self) -> str:
        parts = self.folder.parts
        return "/".join(parts[parts.index("cases") + 1:]) if "cases" in parts else self.folder.name


# --- Reading files ---------------------------------------------------------------


def _tail(path: Path, n_bytes: int = 200_000) -> str:
    """Last part of a (possibly large) text file."""
    if not path.exists():
        return ""
    with path.open("rb") as f:
        f.seek(max(0, path.stat().st_size - n_bytes))
        return f.read().decode(errors="replace")


def _last_float(pattern: str, text: str) -> float | None:
    matches = re.findall(pattern, text, re.M)
    return float(matches[-1]) if matches else None


def _table(path: Path) -> tuple[list[str], np.ndarray]:
    """Column names and numeric rows of a postProcessing .dat file (text columns become NaN)."""
    if not path.exists():
        return [], np.empty((0, 0))
    header, rows = [], []
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("# Time"):
            header = line[1:].split()
        elif line.strip() and not line.startswith("#"):
            rows.append(line.split())
    if not rows:
        return header, np.empty((0, 0))
    width = min(len(r) for r in rows)

    def number(text: str) -> float:
        try:
            return float(text)
        except ValueError:
            return np.nan

    return header, np.array([[number(v) for v in r[:width]] for r in rows])


def _series(function_dir: Path, filename: str) -> tuple[list[str], np.ndarray]:
    """Like _table, but joined over all (re)starts: rows computed again after a restart are dropped."""
    if not function_dir.exists():
        return [], np.empty((0, 0))
    starts = sorted((d for d in function_dir.iterdir() if d.is_dir()), key=lambda d: float(d.name))
    header, parts = [], []
    for i, folder in enumerate(starts):
        names, data = _table(folder / filename)
        header = names or header
        if data.size and i + 1 < len(starts):
            data = data[data[:, 0] < float(starts[i + 1].name)]
        if data.size and (not parts or data.shape[1] == parts[0].shape[1]):
            parts.append(data)
    return header, (np.vstack(parts) if parts else np.empty((0, 0)))


def _current_log(case: RunningCase) -> Path:
    """The newest log of this solver (a resumed run writes log.<solver>.resume1, ...)."""
    logs = list(case.folder.glob(f"log.{case.solver}*"))
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else case.folder / f"log.{case.solver}"


def progress(case: RunningCase) -> dict:
    """Current and end time, time step, Courant number and an estimated finish time."""
    log = _tail(_current_log(case))
    control = (case.folder / "system" / "controlDict").read_text(errors="replace")
    now = _last_float(r"^Time = ([\d.e+-]+)", log) or 0.0
    end = _last_float(r"^endTime\s+([\d.e+-]+);", control) or 1.0
    clock = _last_float(r"ClockTime = ([\d.e+-]+) s", log)

    case.history.append((time.time(), now))
    recent = [(w, s) for w, s in case.history if w > time.time() - 300]
    if len(recent) >= 2 and recent[-1][0] - recent[0][0] >= 20 and recent[-1][1] > recent[0][1]:
        rate = (recent[-1][1] - recent[0][1]) / (recent[-1][0] - recent[0][0])  # simulated per wall second
    elif clock and now > 0:
        rate = now / clock  # average since the start
    else:
        rate = None
    return {
        "now": now,
        "end": end,
        "fraction": min(now / end, 1.0),
        "eta_s": (end - now) / rate if rate else None,
        "dt": _last_float(r"^deltaT = ([\d.e+-]+)", log),
        "courant": _last_float(r"^Courant Number mean: [\d.e+-]+ max: ([\d.e+-]+)", log),
    }


# --- Processes and CPU cores -------------------------------------------------------


def find_running(previous: dict[Path, RunningCase]) -> dict[Path, RunningCase]:
    """Running solver processes, grouped by case folder (one entry per MPI run)."""
    found: dict[Path, RunningCase] = {}
    known = {p.pid: p for case in previous.values() for p in case.ranks}  # keeps cpu_percent state
    for proc in psutil.process_iter(["name"]):
        solver = proc.info["name"]
        if solver not in SOLVERS:
            continue
        try:
            folder = Path(proc.cwd())
        except psutil.Error:
            continue
        case = found.get(folder) or previous.get(folder) or RunningCase(folder, solver)
        if folder not in found:
            case.ranks, case.solver = [], solver
            found[folder] = case
        case.ranks.append(known.get(proc.pid, proc))
    return found


def _performance_cores() -> list[bool]:
    """True for fast cores (P-cores on hybrid CPUs): maximum clock above the midpoint."""
    freqs = []
    for core in range(psutil.cpu_count()):
        path = Path(f"/sys/devices/system/cpu/cpu{core}/cpufreq/cpuinfo_max_freq")
        freqs.append(int(path.read_text()) if path.exists() else 0)
    middle = (min(freqs) + max(freqs)) / 2
    return [f > middle or min(freqs) == max(freqs) for f in freqs]


def _core_usage(cases: list[RunningCase]) -> tuple[dict[int, int], list[str]]:
    """Which case runs on which core right now, and a pinning summary per case."""
    on_core, lines = {}, []
    n_cores = psutil.cpu_count()
    for i, case in enumerate(cases):
        cores, allowed = [], set()
        for rank in case.ranks:
            try:
                cores.append(rank.cpu_num())
                allowed.update(rank.cpu_affinity())
            except psutil.Error:
                continue
        for core in cores:
            on_core.setdefault(core, i)
        pinned = "not pinned (may use any core)" if len(allowed) == n_cores else f"pinned to cores {sorted(allowed)}"
        lines.append(f"{case.name}: {len(case.ranks)} processes, {pinned}, now on cores {sorted(cores)}")
    return on_core, lines


# --- Drawing -------------------------------------------------------------------------


def _style(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=9, color=INK)
    ax.set_xlabel(xlabel, fontsize=8, color=MUTED)
    ax.set_ylabel(ylabel, fontsize=8, color=MUTED)
    ax.tick_params(labelsize=7, colors=MUTED)
    ax.grid(color=GRID, linewidth=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)


def _empty(ax, message: str) -> None:
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=8, color=MUTED, transform=ax.transAxes)


def _plot_window_flows(ax, case: RunningCase, xlabel: str) -> None:
    _style(ax, "Air flow through each window (should level off)", xlabel, "m³/h")
    plotted = False
    for i, window in enumerate(("window1", "window2")):
        _, data = _series(case.folder / "postProcessing" / f"{window}Flow", "surfaceFieldValue.dat")
        if data.size:
            direction = "in" if data[-1, -1] >= 0 else "out"
            ax.plot(data[:, 0], np.abs(data[:, -1]) * 3600, color=SERIES[i], linewidth=1.2,
                    label=f"{window} ({direction})")
            plotted = True
    if plotted:
        ax.legend(fontsize=7, frameon=False, loc="best")
    else:
        _empty(ax, "no values yet")


def _plot_residuals(ax, case: RunningCase) -> None:
    _style(ax, "Residuals (should fall and level off)", "iteration", "initial residual")
    header, data = _series(case.folder / "postProcessing" / "residuals", "solverInfo.dat")
    columns = [(i, name.removesuffix("_initial")) for i, name in enumerate(header) if name.endswith("_initial")]
    if not data.size or not columns:
        _empty(ax, "no values yet")
        return
    for k, (i, name) in enumerate(columns[: len(SERIES)]):
        ax.semilogy(data[:, 0], data[:, i], color=SERIES[k], linewidth=1.0, label=name)
    ax.legend(fontsize=7, frameon=False, ncol=3, loc="upper right")


def _plot_fresh_air(ax, case: RunningCase) -> None:
    _style(ax, "Air replaced in the room", "time since the tracer started [s]", "%")
    _, data = _series(case.folder / "postProcessing" / "roomTracer", "volFieldValue.dat")
    monitors = (case.folder / "system" / "monitors")
    start = _last_float(r"timeStart\s+([\d.e+-]+);", monitors.read_text()) if monitors.exists() else None
    start = start or 0.0
    if not data.size:
        _empty(ax, f"tracer starts at t = {start:g} s" if start else "no values yet")
        return
    ax.plot(data[:, 0] - start, 100 * (1 - data[:, -1]), color=SERIES[0], linewidth=1.4)
    ax.set_ylim(0, 100)


def _plot_room_max(ax, case: RunningCase) -> None:
    _style(ax, "Highest share of old air anywhere in the room", "time [s]", "share")
    _, data = _series(case.folder / "postProcessing" / "roomTracerMax", "volFieldValue.dat")
    if not data.size:
        _empty(ax, "no values yet")
        return
    ax.plot(data[:, 0], data[:, -1], color=SERIES[1], linewidth=1.4)
    ax.set_ylim(0, 1.05)


def _text_panel(ax, case: RunningCase, color: str, info: dict) -> None:
    ax.axis("off")
    eta = info["eta_s"]
    if eta is None:
        eta_text = "finish time: estimating ..."
    else:
        finish = time.strftime("%H:%M", time.localtime(time.time() + eta))
        eta_text = f"remaining: {int(eta // 3600)} h {int(eta % 3600 // 60):02d} min (done ~{finish})"
    unit = "iterations" if case.solver == "simpleFoam" else "s"
    lines = [
        SOLVERS[case.solver],
        f"{case.solver} on {len(case.ranks)} processes",
        f"{info['now']:.6g} of {info['end']:.6g} {unit}  ({info['fraction']:.1%})",
        eta_text,
    ]
    if info["dt"] is not None:
        lines.append(f"time step {info['dt']:.4f} s, max Courant number {info['courant'] or 0:.1f}")
    ax.text(0, 1, case.name, fontsize=11, fontweight="bold", color=color, va="top", transform=ax.transAxes)
    ax.text(0, 0.80, "\n".join(lines), fontsize=8.5, color=INK, va="top", linespacing=1.6, transform=ax.transAxes)
    # Progress bar
    for width, bar_color in ((1.0, GRID), (info["fraction"], color)):
        ax.add_patch(Rectangle((0, 0.02), width, 0.07, color=bar_color, transform=ax.transAxes, clip_on=False))


def draw(fig, cases: dict[Path, RunningCase], perf_cores: list[bool]) -> None:
    fig.clf()
    fig.patch.set_facecolor(SURFACE)
    case_list = sorted(cases.values(), key=lambda c: c.name)[: len(CASE_COLORS)]  # stable colors
    n = max(len(case_list), 1)
    grid = fig.add_gridspec(n + 1, 3, height_ratios=[1] * n + [0.9], width_ratios=[0.9, 1.3, 1.3],
                            hspace=0.75, wspace=0.35, left=0.04, right=0.98, top=0.93, bottom=0.08)
    fig.suptitle(f"Simulation monitor  —  updated {time.strftime('%H:%M:%S')}, every {REFRESH_S} s",
                 x=0.04, ha="left", fontsize=11, color=INK)

    if not case_list:
        ax = fig.add_subplot(grid[0, :])
        ax.axis("off")
        _empty(ax, "No simulation is running right now.")
    for row, case in enumerate(case_list):
        color = CASE_COLORS[row]
        text_ax = fig.add_subplot(grid[row, 0])
        info = progress(case)
        _text_panel(text_ax, case, color, info)
        left, right = fig.add_subplot(grid[row, 1]), fig.add_subplot(grid[row, 2])
        if case.solver == "simpleFoam":
            _plot_residuals(left, case)
            _plot_window_flows(right, case, "iteration")
        elif case.solver == "tracerFoam":
            _plot_fresh_air(left, case)
            _plot_room_max(right, case)
        else:
            _plot_window_flows(left, case, "time [s]")
            _plot_fresh_air(right, case)

    # CPU cores: load per core, colored by the case currently running on it.
    on_core, pin_lines = _core_usage(case_list)
    usage = psutil.cpu_percent(percpu=True)
    ax = fig.add_subplot(grid[n, :2])
    _style(ax, "CPU load per core (colored = a solver process of that case is on it right now)", "", "%")
    colors = [CASE_COLORS[on_core[c]] if c in on_core else IDLE for c in range(len(usage))]
    ax.bar(range(len(usage)), usage, color=colors, width=0.7)
    ax.set_xticks(range(len(usage)),
                  [f"{c}\n{'P' if perf_cores[c] else 'E'}" for c in range(len(usage))], fontsize=7)
    ax.set_ylim(0, 100)
    ax.grid(axis="x", visible=False)
    note = fig.add_subplot(grid[n, 2])
    note.axis("off")
    note.text(0, 1, "P = performance core, E = efficiency core\n\n" + "\n".join(pin_lines or ["no solver processes"]),
              fontsize=7.5, color=INK, va="top", wrap=True, transform=note.transAxes)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Live monitor for running simulations.")
    parser.add_argument("--once", type=Path, help="save one snapshot to this PNG file instead of opening a window")
    args = parser.parse_args(argv)

    import matplotlib

    matplotlib.use("Agg" if args.once else "TkAgg")
    import matplotlib.pyplot as plt

    perf_cores = _performance_cores()
    psutil.cpu_percent(percpu=True)  # start the CPU load measurement
    state: dict[Path, RunningCase] = {}

    def refresh(fig) -> None:
        nonlocal state
        state = find_running(state)
        draw(fig, state, perf_cores)
        fig.canvas.draw_idle()

    n = max(len(find_running({})), 1)
    fig = plt.figure(figsize=(13, 2.7 * min(n, 3) + 2.3), dpi=90)
    if args.once:
        for rank in (p for c in find_running({}).values() for p in c.ranks):
            rank.cpu_percent(None)
        time.sleep(1.0)  # give the load measurement a moment
        refresh(fig)
        fig.savefig(args.once, facecolor=SURFACE)
        print(f"saved {args.once}")
        return
    fig.canvas.manager.set_window_title("stosslueften — simulation monitor")
    refresh(fig)
    timer = fig.canvas.new_timer(interval=REFRESH_S * 1000)
    timer.add_callback(refresh, fig)
    timer.start()
    plt.show()


if __name__ == "__main__":
    main()
