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


def validate_job_controls(workflow: dict[object, object]) -> None:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        raise ValueError("Workflow jobs must be a mapping.")
    pull_request_workflow = isinstance(workflow.get("on"), dict) and "pull_request" in workflow["on"]
    for job_name, raw_job in jobs.items():
        if not isinstance(raw_job, dict):
            raise ValueError(f"Job {job_name!r} must be a mapping.")
        if pull_request_workflow:
            timeout = raw_job.get("timeout-minutes")
            if not isinstance(timeout, str) or not timeout.isdecimal() or not 1 <= int(timeout) <= 360:
                raise ValueError(f"Pull-request job {job_name!r} needs a literal 1–360 minute timeout.")
        steps = raw_job.get("steps", [])
        if not isinstance(steps, list):
            raise ValueError(f"Job {job_name!r} steps must be a list.")
        for step in steps:
            if not isinstance(step, dict) or not str(step.get("uses", "")).startswith("actions/checkout@"):
                continue
            settings = step.get("with")
            if not isinstance(settings, dict) or settings.get("persist-credentials") != "false":
                raise ValueError(f"Checkout in job {job_name!r} must set persist-credentials: false.")


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
            validate_job_controls(workflow)
        except (yaml.YAMLError, ValueError) as exc:
            print(f"{path.name}: {exc}", file=sys.stderr)
            failed = True
    if failed:
        return 1
    print(f"Validated YAML, structure and immutable action references for {len(paths)} GitHub workflows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
