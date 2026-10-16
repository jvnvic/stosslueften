"""Split the cases of a sweep run into balanced lists for parallel `cfd.queue` processes.

Used until the HPC runner (HPC_PLAN.md) takes over. Usage, from the repository root:
    python -m sweeps.queues configs/sweep/train-v1 --first 15        # the pilot: the first 15 cases
    python -m sweeps.queues configs/sweep/train-v1 --skip-done       # everything not finished yet

Writes cases/sweep_queues/<run>_q<k>.txt and prints one start command per queue.
Same-wall cases (method B, PLAN.md §5) take about ten times as long as the others, so they are
spread evenly over the queues and placed first in each, so that no long case is left alone at the end.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

CASES = Path("cases")
METHOD_B_COST = 10  # runtime of a same-wall case in units of a method A case (PLAN.md §5, HPC_PLAN.md §8)


def is_done(case_id: str, layout: str) -> bool:
    """True if the case has its final result: method A's summary, plus method B's for same-wall cases."""
    try:
        summary = json.loads((CASES / case_id / "summary.json").read_text())
    except (OSError, ValueError):
        return False
    return "tau_s" in summary and (layout != "same_wall" or "transient" in summary)


def split(cases: list[tuple[Path, str]], n_queues: int) -> list[list[Path]]:
    """Longest cases first, each onto the queue with the least work so far (LPT rule)."""
    cost = {path: METHOD_B_COST if layout == "same_wall" else 1 for path, layout in cases}
    queues: list[list[Path]] = [[] for _ in range(n_queues)]
    totals = [0] * n_queues
    for path in sorted(cost, key=lambda p: -cost[p]):  # stable: equal costs keep the run order
        k = totals.index(min(totals))
        queues[k].append(path)
        totals[k] += cost[path]
    return queues


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Split a sweep run into balanced cfd.queue lists.")
    parser.add_argument("run_folder", type=Path, help="e.g. configs/sweep/train-v1")
    parser.add_argument("--queues", type=int, default=2, help="number of parallel queues (default 2)")
    parser.add_argument("--procs", type=int, default=4, help="cores per case (default 4)")
    parser.add_argument("--first", type=int, help="only the first N cases of the run (e.g. a pilot)")
    parser.add_argument("--skip-done", action="store_true", help="leave out cases that already have their result")
    args = parser.parse_args(argv)

    run_id = args.run_folder.name
    paths = sorted(args.run_folder.glob(f"{run_id}_*.yaml"))
    if args.first:
        paths = paths[: args.first]
    cases = [(p, yaml.safe_load(p.read_text())["layout"]) for p in paths]
    if args.skip_done:
        cases = [(p, layout) for p, layout in cases if not is_done(p.stem, layout)]
    if not cases:
        raise SystemExit("no cases left to run")
    out_dir = CASES / "sweep_queues"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"{len(cases)} cases of {run_id} in {args.queues} queues, {args.procs} cores each. Start from the repository root:\n")
    for k, queue in enumerate(split(cases, args.queues), start=1):
        if not queue:
            continue
        listing = out_dir / f"{run_id}_q{k}.txt"
        listing.write_text("".join(f"{p.as_posix()}\n" for p in queue))
        n_b = sum(1 for p, layout in cases if p in queue and layout == "same_wall")
        print(f"# queue {k}: {len(queue)} cases ({n_b} same-wall)")
        print(f"setsid nohup .venv/bin/python -m cfd.queue --procs {args.procs} $(cat {listing.as_posix()}) "
              f"> cases/{run_id}_q{k}.out 2>&1 &\nsleep 2\n")


if __name__ == "__main__":
    main()
