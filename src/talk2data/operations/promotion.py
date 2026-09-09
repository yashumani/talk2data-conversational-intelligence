"""Verify exact-candidate evidence against authenticated GitHub run/artifact/approval records."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from talk2data.operations.release import Candidate, ReleaseManifest, evaluate

REVIEW_GATES = {
    "business-acceptance": "business_acceptance",
    "security-acceptance": "security_approval",
    "operations-acceptance": "operations_approval",
}


def github(repository: str, resource: str) -> bytes:
    # Only the installed authenticated CLI handles its token; never put credentials in arguments/logs.
    result = subprocess.run(
        ["gh", "api", f"repos/{repository}/{resource}"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode or len(result.stdout) > 16_000_000:
        raise ValueError("Authenticated release evidence is unavailable.")
    return result.stdout


def review_owners(
    run: dict[str, Any], reviews: list[dict[str, Any]], policy: dict[str, list[str]], candidate: Candidate
) -> dict[str, str]:
    if (
        run.get("head_sha") != candidate.source_commit
        or run.get("head_branch") != "main"
        or run.get("event") != "workflow_dispatch"
        or run.get("conclusion") != "success"
        or run.get("run_attempt") != 1
        or run.get("path") != ".github/workflows/enterprise-review.yml"
    ):
        raise ValueError("Release reviews do not belong to the approved source and first workflow attempt.")
    if set(policy) != set(REVIEW_GATES) or any(not owners for owners in policy.values()):
        raise ValueError("All release review roles require an approved reviewer allowlist.")
    approved: dict[str, str] = {}
    actor = run["actor"]["login"]
    for review in reviews:
        for environment in review.get("environments", []):
            name = environment.get("name")
            if name in REVIEW_GATES:
                owner = review["user"]["login"]
                if review.get("state") != "approved" or owner == actor or owner not in policy[name]:
                    raise ValueError(
                        "Release approval is rejected, self-approved or outside the owner allowlist."
                    )
                approved[REVIEW_GATES[name]] = owner
    if len(approved) != 3 or len(set(approved.values())) != 3:
        raise ValueError("Business, security and operations require three distinct recorded reviewers.")
    return approved


def extract_evidence(raw: bytes, directory: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if len(names) != len(set(names)) or not 2 <= len(names) <= 16:
            raise ValueError("Evidence bundle member count is invalid.")
        for member in members:
            if (
                not re.fullmatch(r"[a-zA-Z0-9_-]+\.json", member.filename)
                or member.file_size > 1_000_000
                or member.external_attr >> 16 & 0o170000 == 0o120000
            ):
                raise ValueError("Evidence bundles require bounded regular JSON files only.")
            (directory / member.filename).write_bytes(archive.read(member))


def verify(
    repository: str, run_id: int, candidate: Candidate, policy: dict[str, list[str]]
) -> dict[str, object]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or run_id < 1:
        raise ValueError("An explicit GitHub repository and workflow run are required.")
    run = json.loads(github(repository, f"actions/runs/{run_id}"))
    owners = review_owners(
        run, json.loads(github(repository, f"actions/runs/{run_id}/approvals")), policy, candidate
    )
    artifacts = json.loads(github(repository, f"actions/runs/{run_id}/artifacts?per_page=100"))["artifacts"]
    matches = [artifact for artifact in artifacts if artifact["name"] == "enterprise-evidence"]
    if len(matches) != 1 or matches[0].get("expired") or not isinstance(matches[0].get("id"), int):
        raise ValueError("One retained immutable workflow evidence artifact is required.")
    artifact = matches[0]
    if not isinstance(artifact.get("size_in_bytes"), int) or not 0 < artifact["size_in_bytes"] <= 16_000_000:
        raise ValueError("Evidence artifact size exceeds its contract.")
    raw = github(repository, f"actions/artifacts/{artifact['id']}/zip")
    if artifact.get("digest") != "sha256:" + hashlib.sha256(raw).hexdigest():
        raise ValueError("Evidence artifact digest does not match GitHub's authenticated record.")
    with tempfile.TemporaryDirectory(prefix="t2d-evidence-") as temporary:
        directory = Path(temporary)
        extract_evidence(raw, directory)
        if Candidate.model_validate_json((directory / "candidate.json").read_bytes()) != candidate:
            raise ValueError("Review evidence belongs to a different image or private configuration.")
        manifest = ReleaseManifest.model_validate_json((directory / "manifest.json").read_bytes())
        report = evaluate(candidate, manifest, evidence_directory=directory)
        if report["status"] != "EVIDENCE_COMPLETE":
            raise ValueError("Candidate acceptance evidence is incomplete.")
        for evidence in manifest.evidence:
            if evidence.gate in owners and evidence.owner != owners[evidence.gate]:
                raise ValueError("The receipt owner does not match the authenticated approval.")
    return {
        "status": "REVIEWED_CANDIDATE",
        "deployment_authorized": False,
        "source_commit": candidate.source_commit,
        "image_digest": candidate.image_digest,
        "configuration_digest": candidate.configuration_digest,
        "evidence_run": run_id,
        "artifact_digest": artifact["digest"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--review-policy", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = verify(
            args.repository,
            args.run,
            Candidate.model_validate_json(args.candidate.read_bytes()),
            json.loads(args.review_policy.read_bytes()),
        )
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, subprocess.SubprocessError):
        print('{"status":"BLOCKED","deployment_authorized":false}')
        return 1
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
