"""Short summary of the runner's memory (~/hpc/state.json), for a terminal on the simulation PC.

Usage, from the repository root (~/stosslueften):
    python -m hpc.show              # once
    python -m hpc.show --watch      # refresh every 10 s; Ctrl+C to leave

Shows the cases per status and run, each running case with its stage and progress, failures, and
the latest events. The runner rewrites the file every minute.
"""

from __future__ import annotations

import argparse
import time
from collections import Counter
from pathlib import Path

from hpc.state import State
from hpc.status import case_progress

STATUSES = ("done", "running", "pending", "failed", "skipped")


def _duration(seconds: float) -> str:
    seconds = max(seconds, 0)
    if seconds >= 3600:
        return f"{int(seconds // 3600)} h {int(seconds % 3600 // 60):02d} min"
    return f"{int(seconds // 60)} min"


def summary(state: State, cases_dir: Path, updated: float, n_events: int = 15, now: float | None = None) -> str:
    now = now or time.time()
    lines = [f"state file updated {_duration(now - updated)} ago ({time.strftime('%d.%m. %H:%M', time.localtime(updated))})", ""]
    if not state.runs:
        lines.append("no run started yet (hpc/control.yaml: state, runs)")
    for run_id, run in state.runs.items():
        counts = Counter(c.status for c in state.cases_of(run_id))
        text = "  ".join(f"{s} {counts[s]}" for s in STATUSES if counts[s])
        finished = f"  finished {time.strftime('%d.%m. %H:%M', time.localtime(run.finished))}" if run.finished else ""
        lines.append(f"{run_id:<12} {sum(counts.values()):>4} cases   {text}{finished}")
    running = sorted(state.running(), key=lambda c: c.started or 0)
    if running:
        lines.append("")
    for case in running:
        progress = case_progress(cases_dir / case.case_id)
        share = f"{progress['progress']:.0%}" if progress["progress"] is not None else ""
        attempt = f"  attempt {case.attempts}" if case.attempts > 1 else ""
        lines.append(f"running  {case.case_id:<16} {case.layout:<15} {case.method}  {progress['stage']:<9} {share:>4}  "
                     f"{_duration(now - case.started) if case.started else ''}{attempt}")
    problems = [c for c in state.cases.values() if c.error and c.status in ("failed", "pending")]
    if problems:
        lines.append("")
    for case in problems:
        what = "FAILED" if case.status == "failed" else "retry "
        lines.append(f"{what}   {case.case_id:<16} {case.error}")
    lines.append("")
    for event in state.events[-n_events:]:
        lines.append(f"{time.strftime('%d.%m. %H:%M', time.localtime(event['t']))}  {event['text']}")
    return "\n".join(lines)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Short summary of the sweep runner's state.")
    parser.add_argument("--home", type=Path, default=Path.home() / "hpc", help="the runner's home folder")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository checkout (its cases/ folder)")
    parser.add_argument("--events", type=int, default=15, help="number of latest events to show")
    parser.add_argument("--watch", type=float, nargs="?", const=10, help="refresh every N seconds (default 10)")
    args = parser.parse_args(argv)
    path = args.home.expanduser() / "state.json"
    while True:
        if path.exists():
            text = summary(State.load(path), args.repo / "cases", path.stat().st_mtime, args.events)
        else:
            text = f"{path} does not exist yet: is the runner installed (bash hpc/setup/install_runner.sh)?"
        if args.watch:
            print("\033[H\033[J" + text, flush=True)  # clear the screen, then print
            time.sleep(args.watch)
        else:
            print(text)
            return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
