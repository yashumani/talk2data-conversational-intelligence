"""Check every committed workflow's YAML before GitHub evaluates the default branch."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def main() -> int:
    paths = sorted((Path(__file__).resolve().parents[1] / ".github/workflows").glob("*.yml"))
    if not paths:
        print("No GitHub workflow files found.", file=sys.stderr)
        return 1
    failed = False
    for path in paths:
        try:
            # BaseLoader preserves the 'on' key instead of treating it as a YAML 1.1 boolean.
            workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
            if (
                not isinstance(workflow, dict)
                or "on" not in workflow
                or not isinstance(workflow.get("jobs"), dict)
                or not workflow["jobs"]
            ):
                raise ValueError("Workflow must contain triggers and a non-empty jobs mapping.")
        except (yaml.YAMLError, ValueError) as exc:
            print(f"{path.name}: {exc}", file=sys.stderr)
            failed = True
    if failed:
        return 1
    print(f"Validated YAML syntax and top-level structure for {len(paths)} GitHub workflows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
