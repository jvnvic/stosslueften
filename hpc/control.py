"""What we want the runner to do: hpc/control.yaml and the run files hpc/runs/<run_id>.yaml on main.

The control file is declarative: it describes the wanted state, not a one-off command, so a
missed poll or a restart of the runner cannot lose a command (HPC_PLAN.md §4). The runner only
reads values from these files and never executes anything from them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

STATES = ("run", "pause", "stop")


class ControlError(ValueError):
    """A control or run file has a mistake; the message says which and how to fix it."""


@dataclass
class Control:
    state: str = "pause"  # run | pause (finish running cases, start no new ones) | stop (abort and requeue)
    runs: list[str] = field(default_factory=list)  # order = priority; runs not listed are not started
    skip: list[str] = field(default_factory=list)  # case ids to leave out
    retry: list[str] = field(default_factory=list)  # failed case ids to run again
    runner_ref: str = "main"  # runner code version, applied only when paused and idle


@dataclass
class RunSpec:
    run_id: str
    configs: str  # glob relative to the repository root, e.g. configs/sweep/train-v1/train-v1_*.yaml
    code: str = "main"  # git ref; resolved to a commit when the run starts
    slots: int = 2  # cases at the same time (HPC_PLAN.md §8: 2 x 4 cores is best on the simulation PC)
    procs_per_case: int = 4
    retries: int = 1
    timeout_a_min: float = 45
    timeout_b_min: float = 300


def _mapping(text: str, name: str) -> dict:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as error:
        raise ControlError(f"{name}: not valid YAML ({error})")
    if not isinstance(data, dict):
        raise ControlError(f"{name}: expected 'key: value' lines")
    return data


def _check_keys(data: dict, allowed: set[str], name: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ControlError(f"{name}: unknown keys {sorted(unknown)} (allowed: {sorted(allowed)})")


def _list_of_names(value, key: str, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ControlError(f"{name}: {key} must be a list of names, e.g. [train-v1]")
    return value


def parse_control(text: str, name: str = "hpc/control.yaml") -> Control:
    data = _mapping(text, name)
    _check_keys(data, {"state", "runs", "skip", "retry", "runner_ref"}, name)
    state = data.get("state", "pause")
    if state not in STATES:
        raise ControlError(f"{name}: state must be one of {STATES}, not {state!r}")
    return Control(state=state, runs=_list_of_names(data.get("runs"), "runs", name),
                   skip=_list_of_names(data.get("skip"), "skip", name),
                   retry=_list_of_names(data.get("retry"), "retry", name),
                   runner_ref=str(data.get("runner_ref", "main")))


def parse_run(text: str, name: str) -> RunSpec:
    data = _mapping(text, name)
    allowed = {f.name for f in RunSpec.__dataclass_fields__.values()}
    _check_keys(data, allowed, name)
    for key in ("run_id", "configs"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ControlError(f"{name}: {key} is required")
    spec = RunSpec(**data)
    if not (1 <= spec.slots <= 8 and 1 <= spec.procs_per_case <= 16 and 0 <= spec.retries <= 5):
        raise ControlError(f"{name}: slots 1-8, procs_per_case 1-16 and retries 0-5 please")
    if spec.timeout_a_min <= 0 or spec.timeout_b_min <= 0:
        raise ControlError(f"{name}: timeouts must be > 0 minutes")
    if not spec.configs.endswith(".yaml") or spec.configs.startswith(("/", "..")):
        raise ControlError(f"{name}: configs must be a pattern of .yaml files inside the repository")
    return spec
