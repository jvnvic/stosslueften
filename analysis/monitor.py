"""Live monitor for running simulations: progress, convergence, CPU cores and run queues.

Usage, from the repository root with the venv active (e.g. in a second terminal):
    python -m analysis.monitor                         # window on the right half of the screen
    python -m analysis.monitor --geometry 960x1040+960+0   # or an explicit size and position
    python -m analysis.monitor --interval 10           # refresh every 10 s (default 5)
    python -m analysis.monitor --once status.png       # one snapshot as a picture

It shows
- every running OpenFOAM solver or mesh tool, one row per case folder, with progress,
  a finish estimate and two small convergence plots;
- the load of every CPU core and which case runs on it (any number of cores);
- the run queues started with `python -m cfd.queue`.

The monitor only reads files, and on each refresh only the lines added since the
last one. Closing it does not affect the simulations.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import psutil
from matplotlib.patches import Rectangle

CASES = Path("cases")
QUEUE_DIR = CASES / "queues"
SOLVERS = {"simpleFoam": "steady flow", "tracerFoam": "tracer", "pimpleFoam": "transient flow + tracer"}
TOOLS = ("blockMesh", "snappyHexMesh", "surfaceFeatureExtract", "gmshToFoam", "topoSet", "createPatch",
         "renumberMesh", "checkMesh", "decomposePar", "reconstructPar", "setFields", "wmake")
MAX_RUN_ROWS = 4  # more parallel runs are listed in the header
PLOT_POINTS = 1500  # longer series are thinned before plotting

# Dark theme. Run colors: the categorical palette's dark-mode steps, always in this order.
BG, PANEL, GRID = "#1b1d21", "#22252a", "#34383f"
TEXT, MUTED, IDLE = "#d8dade", "#8b9099", "#5b616b"
RUN_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"]
MONO = "DejaVu Sans Mono"


# --- Reading growing files -------------------------------------------------------


def _number(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return math.nan  # text columns such as solver names


class TailTable:
    """A growing postProcessing .dat file. Each update reads only the lines added since the last one."""

    def __init__(self, path: Path):
        self.path, self.offset, self.rest = path, 0, ""
        self.header: list[str] = []
        self.rows: list[list[float]] = []
        self.array = np.empty((0, 0))

    def update(self) -> tuple[list[str], np.ndarray]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return self.header, self.array
        if size < self.offset:  # the file was written anew
            self.__init__(self.path)
        if size > self.offset:
            with self.path.open("rb") as f:
                f.seek(self.offset)
                chunk = self.rest + f.read(size - self.offset).decode(errors="replace")
            self.offset = size
            lines = chunk.split("\n")
            self.rest = lines.pop()  # the last line may still be incomplete
            for line in lines:
                if line.startswith("# Time"):
                    self.header = line[1:].split()
                elif line.strip() and not line.startswith("#"):
                    self.rows.append([_number(v) for v in line.split()])
            width = min((len(r) for r in self.rows), default=0)
            self.array = np.array([r[:width] for r in self.rows]) if self.rows else np.empty((0, 0))
        return self.header, self.array


_tables: dict[Path, TailTable] = {}


def series(function_dir: Path, filename: str) -> tuple[list[str], np.ndarray]:
    """Output of one function object over all (re)starts; rows computed again after a restart are dropped."""
    if not function_dir.is_dir():
        return [], np.empty((0, 0))
    starts = sorted((d for d in function_dir.iterdir() if d.is_dir()), key=lambda d: _number(d.name))
    header, parts = [], []
    for i, folder in enumerate(starts):
        table = _tables.setdefault(folder / filename, TailTable(folder / filename))
        names, data = table.update()
        header = names or header
        if data.size and i + 1 < len(starts):
            data = data[data[:, 0] < _number(starts[i + 1].name)]
        if data.size and (not parts or data.shape[1] == parts[0].shape[1]):
            parts.append(data)
    return header, (np.vstack(parts) if parts else np.empty((0, 0)))


def _thin(data: np.ndarray) -> np.ndarray:
    if len(data) <= PLOT_POINTS:
        return data
    return data[np.linspace(0, len(data) - 1, PLOT_POINTS).astype(int)]


def _tail_text(path: Path, n_bytes: int = 64_000) -> str:
    try:
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - n_bytes))
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def _last(pattern: str, text: str) -> float | None:
    matches = re.findall(pattern, text, re.M)
    return float(matches[-1]) if matches else None


# --- Runs, progress and CPU cores ---------------------------------------------------


@dataclass
class Run:
    folder: Path  # working directory of the program = case (stage) folder
    program: str
    procs: list[psutil.Process] = field(default_factory=list)
    history: deque = field(default_factory=lambda: deque(maxlen=120))  # (wall time, simulated time)
    known: dict = field(default_factory=dict, repr=False)  # pid -> Process from the last refresh

    @property
    def name(self) -> str:
        parts = self.folder.parts
        return "/".join(parts[parts.index("cases") + 1:]) if "cases" in parts else self.folder.name

    @property
    def is_solver(self) -> bool:
        return self.program in SOLVERS


def find_runs(previous: dict[Path, Run]) -> dict[Path, Run]:
    """Running solvers and mesh tools, grouped by working directory (one entry per MPI run)."""
    runs: dict[Path, Run] = {}
    for proc in psutil.process_iter(["name"]):
        program = proc.info["name"]
        if program not in SOLVERS and program not in TOOLS:
            continue
        try:
            folder = Path(proc.cwd())
        except psutil.Error:
            continue
        if folder not in runs:
            run = previous.get(folder) or Run(folder, program)
            known = {p.pid: p for p in run.procs}  # keep Process objects: their CPU counters
            run.procs, run.program = [], program
            run.known = known
            runs[folder] = run
        run = runs[folder]
        if program in SOLVERS:
            run.program = program
        run.procs.append(run.known.get(proc.pid, proc))
    return runs


def progress(run: Run) -> dict:
    """Simulated time, end time, time step, Courant number and finish estimate of a solver run."""
    logs = list(run.folder.glob(f"log.{run.program}*"))
    log = _tail_text(max(logs, key=lambda p: p.stat().st_mtime)) if logs else ""
    try:
        control = (run.folder / "system" / "controlDict").read_text(errors="replace")
    except OSError:
        control = ""
    now = _last(r"^Time = ([\d.e+-]+)", log) or 0.0
    end = _last(r"^endTime\s+([\d.e+-]+);", control) or 1.0
    clock = _last(r"ClockTime = ([\d.e+-]+) s", log)
    run.history.append((time.time(), now))
    recent = [(w, s) for w, s in run.history if w > time.time() - 300]
    if len(recent) >= 2 and recent[-1][0] - recent[0][0] >= 20 and recent[-1][1] > recent[0][1]:
        rate = (recent[-1][1] - recent[0][1]) / (recent[-1][0] - recent[0][0])
    elif clock and now > 0:
        rate = now / clock
    else:
        rate = None
    return {"now": now, "end": end, "fraction": min(now / end, 1.0), "eta_s": (end - now) / rate if rate else None,
            "dt": _last(r"^deltaT = ([\d.e+-]+)", log),
            "courant": _last(r"^Courant Number mean: [\d.e+-]+ max: ([\d.e+-]+)", log)}


def performance_cores() -> list[bool]:
    """True for fast cores (P-cores on hybrid CPUs): maximum clock above the midpoint."""
    freqs = []
    for core in range(psutil.cpu_count()):
        path = Path(f"/sys/devices/system/cpu/cpu{core}/cpufreq/cpuinfo_max_freq")
        freqs.append(int(path.read_text()) if path.exists() else 0)
    middle = (min(freqs) + max(freqs)) / 2
    return [f > middle or min(freqs) == max(freqs) for f in freqs]


def core_owners(runs: list[Run]) -> tuple[dict[int, int], list[str]]:
    """Which run is on which core right now, and a pinning note per run."""
    owners, notes, n_cores = {}, [], psutil.cpu_count()
    for i, run in enumerate(runs):
        cores, allowed = [], set()
        for proc in run.procs:
            try:
                cores.append(proc.cpu_num())
                allowed.update(proc.cpu_affinity())
            except psutil.Error:
                continue
        for core in cores:
            owners.setdefault(core, i)
        pinned = "not pinned" if len(allowed) == n_cores else f"pinned to {sorted(allowed)}"
        notes.append(f"{run.name}: {len(run.procs)} proc, {pinned}")
    return owners, notes


# --- Queues ---------------------------------------------------------------------


def read_queues(keep_s: float = 3600) -> list[dict]:
    """Queues that are still running or changed within the last hour, newest first."""
    queues = []
    for path in sorted(QUEUE_DIR.glob("*.json"), reverse=True):
        try:
            state = json.loads(path.read_text())
            recent = time.time() - path.stat().st_mtime < keep_s
        except (OSError, ValueError):
            continue
        try:
            alive = "cfd.queue" in " ".join(psutil.Process(state["pid"]).cmdline())
        except (psutil.Error, KeyError):
            alive = False
        if alive or recent:
            queues.append({**state, "name": path.stem, "alive": alive})
    return queues


def queue_remaining_s(state: dict) -> float | None:
    """Estimated time until the queue is done: average duration of its finished entries."""
    entries = state["entries"]
    done = [e["seconds"] for e in entries if e["status"] == "done" and e["seconds"]]
    if not done:
        return None
    average = sum(done) / len(done)
    pending = sum(e["status"] == "pending" for e in entries)
    running = sum(max(average - (time.time() - e["started"]), 0) for e in entries if e["status"] == "running")
    return average * pending + running


def _duration(seconds: float) -> str:
    seconds = max(seconds, 0)
    if seconds >= 3600:
        return f"{int(seconds // 3600)} h {int(seconds % 3600 // 60):02d} min"
    if seconds >= 60:
        return f"{int(seconds // 60)} min {int(seconds % 60):02d} s"
    return f"{seconds:.0f} s"


def _bar(fraction: float, width: int = 24) -> str:
    filled = round(fraction * width)
    return "[" + "#" * filled + "." * (width - filled) + "]"


def _entry_line(e: dict) -> tuple[str, str]:
    name = Path(e["config"]).stem[:30]
    if e["status"] == "done":
        t90 = e.get("t90_s")
        t90 = ("t90 not reached" if math.isnan(t90) else f"t90 {t90:.1f} s") if isinstance(t90, (int, float)) else ""
        return f"  done  {name:<30} {_duration(e['seconds']):>12}  {t90}", MUTED
    if e["status"] == "running":
        return f"  run   {name:<30} {_duration(time.time() - e['started']):>12}", TEXT
    if e["status"] == "failed":
        return f"  FAIL  {name:<30} {(e.get('error') or '')[:48]}", "#e66767"
    return f"  wait  {name}", MUTED


def queue_lines(queues: list[dict]) -> list[tuple[str, str]]:
    """(text, color) lines for the scrollable queue panel.

    Per queue: a summary (progress, counts, throughput, finish estimate), then every
    entry: running, failed, waiting (in run order) and finished (newest first).
    """
    lines = []
    for q in queues:
        entries = q["entries"]
        by_status = {s: [e for e in entries if e["status"] == s] for s in ("done", "running", "failed", "pending")}
        n_finished = len(by_status["done"]) + len(by_status["failed"])
        state = "running" if q["alive"] else ("finished" if q.get("finished") else "STOPPED (resume with --resume)")
        lines.append((f"queue {q['name']}  {state}", TEXT))
        lines.append((f"  {_bar(n_finished / max(len(entries), 1))} {n_finished}/{len(entries)}   "
                      f"done {len(by_status['done'])}  run {len(by_status['running'])}  "
                      f"failed {len(by_status['failed'])}  wait {len(by_status['pending'])}",
                      "#e66767" if by_status["failed"] else TEXT))
        durations = [e["seconds"] for e in by_status["done"] if e["seconds"]]
        remaining = queue_remaining_s(q)
        if durations and q["alive"]:
            average = sum(durations) / len(durations)
            finish = time.strftime("%a %H:%M", time.localtime(time.time() + remaining)) if remaining else "-"
            lines.append((f"  avg {_duration(average)} per case ({3600 / average:.1f}/h)   "
                          f"left ~{_duration(remaining or 0)}   done ~{finish}", MUTED))
        for status in ("running", "failed", "pending"):
            lines += [_entry_line(e) for e in by_status[status]]
        lines += [_entry_line(e) for e in reversed(by_status["done"])]
        lines.append(("", MUTED))
    return lines


# --- Drawing -------------------------------------------------------------------------
# Layout, top to bottom: title line | per run: info line + slim progress bar |
# per run: two plots | CPU core bars | small notes | queue list (rest of the height, scrollable).


def _style(ax, title: str) -> None:
    ax.set_facecolor(PANEL)
    ax.set_title(title, loc="left", fontsize=8, color=MUTED, pad=3)
    ax.tick_params(labelsize=7, colors=MUTED, length=2)
    ax.grid(color=GRID, linewidth=0.6)
    for spine in ax.spines.values():
        spine.set_color(GRID)


def _note(ax, text: str) -> None:
    ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=8, color=MUTED, transform=ax.transAxes)


def _plot_residuals(ax, run: Run, color: str) -> None:
    _style(ax, "residuals (initial)")
    header, data = series(run.folder / "postProcessing" / "residuals", "solverInfo.dat")
    columns = [(i, n.removesuffix("_initial")) for i, n in enumerate(header) if n.endswith("_initial")]
    if not data.size or not columns:
        return _note(ax, "no values yet")
    data = _thin(data)
    for k, (i, name) in enumerate(columns[: len(RUN_COLORS)]):
        if i < data.shape[1]:
            ax.semilogy(data[:, 0], data[:, i], color=RUN_COLORS[k], linewidth=0.9, label=name)
    ax.legend(fontsize=6.5, frameon=False, ncol=3, loc="upper right", labelcolor=TEXT)


def _plot_window_flows(ax, run: Run, color: str) -> None:
    _style(ax, "window flow [m³/h] (should level off)")
    plotted = False
    for window, line_color, dash in (("window1", TEXT, "-"), ("window2", MUTED, "--")):
        _, data = series(run.folder / "postProcessing" / f"{window}Flow", "surfaceFieldValue.dat")
        if data.size:
            data = _thin(data)
            direction = "in" if data[-1, -1] >= 0 else "out"
            ax.plot(data[:, 0], np.abs(data[:, -1]) * 3600, color=line_color, linestyle=dash, linewidth=1.0,
                    label=f"{window} {direction}")
            plotted = True
    if plotted:
        ax.legend(fontsize=6.5, frameon=False, loc="best", labelcolor=TEXT)
    else:
        _note(ax, "no values yet")


def _plot_air_replaced(ax, run: Run, color: str) -> None:
    _style(ax, "air replaced [%]")
    _, data = series(run.folder / "postProcessing" / "roomTracer", "volFieldValue.dat")
    monitors = run.folder / "system" / "monitors"
    start = _last(r"timeStart\s+([\d.e+-]+);", monitors.read_text()) if monitors.exists() else None
    if not data.size:
        return _note(ax, f"tracer starts at t = {start:g} s" if start else "no values yet")
    data = _thin(data)
    ax.plot(data[:, 0] - (start or 0), 100 * (1 - data[:, -1]), color=color, linewidth=1.3)
    ax.set_ylim(0, 100)


def _plot_room_max(ax, run: Run, color: str) -> None:
    _style(ax, "highest old-air share in the room")
    _, data = series(run.folder / "postProcessing" / "roomTracerMax", "volFieldValue.dat")
    if not data.size:
        return _note(ax, "no values yet")
    data = _thin(data)
    ax.plot(data[:, 0], data[:, -1], color=color, linewidth=1.3)
    ax.set_ylim(0, 1.05)


PLOTS = {
    "simpleFoam": (_plot_residuals, _plot_window_flows),
    "tracerFoam": (_plot_air_replaced, _plot_room_max),
    "pimpleFoam": (_plot_window_flows, _plot_air_replaced),
}


def _safe(ax, draw_panel, *args) -> None:
    """Draw one panel; a half-written file or similar must never stop the monitor."""
    try:
        draw_panel(ax, *args)
    except Exception as error:  # noqa: BLE001 - keep the window alive whatever happens
        ax.clear()
        ax.set_facecolor(PANEL)
        _note(ax, f"not available ({error.__class__.__name__})")


def _empty_panel(ax) -> None:
    ax.set_facecolor(PANEL)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color(GRID)


def run_info(run: Run) -> tuple[str, float | None]:
    """One-line status of a run and its progress (None while a mesh tool runs)."""
    if not run.is_solver:
        try:
            age = time.time() - min(p.create_time() for p in run.procs)
        except (psutil.Error, ValueError):
            age = 0
        return f"preparing: {run.program}  ({_duration(age)})", None
    info = progress(run)
    unit = "it" if run.program == "simpleFoam" else "s"
    eta = info["eta_s"]
    finish = "estimating" if eta is None else \
        f"left {_duration(eta)} (~{time.strftime('%H:%M', time.localtime(time.time() + eta))})"
    text = f"{run.program} {len(run.procs)}p   {info['now']:.6g}/{info['end']:.6g} {unit}   {info['fraction']:5.1%}   {finish}"
    if info["dt"] is not None:
        text += f"   dt {info['dt']:.4f} s  Co {info['courant'] or 0:.1f}"
    return text, info["fraction"]


def _run_header(ax, run: Run, color: str) -> None:
    """Title and status on one line, slim progress bar across the full width below."""
    ax.axis("off")
    text, fraction = run_info(run)
    ax.text(0, 0.95, run.name, fontsize=10, fontweight="bold", color=color, va="top", transform=ax.transAxes)
    ax.text(1, 0.95, text, fontsize=8.5, color=TEXT, va="top", ha="right", family=MONO, transform=ax.transAxes)
    ax.add_patch(Rectangle((0, 0.0), 1.0, 0.16, color=GRID, transform=ax.transAxes, clip_on=False))
    if fraction is not None:
        ax.add_patch(Rectangle((0, 0.0), fraction, 0.16, color=color, transform=ax.transAxes, clip_on=False))


def cpu_grid(n_cores: int, width_in: float) -> tuple[int, int]:
    """(rows, columns) of the core bars: about 2.2 inch per column, rows filled evenly.

    8 cores: one row at full 16:9 width, 2 x 4 on half a screen.
    """
    fit = max(1, min(n_cores, int(width_in / 2.2)))
    rows = math.ceil(n_cores / fit)
    return rows, math.ceil(n_cores / rows)


def _cpu(ax, usage: list[float], owners: dict[int, int], perf: list[bool], cols: int) -> None:
    """One compact bar per core, colored by the run whose process is on that core right now."""
    ax.axis("off")
    rows = math.ceil(len(usage) / cols)
    label_w, value_w, gap = 0.17, 0.17, 0.1
    for core, load in enumerate(usage):
        row, col = divmod(core, cols)
        x0, y = col * (1 + gap), rows - 1 - row
        color = RUN_COLORS[owners[core] % len(RUN_COLORS)] if core in owners else IDLE
        track = 1 - label_w - value_w
        ax.text(x0, y, f"{core:>2} {'P' if perf[core] else 'E'}", fontsize=7.5, color=MUTED, va="center", family=MONO)
        ax.add_patch(Rectangle((x0 + label_w, y - 0.3), track, 0.6, color=GRID))
        ax.add_patch(Rectangle((x0 + label_w, y - 0.3), track * min(load, 100) / 100, 0.6, color=color))
        ax.text(x0 + 1, y, f"{load:3.0f}%", fontsize=7.5, color=TEXT, va="center", ha="right", family=MONO)
    ax.set_xlim(0, cols + gap * (cols - 1))
    ax.set_ylim(-0.6, rows - 0.4)


class Monitor:
    """Collects data on a timer and draws it; scrolling and resizing only redraw."""

    LINE_PT = 8  # queue text size

    def __init__(self, fig, max_runs: int = MAX_RUN_ROWS):
        self.fig, self.max_runs = fig, max_runs
        self.perf = performance_cores()
        self.state: dict[Path, Run] = {}
        self.runs: list[Run] = []
        self.queues: list[dict] = []
        self.usage: list[float] = []
        self.queue_scroll = 0  # first visible queue line
        self.queue_ax = None
        psutil.cpu_percent(percpu=True)  # start the CPU load measurement

    def refresh(self) -> None:
        """Read processes, files and queues (the only part that touches the system)."""
        self.state = find_runs(self.state)
        self.runs = sorted(self.state.values(), key=lambda r: r.name)  # stable order = stable colors
        self.queues = read_queues()
        self.usage = psutil.cpu_percent(percpu=True)
        self.draw()

    def on_scroll(self, event) -> None:
        if self.queue_ax is not None and event.inaxes is self.queue_ax:
            self.queue_scroll = max(0, self.queue_scroll - 3 * int(event.step))
            self.draw()

    def draw(self) -> None:
        fig = self.fig
        fig.clf()
        fig.patch.set_facecolor(BG)
        width_in, height_in = fig.get_size_inches()
        shown = self.runs[: self.max_runs]
        n = max(len(shown), 1)
        cpu_rows, cpu_cols = cpu_grid(len(self.usage), width_in * 0.94)
        owners, notes = core_owners(shown)
        q_lines = queue_lines(self.queues) or [("no queue (start one with: python -m cfd.queue ...)", MUTED)]

        # Row heights in inches: fixed parts first, the queue list gets what is left.
        title_h, header_h = 0.3, 0.42 * n
        plots_h = n * min(max(0.28 * height_in / n ** 0.5, 1.3), 3.2)
        cpu_h, notes_h = 0.15 + 0.22 * cpu_rows, 0.16 * (len(notes) + 1)
        queue_h = max(height_in - (title_h + header_h + plots_h + cpu_h + notes_h) - 0.45, 1.0)
        outer = fig.add_gridspec(6, 1, height_ratios=[title_h, header_h, plots_h, cpu_h, notes_h, queue_h],
                                 left=0.045, right=0.985, top=0.99, bottom=0.01, hspace=0.22)

        title = fig.add_subplot(outer[0])
        title.axis("off")
        title.text(0, 0.9, "stosslueften  |  simulation monitor", fontsize=11, color=TEXT, va="top",
                   transform=title.transAxes)
        extra = f" (+{len(self.runs) - len(shown)} more)" if len(self.runs) > len(shown) else ""
        n_wait = sum(e["status"] == "pending" for q in self.queues for e in q["entries"])
        title.text(1, 0.9, f"{time.strftime('%H:%M:%S')}   {len(self.runs)} running{extra}   {n_wait} queued",
                   fontsize=9, color=MUTED, va="top", ha="right", family=MONO, transform=title.transAxes)

        headers = outer[1].subgridspec(n, 1, hspace=0.25)
        plots = outer[2].subgridspec(n, 2, hspace=0.45, wspace=0.16)
        if not shown:
            ax = fig.add_subplot(headers[0])
            ax.axis("off")
            ax.text(0, 0.5, "no simulation running", fontsize=9, color=MUTED, va="center", transform=ax.transAxes)
            for col in (0, 1):
                _empty_panel(fig.add_subplot(plots[0, col]))
        for i, run in enumerate(shown):
            color = RUN_COLORS[i % len(RUN_COLORS)]
            _safe(fig.add_subplot(headers[i]), _run_header, run, color)
            panels = PLOTS.get(run.program)
            for col in (0, 1):
                ax = fig.add_subplot(plots[i, col])
                if panels:
                    _safe(ax, panels[col], run, color)
                else:
                    _empty_panel(ax)

        _safe(fig.add_subplot(outer[3]), _cpu, self.usage, owners, self.perf, cpu_cols)
        notes_ax = fig.add_subplot(outer[4])
        notes_ax.axis("off")
        notes_ax.text(0, 1, "\n".join(["CPU bars: color = run on that core, gray = other load", *notes]),
                      fontsize=7, color=MUTED, va="top", family=MONO, linespacing=1.3, transform=notes_ax.transAxes)

        # Queue list: only the visible lines are drawn; the mouse wheel scrolls.
        self.queue_ax = ax = fig.add_subplot(outer[5])
        ax.axis("off")
        line_px = self.LINE_PT * 1.45 / 72 * fig.dpi
        visible = max(1, int(ax.get_window_extent().height // line_px) - 1)
        self.queue_scroll = min(self.queue_scroll, max(0, len(q_lines) - visible))
        step = line_px / max(ax.get_window_extent().height, 1)
        for k, (text, color) in enumerate(q_lines[self.queue_scroll: self.queue_scroll + visible]):
            ax.text(0, 1 - k * step, text, fontsize=self.LINE_PT, color=color, va="top", family=MONO,
                    transform=ax.transAxes)
        if len(q_lines) > visible:
            last = min(self.queue_scroll + visible, len(q_lines))
            ax.text(1, 1, f"lines {self.queue_scroll + 1}-{last} of {len(q_lines)}  (scroll)", fontsize=7,
                    color=MUTED, va="top", ha="right", family=MONO, transform=ax.transAxes)
        fig.canvas.draw_idle()


def right_half_geometry(screen_w: int, screen_h: int) -> str:
    """Tk geometry for the right half of the screen (of the rightmost 16:9 monitor if several are side by side)."""
    monitor_w = min(screen_w, round(screen_h * 16 / 9))
    x0 = screen_w - monitor_w + monitor_w // 2
    return f"{monitor_w // 2}x{screen_h - 70}+{x0}+0"


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Live monitor for running simulations.")
    parser.add_argument("--once", type=Path, help="save one snapshot to this PNG file instead of opening a window")
    parser.add_argument("--interval", type=float, default=5, help="refresh interval in seconds (default 5)")
    parser.add_argument("--geometry", help="window size and position as WIDTHxHEIGHT+X+Y (default: right half)")
    parser.add_argument("--size", default="9.6x10.1", help="--once only: picture size in inches (WIDTHxHEIGHT)")
    args = parser.parse_args(argv)

    import matplotlib

    matplotlib.use("Agg" if args.once else "TkAgg")
    import matplotlib.pyplot as plt

    width, height = (float(v) for v in args.size.split("x"))
    fig = plt.figure(figsize=(width, height), dpi=100)
    monitor = Monitor(fig)
    if args.once:
        time.sleep(1.0)  # give the CPU load measurement a moment
        monitor.refresh()
        fig.savefig(args.once, facecolor=BG)
        print(f"saved {args.once}")
        return
    window = fig.canvas.manager.window
    fig.canvas.manager.set_window_title("stosslueften monitor")
    window.geometry(args.geometry or right_half_geometry(window.winfo_screenwidth(), window.winfo_screenheight()))
    fig.canvas.mpl_connect("scroll_event", monitor.on_scroll)
    fig.canvas.mpl_connect("resize_event", lambda event: monitor.draw())
    monitor.refresh()
    timer = fig.canvas.new_timer(interval=int(args.interval * 1000))
    timer.add_callback(monitor.refresh)
    timer.start()
    plt.show()


if __name__ == "__main__":
    main()
