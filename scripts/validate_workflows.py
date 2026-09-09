"""Check every committed workflow's YAML before GitHub evaluates the default branch."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


def validate_action_pins(value: object) -> None:
    """Check steps and reusable jobs, including nested mappings and lists."""
    if isinstance(value, dict):
        if "uses" in value:
            reference = value["uses"]
            if not isinstance(reference, str):
                raise ValueError("Action reference must be a string.")
            if reference.startswith("./"):
                pass  # A local action is already bound to the checked-out source revision.
            elif reference.startswith("docker://"):
                if not re.fullmatch(r"docker://[^@\s]+@sha256:[a-f0-9]{64}", reference):
                    raise ValueError(f"Container action must use a SHA-256 digest: {reference}")
            elif not re.fullmatch(r"[^@\s]+/[^@\s]+@[a-f0-9]{40}", reference):
                raise ValueError(f"Remote action must use a full commit SHA: {reference}")
        for child in value.values():
            validate_action_pins(child)
    elif isinstance(value, list):
        for child in value:
            validate_action_pins(child)


def main() -> int:
    directory = Path(__file__).resolve().parents[1] / ".github/workflows"
    paths = sorted(path for path in directory.glob("*") if path.suffix in {".yml", ".yaml"})
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
            validate_action_pins(workflow["jobs"])
        except (yaml.YAMLError, ValueError) as exc:
            print(f"{path.name}: {exc}", file=sys.stderr)
            failed = True
    if failed:
        return 1
    print(f"Validated YAML, structure and immutable action references for {len(paths)} GitHub workflows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
