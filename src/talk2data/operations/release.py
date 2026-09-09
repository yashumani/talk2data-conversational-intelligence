"""Fail-closed release evidence evaluation; no deployment or secret configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

GATES: dict[str, str] = {
    "quality": "automated",
    "csv_restart": "automated",
    "production_state": "live",
    "distributed_workers": "live",
    "backup_restore": "live",
    "load_and_cost": "live",
    "browser_accessibility": "live",
    "LA-1": "live",
    "DG-1": "live",
    "business_acceptance": "owner_review",
    "security_approval": "owner_review",
    "operations_approval": "owner_review",
}
Sha = str


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    gate: str
    status: Literal["passed", "open", "deferred", "failed", "skipped"]
    method: Literal["automated", "live", "owner_review", "recording"]
    source_commit: Sha = Field(pattern=r"^[0-9a-f]{40}$")
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    configuration_digest: Sha = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: AwareDatetime
    artifact_digest: Sha = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_reference: str = Field(min_length=1, max_length=1000)
    owner: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def known_gate(self) -> Self:
        if self.gate not in GATES or not self.owner.strip() or not self.evidence_reference.strip():
            raise ValueError("A known gate and named evidence owner/reference are required.")
        return self


class ReleaseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    evidence: list[Evidence] = Field(max_length=len(GATES))

    @model_validator(mode="after")
    def unique_gates(self) -> Self:
        if len({e.gate for e in self.evidence}) != len(self.evidence):
            raise ValueError("Release gates must have one unambiguous evidence record each.")
        return self


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_commit: Sha = Field(pattern=r"^[0-9a-f]{40}$")
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    configuration_digest: Sha = Field(pattern=r"^[0-9a-f]{64}$")


def evaluate(
    candidate: Candidate,
    manifest: ReleaseManifest,
    *,
    at: datetime | None = None,
    evidence_directory: Path | None = None,
) -> dict[str, object]:
    timestamp = at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Release evaluation needs a timezone-aware timestamp.")
    records = {e.gate: e for e in manifest.evidence}
    gates = []
    for name, method in GATES.items():
        evidence = records.get(name)
        reasons = []
        if evidence is None:
            reasons.append("MISSING_EVIDENCE")
        else:
            if evidence.status != "passed":
                reasons.append("NOT_PASSED")
            if evidence.method != method:
                reasons.append("WRONG_ACCEPTANCE_METHOD")
            if any(
                getattr(evidence, field) != getattr(candidate, field)
                for field in type(candidate).model_fields
            ):
                reasons.append("CANDIDATE_MISMATCH")
            if not timestamp - timedelta(days=7) <= evidence.observed_at <= timestamp:
                reasons.append("STALE_OR_FUTURE_EVIDENCE")
            if not verified_artifact(evidence, evidence_directory):
                reasons.append("ARTIFACT_NOT_VERIFIED")
        gates.append({"gate": name, "status": "BLOCKED" if reasons else "PASSED", "reasons": reasons})
    return {
        "status": "BLOCKED" if any(gate["reasons"] for gate in gates) else "EVIDENCE_COMPLETE",
        "candidate": candidate.model_dump(),
        "gates": gates,
        "deployment_authorized": False,
    }


def verified_artifact(evidence: Evidence, directory: Path | None) -> bool:
    if directory is None:
        return False
    try:
        reference = Path(evidence.evidence_reference)
        if reference.is_absolute() or ".." in reference.parts:
            return False
        path = directory / reference
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(directory.resolve(strict=True)):
            return False
        with path.open("rb") as stream:
            raw = stream.read(1_000_001)
        if len(raw) > 1_000_000 or hashlib.sha256(raw).hexdigest() != evidence.artifact_digest:
            return False
        receipt = Evidence.model_validate(
            {
                **json.loads(raw),
                "artifact_digest": evidence.artifact_digest,
                "evidence_reference": evidence.evidence_reference,
            }
        )
        return receipt == evidence
    except (OSError, ValueError, TypeError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = evaluate(
            Candidate.model_validate_json(args.candidate.read_bytes()),
            ReleaseManifest.model_validate_json(args.manifest.read_bytes()),
            evidence_directory=args.evidence_directory,
        )
    except (OSError, ValueError):
        print(
            json.dumps(
                {"status": "BLOCKED", "reason": "INVALID_RELEASE_INPUT", "deployment_authorized": False}
            )
        )
        raise SystemExit(2) from None
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "EVIDENCE_COMPLETE" else 1)


if __name__ == "__main__":
    main()
