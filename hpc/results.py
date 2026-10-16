"""After a case: copy its results into the folder of the hpc-results branch, with two small pictures.

results/<run_id>/<case_id>/
    config.yaml, summary.json, fresh_fraction.csv (+ fresh_fraction_transient.csv for method B)
    setup.jpg, flow.jpg      room setup and streamlines (done cases; skipped if rendering fails)
    log_tail.txt             last lines of the log (failed cases)

These are the files the dataset writer reads (DATASET_PLAN.md §3); the large case folders stay on
the simulation PC.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from hpc.state import Case

COPY = ("summary.json", "fresh_fraction.csv", "fresh_fraction_transient.csv")
JPEG_WIDTH, JPEG_QUALITY = 900, 82


def _render(cmd: list[str], cwd: Path, code_dir: Path, timeout: float = 240) -> bool:
    """Run a picture command; without a display, try once more under xvfb-run."""
    env = {**os.environ, "PYTHONPATH": str(code_dir)}
    attempts = [cmd] + ([["xvfb-run", "-a", *cmd]] if shutil.which("xvfb-run") else [])
    for attempt in attempts:
        try:
            if subprocess.run(attempt, cwd=cwd, env=env, capture_output=True, timeout=timeout).returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def to_jpeg(png: Path, jpg: Path) -> None:
    from PIL import Image  # comes with matplotlib

    with Image.open(png) as image:
        image = image.convert("RGB")
        if image.width > JPEG_WIDTH:
            image = image.resize((JPEG_WIDTH, round(image.height * JPEG_WIDTH / image.width)))
        image.save(jpg, quality=JPEG_QUALITY, optimize=True)
    png.unlink()


def render_pictures(case: Case, config: Path, repo: Path, code_dir: Path, python: str, dest: Path) -> list[Path]:
    """setup.jpg (3D room) and flow.jpg (streamlines at window height); returns those that worked."""
    made = []
    jobs = {"setup": [python, "-P", "-m", "geometry.render", str(config), "--out", str(dest / "setup.png")],
            "flow": [python, "-P", "-m", "analysis.visualize", "--config", str(config), "--kind", "flow",
                     "--out", str(dest / "flow.png")]}
    for name, cmd in jobs.items():
        if _render(cmd, repo, code_dir) and (dest / f"{name}.png").exists():
            to_jpeg(dest / f"{name}.png", dest / f"{name}.jpg")
            made.append(dest / f"{name}.jpg")
    return made


def package(case: Case, case_dir: Path, config: Path, results_root: Path, log_tail: str) -> Path:
    """Copy the result files of one case; returns its folder in the results branch."""
    dest = results_root / "results" / case.run_id / case.case_id
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(config, dest / "config.yaml")
    for name in COPY:
        if (case_dir / name).exists():
            shutil.copy(case_dir / name, dest / name)
    if case.status == "failed":
        (dest / "log_tail.txt").write_text(log_tail + "\n")
    return dest
