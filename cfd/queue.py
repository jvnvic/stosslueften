"""Run several cases one after another, with a status file that the monitor shows as a queue.

Usage, from the repository root with the venv active and OpenFOAM loaded. Start it
detached so that it survives closing the terminal or editor:
    setsid nohup python -m cfd.queue configs/benchmark/snappy_*.yaml > cases/queue.out 2>&1 &
    python -m cfd.queue --procs 4 configs/a.yaml configs/b.yaml    # --procs is passed on to run_case
    python -m cfd.queue --transient --procs 4 configs/a.yaml        # comparison runs (steady flow first if missing)

Each queue writes its status to cases/queues/<start time>.json. The monitor
(python -m analysis.monitor) reads all of them, so several queues can run side by
side, for example two queues with --procs 4 each.

If a queue was interrupted (reboot, power cut), continue it; the case that was
running is started again from its beginning, finished cases are kept:
    setsid nohup python -m cfd.queue --resume cases/queues/<name>.json > cases/queue.out 2>&1 &
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from cfd.config import ConfigError, load_config

CASES = Path("cases")
QUEUE_DIR = CASES / "queues"


def write_state(path: Path, state: dict) -> None:
    """Write the status file in one step, so a reader never sees half a file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, path)


def _result(case_id: str, transient: bool) -> float | None:
    """t90 of the case: of method B for --transient queues and same-wall cases, else of method A."""
    summary = CASES / case_id / "summary.json"
    try:
        summary = json.loads(summary.read_text())
        use_b = transient or summary.get("method") == "B"
        return (summary.get("transient", {}) if use_b else summary).get("t90_s")
    except (OSError, ValueError):
        return None


def _alive(pid: int) -> bool:
    """True if a queue process with this PID is still running."""
    try:
        import psutil

        return "cfd.queue" in " ".join(psutil.Process(pid).cmdline())
    except Exception:  # noqa: BLE001 - no psutil, no such process, no access: treat as not running
        return False


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Run several cases one after another.")
    parser.add_argument("configs", nargs="*", type=Path, help="case YAML files, run in this order")
    parser.add_argument("--procs", type=int, help="CPU cores per case (passed on to run_case)")
    parser.add_argument("--transient", action="store_true",
                        help="comparison runs with time-varying flow (run_case --transient); "
                             "the steady flow is computed first for cases that do not have it yet")
    parser.add_argument("--resume", type=Path, help="continue an interrupted queue (its cases/queues/*.json file)")
    args = parser.parse_args(argv)
    if bool(args.configs) == bool(args.resume):
        raise SystemExit("give either config files or --resume <queue file>")
    if "WM_PROJECT_DIR" not in os.environ:
        raise SystemExit("OpenFOAM is not loaded: run `of` first, or source its etc/bashrc "
                         "(Arch AUR: /opt/OpenFOAM/OpenFOAM-v2606/etc/bashrc, "
                         "Ubuntu package: /usr/lib/openfoam/openfoam2606/etc/bashrc)")

    if args.resume:
        path = args.resume
        state = json.loads(path.read_text())
        if _alive(state["pid"]):
            raise SystemExit(f"queue {path.name} is still running (pid {state['pid']})")
        for entry in state["entries"]:
            if entry["status"] == "running":  # interrupted: run it again from the start
                entry["status"], entry["started"] = "pending", None
        state["pid"], state["finished"] = os.getpid(), None
    else:
        try:  # check every config before starting, so a typo does not stop the queue halfway
            case_ids = [load_config(config).case_id for config in args.configs]
        except ConfigError as error:
            raise SystemExit(f"Invalid configuration: {error}")
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        while True:  # claim a free file name; two queues started in the same second get different ones
            path = QUEUE_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
            try:
                path.open("x").close()
                break
            except FileExistsError:
                time.sleep(1)
        state = {
            "pid": os.getpid(),
            "started": time.time(),
            "finished": None,
            "procs": args.procs,
            "transient": args.transient,
            "entries": [
                {"config": str(config), "case_id": case_id, "status": "pending", "started": None,
                 "seconds": None, "t90_s": None, "error": None}
                for config, case_id in zip(args.configs, case_ids)
            ],
        }
    write_state(path, state)
    procs = args.procs or state.get("procs")
    transient = state.get("transient", False)
    run_case = [sys.executable, "-m", "cfd.run_case"] + (["--procs", str(procs)] if procs else [])
    for entry in state["entries"]:
        if entry["status"] != "pending":
            continue
        entry["status"], entry["started"] = "running", time.time()
        write_state(path, state)
        # a normal run: steady flow + tracer, and for same-wall cases also the time-varying stage
        commands = [run_case + ["--config", entry["config"]]]
        if transient:  # comparison run: the steady flow first if missing, then the time-varying stage
            has_flow = (CASES / entry["case_id"] / "summary.json").exists()
            steady = [] if has_flow else [run_case + ["--config", entry["config"], "--steady-only"]]
            commands = steady + [run_case + ["--config", entry["config"], "--transient"]]
        log = CASES / f"{entry['case_id']}.{'transient.' if transient else ''}queue.log"
        with log.open("w") as out:
            for command in commands:
                result = subprocess.run(command, stdout=out, stderr=subprocess.STDOUT)
                if result.returncode != 0:
                    break
        entry["seconds"] = round(time.time() - entry["started"], 1)
        if result.returncode == 0:
            entry["status"], entry["t90_s"] = "done", _result(entry["case_id"], transient)
        else:
            lines = log.read_text(errors="replace").strip().splitlines()
            entry["status"], entry["error"] = "failed", (lines[-1] if lines else f"exit code {result.returncode}")
        write_state(path, state)
        print(f"{entry['status']:>7}  {entry['config']}  ({entry['seconds']:.0f} s)", flush=True)
    state["finished"] = time.time()
    write_state(path, state)


if __name__ == "__main__":
    main()
