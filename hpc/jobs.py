"""Starting, watching and stopping cases.

Each case is `python -P -m cfd.run_case --config … --procs N`, started in its own process group
(so stopping it also stops its OpenFOAM MPI processes) with the run's pinned code on PYTHONPATH.
The working folder is the runner's repository checkout, so all results land in <repo>/cases/, the
same folder that `cfd.queue` uses: cases finished there before (e.g. a pilot) are recognised.

What to run is decided from the case's files, so it also works after a reboot:
- complete result                 -> nothing to run (adopted as done)
- method A done, method B missing -> `--transient`, with `--resume` if B has a save point
- otherwise                       -> the whole case
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import psutil

from hpc.state import Case, Run


def result_state(case_dir: Path, layout: str) -> str:
    """'complete', 'steady' (method A done, but method B of a same-wall case missing) or 'none'."""
    try:
        summary = json.loads((case_dir / "summary.json").read_text())
    except (OSError, ValueError):
        return "none"
    if "tau_s" not in summary:
        return "none"
    if layout == "same_wall" and "transient" not in summary:
        return "steady"
    return "complete"


def has_save_point(transient_dir: Path) -> bool:
    """True if method B wrote at least one complete save point (a time folder > 0 with U)."""
    processor = transient_dir / "processor0"
    if not processor.is_dir():
        return False
    for folder in processor.iterdir():
        try:
            if float(folder.name) > 0 and (folder / "U").exists():
                return True
        except ValueError:
            continue
    return False


class Jobs:
    def __init__(self, repo: Path, python: str, fake: bool = False):
        self.repo = repo  # working folder of the cases; results go to repo/cases/<case_id>
        self.cases_dir = repo / "cases"
        self.python = python
        self.module = "hpc.fake_case" if fake else "cfd.run_case"
        self.procs: dict[str, subprocess.Popen] = {}  # cases started by this runner process

    def case_dir(self, case: Case) -> Path:
        return self.cases_dir / case.case_id

    def log_path(self, case: Case) -> Path:
        return self.cases_dir / f"{case.case_id}.runner.log"

    def command(self, case: Case, run: Run, code_dir: Path) -> list[str]:
        cmd = [self.python, "-P", "-m", self.module, "--config", str(code_dir / case.config), "--procs", str(run.procs)]
        if result_state(self.case_dir(case), case.layout) == "steady":
            transient = self.case_dir(case) / "transient"
            cmd += ["--transient"] + (["--resume"] if has_save_point(transient) else [])
        return cmd

    def start(self, case: Case, run: Run, code_dir: Path) -> None:
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        cmd = self.command(case, run, code_dir)
        env = {**os.environ, "PYTHONPATH": str(code_dir), "PYTHONUNBUFFERED": "1"}
        with self.log_path(case).open("a") as log:
            log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} attempt {case.attempts + 1}: {' '.join(cmd[3:])}\n")
            log.flush()
            proc = subprocess.Popen(cmd, cwd=self.repo, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        self.procs[case.case_id] = proc
        case.status, case.pid, case.started = "running", proc.pid, time.time()
        case.pid_started = psutil.Process(proc.pid).create_time()
        case.attempts += 1
        case.error = None

    def alive(self, case: Case) -> bool:
        proc = self.procs.get(case.case_id)
        if proc is not None:
            return proc.poll() is None  # also collects a finished child, so it does not linger as a zombie
        try:  # a case adopted after a runner restart: same PID *and* same start time
            p = psutil.Process(case.pid)
            return abs(p.create_time() - (case.pid_started or 0)) < 1 and p.status() != psutil.STATUS_ZOMBIE
        except (psutil.Error, TypeError):
            return False

    def succeeded(self, case: Case) -> bool:
        """After the process ended: the exit code (if known) and the result files say it worked."""
        proc = self.procs.pop(case.case_id, None)
        code_ok = proc is None or proc.returncode == 0
        return code_ok and result_state(self.case_dir(case), case.layout) == "complete"

    def stop(self, case: Case, grace_s: float = 20) -> None:
        """Stop the case and everything it started (its process group)."""
        if case.pid is None or not self.alive(case):
            self.procs.pop(case.case_id, None)
            return
        try:
            os.killpg(case.pid, signal.SIGTERM)
        except OSError:
            pass
        end = time.time() + grace_s
        while time.time() < end and self.alive(case):
            time.sleep(0.5)
        if self.alive(case):
            try:
                os.killpg(case.pid, signal.SIGKILL)
            except OSError:
                pass
            time.sleep(0.5)
            self.alive(case)  # collect it
        self.procs.pop(case.case_id, None)

    def busy_elsewhere(self, case: Case) -> bool:
        """True if another process works in this case's folder, e.g. a cfd.queue started by hand."""
        folder = str(self.case_dir(case).resolve())
        for p in psutil.process_iter():
            try:
                cwd = p.cwd()
            except psutil.Error:
                continue
            if cwd == folder or cwd.startswith(folder + os.sep):
                return True
        return False

    def timed_out(self, case: Case, run: Run) -> bool:
        limit = run.timeout_a_min + (run.timeout_b_min if case.method == "B" else 0)
        return case.started is not None and time.time() - case.started > limit * 60

    def log_tail(self, case: Case, n: int = 50) -> str:
        try:
            lines = self.log_path(case).read_text(errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(lines[-n:])

    def last_error(self, case: Case) -> str:
        lines = [line for line in self.log_tail(case, 30).splitlines() if line.strip()]
        return lines[-1][:300] if lines else "no output"
