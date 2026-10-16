"""Git for the runner: read the control files from main, publish status and results on own branches.

The runner never writes to main. It publishes through two small separate repositories under its
home folder, each pushing one branch of the same GitHub repository:
- hpc-status: always a single commit, force-pushed (keeps the repository small; GitHub Pages shows it)
- hpc-results: normal history, one commit per batch of finished cases

Network or GitHub problems never stop the runner: calls have time limits, publishing returns False
and is tried again later. The simulations never wait for GitHub (HPC_PLAN.md §5).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

IDENTITY = ("stosslueften-hpc", "hpc@stosslueften.invalid")


class GitError(RuntimeError):
    pass


def git(*args: str, cwd: Path, timeout: float = 120) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GitError(f"git {' '.join(args)}: no answer within {timeout:.0f} s")
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {(result.stderr or result.stdout).strip().splitlines()[-1:]}")
    return result.stdout


class Repo:
    """The runner's own checkout of the repository (its code, and the source of the control files)."""

    def __init__(self, path: Path):
        self.path = path

    def fetch(self) -> bool:
        try:
            git("fetch", "--quiet", "origin", "main", cwd=self.path, timeout=90)
            return True
        except GitError:
            return False

    def show(self, file: str, ref: str = "origin/main") -> str | None:
        """Content of a file on main as last fetched, or None if it does not exist."""
        try:
            return git("show", f"{ref}:{file}", cwd=self.path)
        except GitError:
            return None

    def list_dir(self, folder: str, ref: str = "origin/main") -> list[str]:
        try:
            return git("ls-tree", "--name-only", f"{ref}:{folder}", cwd=self.path).split()
        except GitError:
            return []

    def resolve(self, ref: str) -> str:
        """A branch name (looked up on origin), tag or commit -> full commit hash."""
        for candidate in (f"origin/{ref}", ref):
            try:
                return git("rev-parse", "--verify", f"{candidate}^{{commit}}", cwd=self.path).strip()
            except GitError:
                continue
        raise GitError(f"unknown code version {ref!r}")

    def head(self) -> str:
        return git("rev-parse", "HEAD", cwd=self.path).strip()

    def remote_url(self) -> str:
        return git("remote", "get-url", "origin", cwd=self.path).strip()

    def code_checkout(self, commit: str, root: Path) -> Path:
        """A separate checkout of `commit` (git worktree) for a run's cases; created once, then reused."""
        dest = root / commit
        if not (dest / ".git").exists():
            root.mkdir(parents=True, exist_ok=True)
            git("worktree", "prune", cwd=self.path)
            git("worktree", "add", "--detach", str(dest), commit, cwd=self.path)
        return dest

    def changed_files(self, a: str, b: str) -> list[str]:
        try:
            return git("diff", "--name-only", a, b, cwd=self.path).split()
        except GitError:
            return []

    def update(self, ref: str) -> bool:
        """Fast-forward the runner's own checkout to `ref` (remote runner update). False if not possible."""
        try:
            git("merge", "--ff-only", self.resolve(ref), cwd=self.path)
            return True
        except GitError:
            return False


class Branch:
    """A separate small repository in `folder` that publishes its content to one branch."""

    def __init__(self, folder: Path, url: str, branch: str, history: bool):
        self.folder, self.url, self.branch, self.history = folder, url, branch, history

    def prepare(self) -> None:
        if (self.folder / ".git").exists():
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        git("init", "--quiet", cwd=self.folder)
        git("remote", "add", "origin", self.url, cwd=self.folder)
        git("config", "user.name", IDENTITY[0], cwd=self.folder)
        git("config", "user.email", IDENTITY[1], cwd=self.folder)
        if self.history:  # continue the existing branch, if there is one (e.g. after reinstalling the runner)
            try:
                probe = subprocess.run(["git", "ls-remote", "--exit-code", "origin", self.branch], cwd=self.folder,
                                       capture_output=True, timeout=60).returncode
            except subprocess.TimeoutExpired:
                probe = -1
            if probe == 0:
                git("fetch", "--quiet", "origin", self.branch, cwd=self.folder, timeout=120)
                git("checkout", "--quiet", "-B", self.branch, "FETCH_HEAD", cwd=self.folder)
                return
            if probe != 2:  # GitHub not reachable: start over next time, never begin a second history
                shutil.rmtree(self.folder / ".git")
                raise GitError(f"cannot reach the remote to look for branch {self.branch}")
        git("checkout", "--quiet", "--orphan", self.branch, cwd=self.folder)

    def publish(self, message: str) -> bool:
        """Commit everything in the folder and push it. False if GitHub could not be reached."""
        try:
            self.prepare()
            git("add", "-A", cwd=self.folder)
            has_commit = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=self.folder,
                                        capture_output=True).returncode == 0
            if self.history:
                if not has_commit or git("status", "--porcelain", cwd=self.folder).strip():
                    git("commit", "--quiet", "--allow-empty", "-m", message, cwd=self.folder)
                head = git("rev-parse", "HEAD", cwd=self.folder).strip()
                pushed = self.folder / ".git" / "pushed"  # last commit that reached GitHub
                if pushed.exists() and pushed.read_text().strip() == head:
                    return True  # nothing new
                try:
                    git("push", "--quiet", "origin", f"HEAD:refs/heads/{self.branch}", cwd=self.folder)
                except GitError:  # someone else pushed to the branch: put our commits on top and retry
                    git("pull", "--quiet", "--rebase", "origin", self.branch, cwd=self.folder)
                    git("push", "--quiet", "origin", f"HEAD:refs/heads/{self.branch}", cwd=self.folder)
                pushed.write_text(git("rev-parse", "HEAD", cwd=self.folder))
            else:  # always exactly one commit: amend it and force-push
                git("commit", "--quiet", "--allow-empty", *(["--amend"] if has_commit else []), "-m", message,
                    cwd=self.folder)
                git("push", "--quiet", "--force", "origin", f"HEAD:refs/heads/{self.branch}", cwd=self.folder)
            return True
        except GitError:
            return False
