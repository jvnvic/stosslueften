"""The sweep runner on the simulation PC: runs what GitHub asks for, and reports back (HPC_PLAN.md).

Normally started by systemd (hpc/setup/install_runner.sh). By hand, from the repository root:
    python -m hpc.runner --home ~/hpc                    # the real thing
    python -m hpc.runner --home /tmp/hpc --fake --once   # one round with fake cases, for testing

Every minute:
1. fetch main; read hpc/control.yaml and hpc/runs/*.yaml (state run | pause | stop, runs, skip, retry)
2. watch running cases: finished, failed (one retry), timed out
3. start cases in free slots: same-wall (method B) cases first; finished cases are adopted, not rerun
4. every few minutes: publish status.json and the dashboard to the hpc-status branch (GitHub Pages),
   and the finished cases' results to the hpc-results branch

The runner keeps its memory in <home>/state.json. When it restarts (crash, update, reboot), it
adopts cases that still run and requeues the others; method B continues from its last save point.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import psutil

from cfd.config import ConfigError, load_config
from geometry.windows import place_windows
from hpc import results, status
from hpc.control import Control, ControlError, RunSpec, parse_control, parse_run
from hpc.gitsync import Branch, GitError, Repo
from hpc.jobs import Jobs, result_state
from hpc.notify import Notifier, repo_slug
from hpc.state import TERMINAL, Case, Run, State

SITE = Path(__file__).parent / "site"


@dataclass
class Settings:
    repo: Path  # the runner's checkout; cases run in repo/cases
    home: Path  # state, code checkouts, the status and results branches
    python: str = sys.executable
    fake: bool = False  # hpc.fake_case instead of cfd.run_case
    tick_s: float = 60
    status_every_s: float = 360  # GitHub Pages builds a branch at most ~10 times per hour
    results_every_s: float = 600
    render: bool = True
    min_free_gb: float = 20
    remote: str | None = None  # push status/results here instead of the checkout's origin (tests)


def log(text: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}", flush=True)


class Runner:
    def __init__(self, settings: Settings, notifier: Notifier | None = None):
        self.s = settings
        settings.home.mkdir(parents=True, exist_ok=True)
        self.repo = Repo(settings.repo)
        self.state_path = settings.home / "state.json"
        self.state = State.load(self.state_path)
        self.jobs = Jobs(settings.repo, settings.python, settings.fake)
        url = settings.remote or self.repo.remote_url()
        self.status_branch = Branch(settings.home / "status", url, "hpc-status", history=False)
        self.results_branch = Branch(settings.home / "results", url, "hpc-results", history=True)
        self.notifier = notifier or Notifier(repo_slug(url))
        self.control, self.specs = Control(), {}
        self.control_error: str | None = None
        self.offline_since: float | None = None
        self.self_paused: str | None = None  # reason, e.g. a full disk
        self.started = time.time()
        self.last_status = self.last_results = 0.0
        self.busy_noted: set[str] = set()
        self.state.event(f"runner started (code {self.repo.head()[:7]})")
        self.recover()

    # --- start-up -------------------------------------------------------------------------

    def recover(self) -> None:
        """Cases that were running when the runner stopped: adopt the live ones, requeue the others."""
        for case in self.state.running():
            if self.jobs.alive(case):
                self.state.event(f"{case.case_id}: still running, adopted")
            else:
                case.status, case.pid = "pending", None
                case.attempts = max(case.attempts - 1, 0)  # interrupted, not failed
                self.state.event(f"{case.case_id}: interrupted (runner or machine restart), requeued")

    # --- 1. control -----------------------------------------------------------------------

    def sync_control(self) -> None:
        if not self.repo.fetch():
            self.offline_since = self.offline_since or time.time()
            return  # keep working with the last known control
        self.offline_since = None
        text = self.repo.show("hpc/control.yaml") or ""
        try:
            control = parse_control(text)
            specs: dict[str, RunSpec] = {}
            for name in self.repo.list_dir("hpc/runs"):
                if name.endswith(".yaml"):
                    spec = parse_run(self.repo.show(f"hpc/runs/{name}") or "", f"hpc/runs/{name}")
                    specs[spec.run_id] = spec
            missing = [r for r in control.runs if r not in specs and r not in self.state.runs]
            if missing:
                raise ControlError(f"hpc/control.yaml: no run file for {missing} in hpc/runs/")
        except ControlError as error:
            if str(error) != self.control_error:
                self.state.event(f"control not applied: {error}")
            self.control_error = str(error)
            return
        self.control_error = None
        self.control, self.specs = control, specs
        for run_id in control.runs:
            if run_id not in self.state.runs:
                self.add_run(specs[run_id])
        runs = json.dumps({k: vars(v) for k, v in sorted(specs.items())}, sort_keys=True)
        digest = hashlib.sha1((text + runs).encode()).hexdigest()
        if digest != self.state.control_hash:
            self.state.control_hash = digest
            self.state.event(f"control: state {control.state}, runs {control.runs or 'none'}")
            self.apply_lists(control)

    def apply_lists(self, control: Control) -> None:
        """skip and retry apply once per change of the control file."""
        for case_id in control.skip:
            case = self.state.cases.get(case_id)
            if case and case.status == "pending":
                case.status = "skipped"
                self.state.event(f"{case_id}: skipped (control)")
        for case_id in control.retry:
            case = self.state.cases.get(case_id)
            if case and case.status == "failed":
                case.status, case.attempts, case.error = "pending", 0, None
                self.state.event(f"{case_id}: queued again (control)")
                self.reopen(case.run_id)

    def reopen(self, run_id: str) -> None:
        run = self.state.runs[run_id]
        if run.finished:
            run.finished = None

    def add_run(self, spec: RunSpec) -> None:
        try:
            commit = self.repo.resolve(spec.code)
            code_dir = self.repo.code_checkout(commit, self.s.home / "code")
        except GitError as error:
            self.control_error = f"run {spec.run_id}: {error}"
            return
        configs = sorted(code_dir.glob(spec.configs))
        cases = []
        try:
            if not configs:
                raise ConfigError(f"no files match {spec.configs}")
            for path in configs:
                cfg = load_config(path)
                place_windows(cfg)
                cases.append(Case(case_id=cfg.case_id, run_id=spec.run_id, config=str(path.relative_to(code_dir)),
                                  layout=cfg.layout, wind_speed_ms=cfg.wind_speed_ms))
        except ConfigError as error:
            self.control_error = f"run {spec.run_id} rejected: {error}"
            self.state.event(self.control_error)
            return
        if not self.s.fake and not self.build_solver(code_dir):
            return
        run = Run(run_id=spec.run_id, code=commit, slots=spec.slots, procs=spec.procs_per_case,
                  retries=spec.retries, timeout_a_min=spec.timeout_a_min, timeout_b_min=spec.timeout_b_min)
        self.state.runs[spec.run_id] = run
        for case in cases:
            self.state.cases.setdefault(case.case_id, case)
        n_b = sum(c.method == "B" for c in cases)
        text = f"run {spec.run_id} added: {len(cases)} cases ({len(cases) - n_b} A, {n_b} B), code {commit[:7]}"
        self.state.event(text)
        run.issue = self.notifier.open_issue(f"Sweep run {spec.run_id}", f"{text}.\n\nEvents follow as comments.")

    def build_solver(self, code_dir: Path) -> bool:
        """Compile our tracer solver from the run's code (quick if it is up to date)."""
        result = subprocess.run(["wmake"], cwd=code_dir / "cfd" / "solvers" / "tracerFoam", capture_output=True, text=True)
        (self.s.home / "wmake.log").write_text(result.stdout + result.stderr)
        if result.returncode != 0:
            self.control_error = f"tracerFoam does not compile from {code_dir.name[:7]}, see {self.s.home}/wmake.log"
            self.state.event(self.control_error)
        return result.returncode == 0

    # --- 2. watch -------------------------------------------------------------------------

    def watch(self) -> None:
        for case in self.state.running():
            run = self.state.runs[case.run_id]
            if self.jobs.alive(case):
                if self.jobs.timed_out(case, run):
                    self.jobs.stop(case)
                    self.fail(case, f"timeout after {(time.time() - case.started) / 60:.0f} min")
                continue
            if self.jobs.succeeded(case):
                self.finish(case)
            else:
                self.fail(case, self.jobs.last_error(case))
        for run in self.state.runs.values():
            cases = self.state.cases_of(run.run_id)
            if not run.finished and cases and all(c.status in TERMINAL for c in cases):
                run.finished = time.time()
                counts = {s: sum(c.status == s for c in cases) for s in TERMINAL}
                hours = (run.finished - run.started) / 3600
                text = f"run {run.run_id} finished after {hours:.1f} h: {counts['done']} done, {counts['failed']} failed, {counts['skipped']} skipped"
                self.state.event(text)
                self.notifier.close(run.issue, text)
                self.last_status = 0  # publish right away

    def finish(self, case: Case, adopted: bool = False) -> None:
        case.status, case.finished, case.pid = "done", time.time(), None
        case.seconds = None if adopted else round(case.finished - case.started, 1)
        case.published = False
        self.state.event(f"{case.case_id}: done" + (" (result already there, adopted)" if adopted else
                                                    f" after {case.seconds / 60:.0f} min"))
        self.package(case, pictures=not adopted)

    def fail(self, case: Case, error: str) -> None:
        run = self.state.runs[case.run_id]
        case.error, case.pid, case.finished = error, None, time.time()
        case.seconds = round(case.finished - case.started, 1) if case.started else None
        if case.attempts <= run.retries:
            case.status = "pending"
            self.state.event(f"{case.case_id}: failed ({error}), will retry")
        else:
            case.status = "failed"
            self.state.event(f"{case.case_id}: failed for good ({error})")
            self.notifier.note(run.issue, f"`{case.case_id}` failed after {case.attempts} attempts: {error}")
            case.published = False
            self.package(case, pictures=False)

    def package(self, case: Case, pictures: bool) -> None:
        run = self.state.runs[case.run_id]
        code_dir = self.s.home / "code" / run.code
        config = code_dir / case.config
        dest = results.package(case, self.jobs.case_dir(case), config, self.results_branch.folder,
                               self.jobs.log_tail(case))
        if pictures and self.s.render and not self.s.fake:
            if results.render_pictures(case, config, self.s.repo, code_dir, self.s.python, dest):
                self.state.latest = {**status.case_result(case, self.jobs.case_dir(case)),
                                     "pictures": str(dest.relative_to(self.results_branch.folder))}

    # --- 3. start -------------------------------------------------------------------------

    def reconcile(self) -> None:
        running = self.state.running()
        if self.control.state == "stop":
            for case in running:
                self.jobs.stop(case)
                case.status, case.pid = "pending", None
                case.attempts = max(case.attempts - 1, 0)
                self.state.event(f"{case.case_id}: stopped (control), requeued")
            return
        if self.control.state != "run":
            return
        active = [r for r in self.control.runs if r in self.state.runs and not self.state.runs[r].finished]
        if not active:
            return
        free = self.state.runs[active[0]].slots - len(running)
        if free <= 0:
            return
        disk_gb = psutil.disk_usage(str(self.s.repo)).free / 2**30
        if disk_gb < self.s.min_free_gb:
            if not self.self_paused:
                self.self_paused = f"only {disk_gb:.0f} GB disk free"
                self.state.event(f"paused itself: {self.self_paused}")
                self.notifier.note(self.state.runs[active[0]].issue, f"runner paused itself: {self.self_paused}")
            return
        self.self_paused = None
        for run_id in active:
            # same-wall (method B) cases take ~10x longer: start them first, so none is left alone at the end
            pending = sorted((c for c in self.state.cases_of(run_id) if c.status == "pending"),
                             key=lambda c: (c.method != "B", c.case_id))
            for case in pending:
                if free <= 0:
                    return
                if result_state(self.jobs.case_dir(case), case.layout) == "complete":
                    self.finish(case, adopted=True)  # e.g. a pilot case run before with cfd.queue
                    continue
                if self.jobs.busy_elsewhere(case):  # e.g. still running in a cfd.queue started by hand
                    if case.case_id not in self.busy_noted:
                        self.busy_noted.add(case.case_id)
                        self.state.event(f"{case.case_id}: another process works on it, waiting")
                    continue
                run = self.state.runs[run_id]
                self.jobs.start(case, run, self.s.home / "code" / run.code)
                self.state.event(f"{case.case_id}: started (method {case.method}, attempt {case.attempts})")
                free -= 1

    # --- 4. publish -------------------------------------------------------------------------

    def runner_state(self) -> str:
        if self.control.state == "stop":
            return "stopped"
        if self.control.state == "pause":
            return "paused"
        if self.self_paused:
            return "self-paused"
        active = [c for c in self.state.cases.values() if c.status in ("pending", "running")
                  and c.run_id in self.control.runs]
        return "running" if active else "idle"

    def status_data(self) -> dict:
        runner = {"state": self.runner_state(), "control": self.control.state, "runs": self.control.runs,
                  "control_error": self.control_error, "message": self.self_paused,
                  "offline_since": self.offline_since, "code": self.repo.head()[:7], "started": round(self.started)}
        return status.build(self.state, self.jobs.cases_dir, runner, self.state.latest,
                            lambda c: self.jobs.log_tail(c, 40))

    def publish(self, force: bool = False) -> None:
        now = time.time()
        if force or now - self.last_status >= self.s.status_every_s:
            folder = self.status_branch.folder
            folder.mkdir(parents=True, exist_ok=True)
            for item in SITE.iterdir():
                if item.is_file() and item.name != "sample_status.json":
                    shutil.copy(item, folder / item.name)
            (folder / ".nojekyll").write_text("")  # serve the files as they are
            latest = self.state.latest
            if latest and latest.get("pictures"):
                (folder / "img").mkdir(exist_ok=True)
                for name in ("setup", "flow"):
                    source = self.results_branch.folder / latest["pictures"] / f"{name}.jpg"
                    if source.exists():
                        shutil.copy(source, folder / "img" / f"latest_{name}.jpg")
            (folder / "status.json").write_text(json.dumps(self.status_data(), separators=(",", ":")))
            if self.status_branch.publish(f"status {time.strftime('%Y-%m-%d %H:%M')}"):
                self.last_status = now
        unpublished = [c for c in self.state.cases.values() if c.status in ("done", "failed") and not c.published]
        if unpublished and (force or now - self.last_results >= self.s.results_every_s):
            if self.results_branch.publish(f"results: {len(unpublished)} case(s)"):
                for case in unpublished:
                    case.published = True
                self.last_results = now
        self.notifier.flush()

    def write_queue_file(self) -> None:
        """The cfd.queue status format, so analysis.monitor on the simulation PC shows the runner too."""
        entries = [{"config": c.config, "case_id": c.case_id, "status": "done" if c.status == "skipped" else c.status,
                    "started": c.started, "seconds": c.seconds, "t90_s": status.case_result(c, self.jobs.case_dir(c))["t90_s"]
                    if c.status == "done" else None, "error": c.error}
                   for c in self.state.cases.values() if c.run_id in self.control.runs]
        queue_dir = self.jobs.cases_dir / "queues"
        queue_dir.mkdir(parents=True, exist_ok=True)
        tmp = queue_dir / "hpc-runner.tmp"
        tmp.write_text(json.dumps({"pid": os.getpid(), "started": self.started, "finished": None,
                                   "procs": None, "entries": entries}))
        os.replace(tmp, queue_dir / "hpc-runner.json")

    # --- remote update ------------------------------------------------------------------------

    def maybe_update(self) -> None:
        """runner_ref: when paused and idle, move to that code version and restart (systemd starts us again)."""
        if self.control.state != "pause" or self.state.running() or self.s.fake:
            return
        try:
            target = self.repo.resolve(self.control.runner_ref)
        except GitError:
            return
        if target == self.repo.head():
            return
        old = self.repo.show("requirements.txt", "HEAD")
        if self.repo.show("requirements.txt", target) != old:
            if self.control_error != "runner update needs a manual pip install (requirements.txt changed)":
                self.control_error = "runner update needs a manual pip install (requirements.txt changed)"
                self.state.event(self.control_error)
            return
        if self.repo.update(target):
            self.state.event(f"runner updated to {target[:7]}, restarting")
            self.publish(force=True)
            self.state.save(self.state_path)
            raise SystemExit(0)

    # --- the loop ---------------------------------------------------------------------------

    def tick(self) -> None:
        for step in (self.sync_control, self.watch, self.reconcile, self.maybe_update, self.publish,
                     self.write_queue_file):
            try:
                step()
            except SystemExit:
                raise
            except Exception:  # noqa: BLE001 - one broken step must never stop the runner
                log(f"error in {step.__name__}:\n{traceback.format_exc()}")
                self.state.event(f"internal error in {step.__name__} (see the runner log)")
        self.state.save(self.state_path)

    def loop(self) -> None:
        while True:
            started = time.time()
            self.tick()
            time.sleep(max(self.s.tick_s - (time.time() - started), 1))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Run the sweep that hpc/control.yaml asks for.")
    parser.add_argument("--home", type=Path, default=Path.home() / "hpc", help="state, code checkouts, branches")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="the runner's repository checkout")
    parser.add_argument("--fake", action="store_true", help="fake cases (seconds, no OpenFOAM), for testing")
    parser.add_argument("--once", action="store_true", help="one round, then exit")
    parser.add_argument("--no-render", action="store_true", help="no pictures of finished cases")
    parser.add_argument("--remote", help="push status and results here instead of origin (testing)")
    args = parser.parse_args(argv)
    if not args.fake and "WM_PROJECT_DIR" not in os.environ:
        raise SystemExit("OpenFOAM is not loaded: source hpc/setup/foam_env.sh first")
    settings = Settings(repo=args.repo.resolve(), home=args.home.expanduser().resolve(), fake=args.fake,
                        render=not args.no_render, remote=args.remote)
    runner = Runner(settings)
    log(f"runner started: repo {settings.repo}, home {settings.home}{' (fake cases)' if args.fake else ''}")
    if args.once:
        runner.tick()
        runner.publish(force=True)
        runner.state.save(runner.state_path)
    else:
        runner.loop()


if __name__ == "__main__":
    main()
