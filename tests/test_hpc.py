"""The HPC runner (HPC_PLAN.md §11), tested without OpenFOAM and without GitHub:
fake cases (hpc.fake_case, seconds each) and a local bare repository in place of GitHub."""

import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from hpc import status
from hpc.control import ControlError, parse_control, parse_run
from hpc.gitsync import Branch, git
from hpc.jobs import has_save_point, result_state
from hpc.notify import Notifier, repo_slug
from hpc.runner import Runner, Settings
from hpc.state import Case, State

REPO = Path(__file__).parents[1]


# --- small parts ----------------------------------------------------------------------------

def test_control_file_is_checked_with_clear_messages():
    control = parse_control("state: run\nruns: [train-v1]\nretry: [train-v1_007]\n")
    assert (control.state, control.runs, control.retry) == ("run", ["train-v1"], ["train-v1_007"])
    assert parse_control("").state == "pause"  # no file: do nothing
    with pytest.raises(ControlError, match="state must be one of"):
        parse_control("state: go\n")
    with pytest.raises(ControlError, match="unknown keys"):
        parse_control("state: run\nrunz: [a]\n")
    spec = parse_run("run_id: r\nconfigs: configs/sweep/r/r_*.yaml\nslots: 3\n", "hpc/runs/r.yaml")
    assert (spec.slots, spec.procs_per_case, spec.code) == (3, 4, "main")
    with pytest.raises(ControlError, match="inside the repository"):
        parse_run("run_id: r\nconfigs: /etc/*.yaml\n", "x")


def test_result_state_and_save_points(tmp_path):
    case = tmp_path / "c"
    case.mkdir()
    assert result_state(case, "opposite_walls") == "none"
    (case / "summary.json").write_text(json.dumps({"tau_s": 30.0}))
    assert result_state(case, "opposite_walls") == "complete"
    assert result_state(case, "same_wall") == "steady"  # method B missing
    assert not has_save_point(case / "transient")
    (case / "transient" / "processor0" / "0").mkdir(parents=True)
    assert not has_save_point(case / "transient")  # only the start
    (case / "transient" / "processor0" / "30").mkdir()
    (case / "transient" / "processor0" / "30" / "U").write_text("")
    assert has_save_point(case / "transient")


def test_status_has_no_nan_and_reads_progress(tmp_path):
    assert status.clean({"a": [math.nan, 1.0], "b": math.inf}) == {"a": [None, 1.0], "b": None}
    case = tmp_path / "c"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("endTime         2000;\n")
    (case / "log.simpleFoam").write_text("Time = 499\n\nTime = 500\n")
    progress = status.case_progress(case)
    assert progress["stage"] == "flow" and progress["progress"] == pytest.approx(0.25)


def test_notifications_are_batched(tmp_path):
    token = tmp_path / "token"
    token.write_text("secret\n")
    sent = []
    notifier = Notifier("o/r", token, send=lambda method, path, body: sent.append((method, path, body)) or {"number": 5})
    issue = notifier.open_issue("Sweep run t", "hello")
    notifier.note(issue, "a")
    notifier.note(issue, "b")
    notifier.flush()
    notifier.note(issue, "c")
    notifier.flush()  # within 30 minutes: waits
    assert [p for _, p, _ in sent] == ["/issues", "/issues/5/comments"]
    assert "a" in sent[1][2]["body"] and "b" in sent[1][2]["body"]
    notifier.close(issue, "finished")  # forced: sends the waiting lines, then closes
    assert sent[-1] == ("PATCH", "/issues/5", {"state": "closed"}) and "c" in sent[-2][2]["body"]
    assert repo_slug("github-stosslueften:jvnvic/stosslueften.git") == "jvnvic/stosslueften"
    assert not Notifier("o/r", tmp_path / "missing").enabled


def test_status_branch_always_has_one_commit(tmp_path):
    remote = tmp_path / "remote.git"
    git("init", "--quiet", "--bare", str(remote), cwd=tmp_path)
    branch = Branch(tmp_path / "status", str(remote), "hpc-status", history=False)
    for k in range(3):
        branch.folder.mkdir(exist_ok=True)
        (branch.folder / "status.json").write_text(json.dumps({"k": k}))
        assert branch.publish(f"status {k}")
    assert git("rev-list", "--count", "hpc-status", cwd=remote).strip() == "1"
    assert json.loads(git("show", "hpc-status:status.json", cwd=remote)) == {"k": 2}
    offline = Branch(tmp_path / "offline", str(tmp_path / "missing.git"), "hpc-results", history=True)
    assert offline.publish("x") is False  # no exception, just "not now"


# --- the whole runner with fake cases ---------------------------------------------------------

def _commit_all(repo: Path, message: str) -> None:
    git("add", "-A", cwd=repo)
    git("commit", "--quiet", "-m", message, cwd=repo)
    git("push", "--quiet", "origin", "main", cwd=repo)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A 'GitHub' (bare repo), the runner's checkout of it with the current code and 6 cases, and a notifier."""
    remote = tmp_path / "remote.git"
    git("init", "--quiet", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    repo = tmp_path / "repo"
    git("clone", "--quiet", str(remote), str(repo), cwd=tmp_path)
    git("config", "user.name", "test", cwd=repo)
    git("config", "user.email", "t@t", cwd=repo)
    git("symbolic-ref", "HEAD", "refs/heads/main", cwd=repo)
    ignore = shutil.ignore_patterns("__pycache__", "linux64*", "*.pyc")
    for package in ("cfd", "geometry", "hpc", "analysis", "sweeps"):
        shutil.copytree(REPO / package, repo / package, ignore=ignore)
    (repo / "configs").mkdir()
    shutil.copy(REPO / "configs" / "default.yaml", repo / "configs" / "default.yaml")
    shutil.copy(REPO / "requirements.txt", repo / "requirements.txt")
    run_dir = repo / "configs" / "sweep" / "t"
    run_dir.mkdir(parents=True)
    spec = yaml.safe_load((REPO / "configs" / "sweep" / "train-v1" / "spec.yaml").read_text())
    spec.update(run_id="t", n_cases=6, base_config="configs/default.yaml")
    (run_dir / "spec.yaml").write_text(yaml.safe_dump(spec))
    subprocess.run([sys.executable, "-m", "sweeps.generate", str(run_dir / "spec.yaml"), "--no-plot"], cwd=repo,
                   check=True, capture_output=True)
    (repo / "hpc" / "runs").mkdir(exist_ok=True)
    (repo / "hpc" / "runs" / "t.yaml").write_text("run_id: t\nconfigs: configs/sweep/t/t_*.yaml\nslots: 2\nprocs_per_case: 1\n")
    (repo / "hpc" / "control.yaml").write_text("state: run\nruns: [t]\n")
    _commit_all(repo, "test setup")
    monkeypatch.setenv("HPC_FAKE_SECONDS", "0.2")
    for name in ("HPC_FAKE_FAIL", "HPC_FAKE_HANG"):
        monkeypatch.delenv(name, raising=False)
    token = tmp_path / "token"
    token.write_text("x")
    sent = []

    def make_runner():
        notifier = Notifier("o/r", token, send=lambda m, p, b: sent.append((m, p, b)) or {"number": 1})
        settings = Settings(repo=repo, home=tmp_path / "home", fake=True, tick_s=0, status_every_s=0,
                            results_every_s=0, render=False, remote=str(remote), min_free_gb=0)
        return Runner(settings, notifier)

    return {"repo": repo, "remote": remote, "make_runner": make_runner, "sent": sent}


def _run_until(runner, condition, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        runner.tick()
        if condition():
            return
        time.sleep(0.2)
    raise AssertionError("timed out; events: " + json.dumps(runner.state.events[-10:], indent=1))


def _statuses(runner):
    return {c.case_id: c.status for c in runner.state.cases.values()}


def test_runner_runs_a_whole_run_and_publishes(world):
    runner = world["make_runner"]()
    _run_until(runner, lambda: runner.state.runs.get("t") and runner.state.runs["t"].finished)
    assert set(_statuses(runner).values()) == {"done"}
    same_wall = [c for c in runner.state.cases.values() if c.layout == "same_wall"]
    assert same_wall and all(c.method == "B" for c in same_wall)
    runner.publish(force=True)
    remote = world["remote"]
    published = json.loads(git("show", "hpc-status:status.json", cwd=remote))
    assert published["runs"][0]["counts"]["done"] == 6 and len(published["results"]) == 6
    assert "index.html" in git("ls-tree", "--name-only", "hpc-status", cwd=remote)
    assert git("rev-list", "--count", "hpc-status", cwd=remote).strip() == "1"
    files = git("ls-tree", "-r", "--name-only", "hpc-results", cwd=remote).split()
    assert "results/t/t_001/summary.json" in files and "results/t/t_001/config.yaml" in files
    calls = [(m, p) for m, p, _ in world["sent"]]
    assert ("POST", "/issues") in calls and ("PATCH", "/issues/1") in calls  # run issue opened and closed
    queue_file = json.loads((world["repo"] / "cases" / "queues" / "hpc-runner.json").read_text())
    assert len(queue_file["entries"]) == 6  # analysis.monitor shows the runner like a queue


def test_failed_case_is_retried_once_then_reported(world, monkeypatch):
    monkeypatch.setenv("HPC_FAKE_FAIL", "t_002")
    runner = world["make_runner"]()
    _run_until(runner, lambda: runner.state.runs.get("t") and runner.state.runs["t"].finished)
    case = runner.state.cases["t_002"]
    assert (case.status, case.attempts) == ("failed", 2) and "fake failure" in case.error
    data = runner.status_data()
    assert data["failures"][0]["case_id"] == "t_002" and "fake failure" in data["failures"][0]["log_tail"]


def test_pause_starts_nothing_and_stop_requeues(world, monkeypatch):
    repo = world["repo"]
    (repo / "hpc" / "control.yaml").write_text("state: pause\nruns: [t]\n")
    _commit_all(repo, "pause")
    runner = world["make_runner"]()
    runner.tick()
    assert set(_statuses(runner).values()) == {"pending"} and runner.runner_state() == "paused"

    monkeypatch.setenv("HPC_FAKE_HANG", "t_001,t_004")  # the two same-wall cases start first and never end
    (repo / "hpc" / "control.yaml").write_text("state: run\nruns: [t]\n")
    _commit_all(repo, "run")
    runner.tick()
    assert sorted(c.case_id for c in runner.state.running()) == ["t_001", "t_004"]

    (repo / "hpc" / "control.yaml").write_text("state: stop\nruns: [t]\n")
    _commit_all(repo, "stop")
    runner.tick()
    assert not runner.state.running()
    assert runner.state.cases["t_001"].status == "pending" and runner.state.cases["t_001"].attempts == 0


def test_restart_adopts_running_cases_and_timeout_stops_hanging_ones(world, monkeypatch):
    monkeypatch.setenv("HPC_FAKE_HANG", "t_001")
    first = world["make_runner"]()
    first.tick()
    pid = first.state.cases["t_001"].pid
    first.state.save(first.state_path)
    second = world["make_runner"]()  # e.g. after a crash of the runner: the case keeps running
    assert second.state.cases["t_001"].status == "running" and second.state.cases["t_001"].pid == pid
    second.state.runs["t"].timeout_a_min = 0.001  # 0.06 s, then the case is killed
    second.state.runs["t"].timeout_b_min = 0.001
    second.state.runs["t"].retries = 0
    _run_until(second, lambda: second.state.cases["t_001"].status == "failed")
    assert "timeout" in second.state.cases["t_001"].error


def test_finished_cases_are_adopted_not_rerun(world):
    runner = world["make_runner"]()
    case_dir = world["repo"] / "cases" / "t_002"  # an opposite-walls case finished earlier (e.g. pilot)
    case_dir.mkdir(parents=True)
    (case_dir / "summary.json").write_text(json.dumps({"tau_s": 33.5, "t90_s": 76.4}))
    _run_until(runner, lambda: runner.state.cases.get("t_002") and runner.state.cases["t_002"].status == "done")
    assert runner.state.cases["t_002"].attempts == 0
    assert "adopted" in " ".join(e["text"] for e in runner.state.events)


def test_broken_control_file_keeps_the_last_good_one(world):
    runner = world["make_runner"]()
    runner.tick()
    (world["repo"] / "hpc" / "control.yaml").write_text("state: run\nruns: [t, nope]\n")
    _commit_all(world["repo"], "broken")
    runner.tick()
    assert "no run file" in runner.control_error and runner.control.state == "run"


def test_case_busy_in_another_process_is_not_started_twice(tmp_path):
    from hpc.jobs import Jobs

    jobs = Jobs(tmp_path, sys.executable)
    case = Case("c1", "r", "x.yaml", "opposite_walls")
    (tmp_path / "cases" / "c1").mkdir(parents=True)
    assert not jobs.busy_elsewhere(case)
    other = subprocess.Popen(["sleep", "30"], cwd=tmp_path / "cases" / "c1")  # e.g. snappyHexMesh of a manual queue
    try:
        assert jobs.busy_elsewhere(case)
    finally:
        other.kill()
        other.wait()


def test_show_summarises_runs_running_cases_failures_and_events(tmp_path):
    from hpc.show import summary
    from hpc.state import Run

    now = time.time()
    state = State()
    state.runs["r"] = Run("r", "abc", 2, 4, 1, 45, 300, started=now - 3600)
    state.cases["r_001"] = Case("r_001", "r", "x", "same_wall", status="running", attempts=1, started=now - 1800)
    state.cases["r_002"] = Case("r_002", "r", "x", "opposite_walls", status="done")
    state.cases["r_003"] = Case("r_003", "r", "x", "adjacent_walls", status="failed", attempts=2, error="Case failed: x")
    state.event("runner started")
    text = summary(state, tmp_path, updated=now - 30, now=now)
    assert "r               3 cases   done 1  running 1  failed 1" in text
    assert "running  r_001" in text and "same_wall" in text and "30 min" in text
    assert "FAILED   r_003            Case failed: x" in text and "runner started" in text
