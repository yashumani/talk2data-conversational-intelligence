"""Require line and branch coverage independently; a combined score can hide weak branches."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    report = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else "coverage.json").read_text())
    totals = report["totals"]
    if not report["meta"].get("branch_coverage"):
        raise ValueError("Branch coverage must be enabled.")
    passed = True
    for label, covered, total in [
        ("Lines", totals["covered_lines"], totals["num_statements"]),
        ("Branches", totals["covered_branches"], totals["num_branches"]),
    ]:
        if total <= 0:
            raise ValueError(f"{label} coverage has an empty denominator.")
        percentage = 100 * covered / total
        print(f"{label}: {percentage:.2f}% ({covered}/{total}); required: 96%")
        passed = passed and percentage >= 96
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
