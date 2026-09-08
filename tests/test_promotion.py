from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from talk2data.domain.runs import now
from talk2data.operations import promotion
from talk2data.operations.release import ReleaseManifest
from tests.test_release_readiness import CANDIDATE, complete, materialize

POLICY = {environment: [environment + "-owner"] for environment in promotion.REVIEW_GATES}
RUN = {
    "head_sha": CANDIDATE.source_commit,
    "head_branch": "main",
    "event": "workflow_dispatch",
    "conclusion": "success",
    "run_attempt": 1,
    "path": ".github/workflows/enterprise-review.yml",
    "actor": {"login": "release-operator"},
}
REVIEWS = [
    {"state": "approved", "environments": [{"name": environment}], "user": {"login": owners[0]}}
    for environment, owners in POLICY.items()
]


def bundle(directory: Path, damage: str = "") -> bytes:
    manifest = complete()
    owners = {gate: POLICY[environment][0] for environment, gate in promotion.REVIEW_GATES.items()}
    manifest.evidence[:] = [
        record.model_copy(update={"owner": owners.get(record.gate, "automation"), "observed_at": now()})
        for record in manifest.evidence
    ]
    if damage == "owner":
        manifest.evidence[-1] = manifest.evidence[-1].model_copy(update={"owner": "different-owner"})
    if damage == "incomplete":
        manifest = ReleaseManifest(evidence=[])
    manifest = materialize(manifest, directory)
    (directory / "manifest.json").write_text(manifest.model_dump_json())
    candidate = (
        CANDIDATE.model_copy(update={"image_digest": "sha256:" + "e" * 64})
        if damage == "candidate"
        else CANDIDATE
    )
    (directory / "candidate.json").write_text(candidate.model_dump_json())
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path in directory.glob("*.json"):
            archive.write(path, path.name)
    return output.getvalue()


def mock_platform(
    monkeypatch: pytest.MonkeyPatch, raw: bytes, artifact_update: dict[str, Any] | None = None
) -> None:
    artifact = {
        "id": 123,
        "name": "enterprise-evidence",
        "expired": False,
        "size_in_bytes": len(raw),
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        **(artifact_update or {}),
    }
    responses = {
        "actions/runs/99": json.dumps(RUN).encode(),
        "actions/runs/99/approvals": json.dumps(REVIEWS).encode(),
        "actions/runs/99/artifacts?per_page=100": json.dumps({"artifacts": [artifact]}).encode(),
        "actions/artifacts/123/zip": raw,
    }
    monkeypatch.setattr(promotion, "github", lambda repo, resource: responses[resource])


def test_verified_artifacts_and_distinct_approvals_bind_one_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_platform(monkeypatch, bundle(tmp_path))
    report = promotion.verify("owner/product", 99, CANDIDATE, POLICY)
    assert report["status"] == "REVIEWED_CANDIDATE" and not report["deployment_authorized"]
    assert "approval" not in json.dumps(report)


@pytest.mark.parametrize(
    "change",
    [
        {"head_sha": "b" * 40},
        {"head_branch": "feature"},
        {"event": "pull_request"},
        {"conclusion": "skipped"},
        {"run_attempt": 2},
        {"path": "other.yml"},
    ],
)
def test_unreviewed_source_and_workflow_rejected(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        promotion.review_owners({**RUN, **change}, REVIEWS, POLICY, CANDIDATE)


@pytest.mark.parametrize(
    "damage", ["missing", "empty", "rejected", "self", "unknown", "duplicate", "unrelated"]
)
def test_owner_approval_cannot_be_forged(damage: str) -> None:
    reviews, policy = deepcopy(REVIEWS), deepcopy(POLICY)
    if damage == "missing":
        reviews.pop()
    if damage == "empty":
        policy["business-acceptance"] = []
    if damage == "rejected":
        reviews[0]["state"] = "rejected"
    if damage == "self":
        reviews[0]["user"]["login"] = "release-operator"
    if damage == "unknown":
        reviews[0]["user"]["login"] = "unapproved"
    if damage == "duplicate":
        reviews[1]["user"]["login"] = reviews[0]["user"]["login"]
        policy["security-acceptance"] = [reviews[0]["user"]["login"]]
    if damage == "unrelated":
        reviews[0]["environments"] = [{"name": "other"}]
    with pytest.raises(ValueError):
        promotion.review_owners(RUN, reviews, policy, CANDIDATE)
    with pytest.raises(ValueError):
        promotion.review_owners(RUN, REVIEWS, {}, CANDIDATE)


@pytest.mark.parametrize("damage", ["candidate", "owner", "incomplete"])
def test_reviewed_receipts_must_match_image_configuration_and_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    mock_platform(monkeypatch, bundle(tmp_path, damage))
    with pytest.raises(ValueError):
        promotion.verify("owner/product", 99, CANDIDATE, POLICY)


@pytest.mark.parametrize(
    "change",
    [
        {"digest": "sha256:" + "0" * 64},
        {"expired": True},
        {"id": "123"},
        {"name": "untrusted"},
        {"size_in_bytes": 20_000_000},
    ],
)
def test_artifact_identity_expiry_and_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    mock_platform(monkeypatch, bundle(tmp_path), change)
    with pytest.raises(ValueError):
        promotion.verify("owner/product", 99, CANDIDATE, POLICY)


@pytest.mark.parametrize("damage", ["traversal", "symlink", "duplicate", "oversized", "empty"])
def test_zip_extraction_rejects_unsafe_members(tmp_path: Path, damage: str) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        if damage != "empty":
            archive.writestr("candidate.json", "{}")
            if damage == "traversal":
                archive.writestr("../outside.json", "{}")
            if damage == "duplicate":
                with pytest.warns(UserWarning):
                    archive.writestr("candidate.json", "{}")
            if damage == "oversized":
                archive.writestr("big.json", "x" * 1_000_001)
            if damage == "symlink":
                member = zipfile.ZipInfo("link.json")
                member.external_attr = 0o120777 << 16
                archive.writestr(member, "outside.json")
    with pytest.raises(ValueError):
        promotion.extract_evidence(output.getvalue(), tmp_path)


def test_cli_uses_authenticated_api_and_sanitizes_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    calls = []

    def call(args: list[str], **kwargs: Any) -> Any:
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=b"{}")

    monkeypatch.setattr(subprocess, "run", call)
    assert promotion.github("owner/product", "actions/runs/99") == b"{}"
    assert calls[0] == ["gh", "api", "repos/owner/product/actions/runs/99"]
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=b"private")
    )
    with pytest.raises(ValueError):
        promotion.github("owner/product", "actions/runs/99")
    for repo, run in [("--malicious", 99), ("owner/product", 0)]:
        with pytest.raises(ValueError):
            promotion.verify(repo, run, CANDIDATE, POLICY)
    candidate, policy = tmp_path / "input.json", tmp_path / "policy.json"
    args = [
        "--repository",
        "owner/product",
        "--run",
        "99",
        "--candidate",
        str(candidate),
        "--review-policy",
        str(policy),
    ]
    assert promotion.main(args) == 1
    raw_dir = tmp_path / "bundle"
    raw_dir.mkdir()
    mock_platform(monkeypatch, bundle(raw_dir))
    candidate.write_text(CANDIDATE.model_dump_json())
    policy.write_text(json.dumps(POLICY))
    assert promotion.main(args) == 0
    assert "private" not in capsys.readouterr().out
