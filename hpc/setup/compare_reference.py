"""Compare the simulation PC's reference results with the laptop's (hpc/setup/README.md, step 7).

Usage, from the repository root after hpc/setup/reference_check.sh has run the cases:
    python -m hpc.setup.compare_reference

Matching results mean that both machines can produce dataset rows. Exits with 1 if anything differs.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

REFERENCE = Path(__file__).with_name("reference.json")
CASES = Path("cases")


def within(value, expected: float, tolerance: float) -> bool:
    """True if value is within the relative tolerance of expected (both 'not reached' also counts)."""
    if value is None:
        return False
    if math.isnan(value) or math.isnan(expected):
        return math.isnan(value) and math.isnan(expected)
    return abs(value - expected) <= tolerance * abs(expected)


def compare(check: dict, summary: dict, cell_tolerance: float) -> list[tuple[str, float, float | None, bool]]:
    """Rows (quantity, laptop, this PC, ok) for one reference check; summary is the case's summary.json."""
    result = summary if check["method"] == "A" else summary.get("transient", {})
    rows = [("cells", check["n_cells"], summary.get("n_cells"),
             within(summary.get("n_cells"), check["n_cells"], cell_tolerance))]
    for key in ("t90_s", "tau_s"):
        rows.append((key, check[key], result.get(key), within(result.get(key), check[key], check["tolerance"])))
    return rows


def _seconds(check: dict, summary: dict) -> float | None:
    if check["method"] == "B":
        return summary.get("transient", {}).get("solver_wall_seconds")
    parts = [summary.get(k) for k in ("mesh_seconds", "flow_seconds", "tracer_seconds")]
    return sum(parts) if all(p is not None for p in parts) else None


def main() -> None:
    reference = json.loads(REFERENCE.read_text())
    failures = 0
    print(f"{'case':<24}{'method':<8}{'quantity':<10}{'laptop':>10}{'this PC':>10}{'diff':>8}  result")
    for check in reference["checks"]:
        summary_file = CASES / check["case"] / "summary.json"
        if not summary_file.exists():
            print(f"{check['case']:<24}{check['method']:<8}not run yet ({summary_file} missing)  FAIL")
            failures += 1
            continue
        summary = json.loads(summary_file.read_text())
        for quantity, laptop, here, ok in compare(check, summary, reference["cell_tolerance"]):
            diff = f"{(here / laptop - 1) * 100:+.1f}%" if here is not None and not math.isnan(here) and laptop else ""
            here_text = "missing" if here is None else f"{here:g}"
            print(f"{check['case']:<24}{check['method']:<8}{quantity:<10}{laptop:>10g}{here_text:>10}{diff:>8}  "
                  f"{'OK' if ok else 'FAIL'}")
            failures += not ok
        seconds = _seconds(check, summary)
        if seconds and check.get("laptop_seconds"):
            print(f"{'':<32}time: laptop {check['laptop_seconds']} s, this PC {seconds:.0f} s (information only)")
    print("\nAll reference results match." if failures == 0 else f"\n{failures} value(s) differ: compare the logs before mixing results.")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
