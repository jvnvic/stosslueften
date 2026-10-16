"""Notifications through GitHub issues: one issue per run, events as comments (HPC_PLAN.md §5).

The GitHub app on the phone then notifies about every comment. Comments are batched to at most
one per 30 minutes, except the run's final summary. The token (fine-grained, this repository only,
Issues: read and write) is read from ~/.config/stosslueften/token and never written anywhere else.
Without a token, notifications are switched off and the runner works as usual.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

TOKEN_FILE = Path.home() / ".config" / "stosslueften" / "token"
BATCH_S = 30 * 60


def repo_slug(remote_url: str) -> str | None:
    """'owner/name' from an SSH alias, git@ or https URL of the GitHub repository."""
    match = re.search(r"[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", remote_url)
    return f"{match.group(1)}/{match.group(2)}" if match else None


class Notifier:
    def __init__(self, slug: str | None, token_file: Path = TOKEN_FILE, send=None):
        self.slug = slug
        self.token = token_file.read_text().strip() if token_file.exists() else None
        self._send = send or self._http  # replaced in tests
        self.queue: dict[int, list[str]] = {}  # issue -> waiting comment lines
        self.last_sent: dict[int, float] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.slug)

    def _http(self, method: str, path: str, body: dict) -> dict:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.slug}{path}", method=method, data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read() or b"{}")

    def open_issue(self, title: str, text: str) -> int | None:
        if not self.enabled:
            return None
        try:
            return self._send("POST", "/issues", {"title": title, "body": text})["number"]
        except (urllib.error.URLError, OSError, KeyError, ValueError):
            return None

    def note(self, issue: int | None, line: str) -> None:
        """Queue one line for the next comment on the issue."""
        if issue is not None and self.enabled:
            self.queue.setdefault(issue, []).append(f"- {time.strftime('%d.%m. %H:%M')} {line}")

    def flush(self, force: bool = False) -> None:
        """Post the waiting lines as one comment per issue, at most every 30 minutes (unless forced)."""
        for issue, lines in list(self.queue.items()):
            if not lines or (not force and time.time() - self.last_sent.get(issue, 0) < BATCH_S):
                continue
            try:
                self._send("POST", f"/issues/{issue}/comments", {"body": "\n".join(lines)})
                self.queue[issue] = []
                self.last_sent[issue] = time.time()
            except (urllib.error.URLError, OSError, ValueError):
                pass  # GitHub not reachable: the lines stay queued for the next try

    def close(self, issue: int | None, text: str) -> None:
        if issue is None or not self.enabled:
            return
        self.note(issue, text)
        self.flush(force=True)
        try:
            self._send("PATCH", f"/issues/{issue}", {"state": "closed"})
        except (urllib.error.URLError, OSError, ValueError):
            pass
