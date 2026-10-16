"""The runner's memory: every case of every run, saved atomically in <home>/state.json.

A case goes pending -> running -> done | failed, or pending -> skipped. An interrupted case (stop,
reboot) goes back to pending without counting as a failed attempt.
"""

from __future__ import annotations

import dataclasses
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

TERMINAL = ("done", "failed", "skipped")
MAX_EVENTS = 200


@dataclass
class Case:
    case_id: str
    run_id: str
    config: str  # path relative to the run's code checkout
    layout: str
    wind_speed_ms: float | None = None  # for the dashboard's results chart
    status: str = "pending"
    attempts: int = 0  # starts that ended in a failure or are running now
    pid: int | None = None
    pid_started: float | None = None  # process start time, to recognise the same process after a restart
    started: float | None = None
    finished: float | None = None
    seconds: float | None = None
    error: str | None = None
    published: bool = False  # results pushed to the hpc-results branch

    @property
    def method(self) -> str:
        """A or B: B for same-wall cases (PLAN.md §5, decision M1)."""
        return "B" if self.layout == "same_wall" else "A"


@dataclass
class Run:
    run_id: str
    code: str  # commit of the run's code; all its cases use it
    slots: int
    procs: int
    retries: int
    timeout_a_min: float
    timeout_b_min: float
    started: float = field(default_factory=time.time)
    finished: float | None = None
    issue: int | None = None  # GitHub issue for the run's notifications


@dataclass
class State:
    runs: dict[str, Run] = field(default_factory=dict)
    cases: dict[str, Case] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    control_hash: str | None = None  # last applied control file, so skip/retry lists apply once per change
    latest: dict | None = None  # the last finished case with pictures, for the dashboard
    control_lists: dict = field(default_factory=lambda: {"retry": [], "skip": []})  # last applied retry/skip

    def event(self, text: str) -> None:
        self.events.append({"t": round(time.time()), "text": text})
        del self.events[:-MAX_EVENTS]

    def cases_of(self, run_id: str) -> list[Case]:
        return [c for c in self.cases.values() if c.run_id == run_id]

    def running(self) -> list[Case]:
        return [c for c in self.cases.values() if c.status == "running"]

    def save(self, path: Path) -> None:
        """Write in one step (temporary file + rename), so a crash never leaves half a file."""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(dataclasses.asdict(self), indent=1))
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> "State":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        return cls(runs={k: Run(**v) for k, v in data["runs"].items()},
                   cases={k: Case(**v) for k, v in data["cases"].items()},
                   events=data.get("events", []), control_hash=data.get("control_hash"), latest=data.get("latest"),
                   control_lists=data.get("control_lists", {"retry": [], "skip": []}))
