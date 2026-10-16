"""Change hpc/control.yaml from the "Runner control" workflow (.github/workflows/runner-control.yml).

The dashboard's buttons start that workflow; it can also be started by hand in the GitHub app or on
github.com (Actions -> Runner control -> Run workflow). Usage, from the repository root:
    python -m hpc.control_edit --state pause
    python -m hpc.control_edit --state run --runs "train-v1 test-v1" --retry "train-v1_017"

--runs: the runs in this order; empty keeps the current ones, "-" removes all.
--retry / --skip: case ids; they replace the lists, so leaving them empty clears them.
Every value is checked before the file is written; a wrong value stops with a clear message.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from hpc.control import STATES, Control, ControlError, parse_control

CONTROL = Path("hpc/control.yaml")
RUNS = Path("hpc/runs")
NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _names(text: str, what: str) -> list[str]:
    names = [n for n in re.split(r"[\s,]+", text.strip()) if n]
    bad = [n for n in names if not NAME.match(n)]
    if bad:
        raise ControlError(f"{what}: {bad} are not valid names (letters, digits, _ . - only)")
    return names


def render(control: Control) -> str:
    def items(values):
        return "[" + ", ".join(values) + "]"

    return f"""# What the sweep runner on the simulation PC should do (hpc/README.md). Change it with the dashboard's
# buttons, by hand in the GitHub app (Actions -> Runner control), or edit and push it.
state: {control.state:<12} # run | pause (finish running cases, start no new ones) | stop (abort running cases, requeue them)
runs: {items(control.runs):<13} # runs to work on, in this order, e.g. [train-v1, test-v1]; each needs hpc/runs/<run>.yaml
skip: {items(control.skip):<13} # case ids to leave out, e.g. [train-v1_017]
retry: {items(control.retry):<12} # failed case ids to run again
runner_ref: {control.runner_ref:<7} # runner code version; applied when paused and no case runs
"""


def edit(text: str, state: str, runs: str, retry: str, skip: str, known_runs: set[str]) -> Control:
    """The new control: the given values, the rest kept from the current file."""
    current = parse_control(text)
    if state not in STATES:
        raise ControlError(f"state must be one of {STATES}, not {state!r}")
    if runs.strip() == "-":
        new_runs = []
    elif runs.strip():
        new_runs = _names(runs, "runs")
    else:
        new_runs = current.runs
    unknown = [r for r in new_runs if r not in known_runs]
    if unknown:
        raise ControlError(f"no run file hpc/runs/<run>.yaml for {unknown}; known runs: {sorted(known_runs)}")
    return Control(state=state, runs=new_runs, skip=_names(skip, "skip"), retry=_names(retry, "retry"),
                   runner_ref=current.runner_ref)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Change hpc/control.yaml (used by the Runner control workflow).")
    parser.add_argument("--state", required=True, choices=STATES)
    parser.add_argument("--runs", default="", help='runs in order, e.g. "train-v1 test-v1"; empty: keep; "-": none')
    parser.add_argument("--retry", default="", help="failed case ids to run again")
    parser.add_argument("--skip", default="", help="case ids to leave out")
    args = parser.parse_args(argv)
    known = {p.stem for p in RUNS.glob("*.yaml")}
    try:
        control = edit(CONTROL.read_text() if CONTROL.exists() else "", args.state, args.runs, args.retry,
                       args.skip, known)
    except ControlError as error:
        raise SystemExit(f"Not changed: {error}")
    CONTROL.write_text(render(control))
    parse_control(CONTROL.read_text())  # what the runner will read must be valid
    print(f"state {control.state}, runs {control.runs}, retry {control.retry}, skip {control.skip}")


if __name__ == "__main__":
    main()
