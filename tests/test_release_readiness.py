from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from talk2data.operations.release import (
    GATES,
    Candidate,
    Evidence,
    ReleaseManifest,
    evaluate,
    main,
    verified_artifact,
)

NOW = datetime(2026, 9, 8, tzinfo=UTC)
CANDIDATE = Candidate(
    source_commit="a" * 40, image_digest="sha256:" + "b" * 64, configuration_digest="c" * 64
)


def evidence(**updates: Any) -> dict[str, Any]:
    return {
        "gate": "quality",
        "status": "passed",
        "method": "automated",
        **CANDIDATE.model_dump(),
        "observed_at": NOW,
        "artifact_digest": "d" * 64,
        "evidence_reference": "private-approved-evidence",
        "owner": "named-owner",
        **updates,
    }


def complete() -> ReleaseManifest:
    return ReleaseManifest(
        evidence=[
            Evidence.model_validate(evidence(gate=gate, method=method)) for gate, method in GATES.items()
        ]
    )


def materialize(manifest: ReleaseManifest, directory: Path) -> ReleaseManifest:
    records = []
    for record in manifest.evidence:
        name = record.gate + ".json"
        raw = record.model_dump_json(exclude={"artifact_digest", "evidence_reference"}).encode()
        (directory / name).write_bytes(raw)
        records.append(
            record.model_copy(
                update={"artifact_digest": hashlib.sha256(raw).hexdigest(), "evidence_reference": name}
            )
        )
    return ReleaseManifest(evidence=records)


def test_complete_evidence_is_not_deployment_authorization(tmp_path: Path) -> None:
    manifest = materialize(complete(), tmp_path)
    result = evaluate(CANDIDATE, manifest, at=NOW, evidence_directory=tmp_path)
    assert result["status"] == "EVIDENCE_COMPLETE" and result["deployment_authorized"] is False
    assert "private-approved-evidence" not in json.dumps(result) and "named-owner" not in json.dumps(result)


def test_empty_manifest_and_deferred_live_connections_block_release(tmp_path: Path) -> None:
    result = evaluate(CANDIDATE, ReleaseManifest(evidence=[]), at=NOW)
    assert result["status"] == "BLOCKED"
    assert len(result["gates"]) == len(GATES)  # type: ignore[arg-type]
    for status in ("deferred", "skipped", "open", "failed"):
        manifest = complete()
        record = next(e for e in manifest.evidence if e.gate == "DG-1")
        manifest.evidence[manifest.evidence.index(record)] = record.model_copy(update={"status": status})
        result = evaluate(CANDIDATE, materialize(manifest, tmp_path), at=NOW, evidence_directory=tmp_path)
        assert result["status"] == "BLOCKED"
        assert next(g for g in result["gates"] if g["gate"] == "DG-1")["reasons"] == ["NOT_PASSED"]  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"method": "recording"}, "WRONG_ACCEPTANCE_METHOD"),
        ({"source_commit": "e" * 40}, "CANDIDATE_MISMATCH"),
        ({"image_digest": "sha256:" + "e" * 64}, "CANDIDATE_MISMATCH"),
        ({"configuration_digest": "e" * 64}, "CANDIDATE_MISMATCH"),
        ({"observed_at": NOW - timedelta(days=8)}, "STALE_OR_FUTURE_EVIDENCE"),
        ({"observed_at": NOW + timedelta(seconds=1)}, "STALE_OR_FUTURE_EVIDENCE"),
    ],
)
def test_mocked_wrong_build_or_stale_acceptance_cannot_pass(
    tmp_path: Path, updates: Any, reason: str
) -> None:
    manifest = complete()
    manifest.evidence[0] = Evidence.model_validate(evidence(**updates))
    result = evaluate(CANDIDATE, materialize(manifest, tmp_path), at=NOW, evidence_directory=tmp_path)
    assert result["gates"][0]["reasons"] == [reason]  # type: ignore[index]


@pytest.mark.parametrize(
    "updates",
    [
        {"gate": "invented"},
        {"owner": " "},
        {"evidence_reference": " "},
        {"status": "waived"},
        {"observed_at": "2026-09-08T00:00:00"},
        {"source_commit": "main"},
        {"secret": "forbidden"},
    ],
)
def test_strict_release_contract(updates: Any) -> None:
    with pytest.raises(ValidationError):
        Evidence.model_validate(evidence(**updates))


def test_duplicate_gate_and_naive_evaluation_rejected() -> None:
    with pytest.raises(ValidationError):
        ReleaseManifest(evidence=[Evidence.model_validate(evidence())] * 2)
    with pytest.raises(ValueError):
        evaluate(CANDIDATE, complete(), at=NOW.replace(tzinfo=None))


def test_cli_returns_blocked_invalid_and_complete_exit_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    candidate = tmp_path / "candidate.json"
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "release",
            "--candidate",
            str(candidate),
            "--manifest",
            str(manifest),
            "--evidence-directory",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit) as exited:
        main()
    assert exited.value.code == 2 and "INVALID_RELEASE_INPUT" in capsys.readouterr().out
    candidate.write_text(CANDIDATE.model_dump_json())
    manifest.write_text(ReleaseManifest(evidence=[]).model_dump_json())
    with pytest.raises(SystemExit) as exited:
        main()
    assert exited.value.code == 1 and '"BLOCKED"' in capsys.readouterr().out
    accepted = complete()
    for i, record in enumerate(accepted.evidence):
        accepted.evidence[i] = record.model_copy(update={"observed_at": datetime.now(UTC)})
    manifest.write_text(materialize(accepted, tmp_path).model_dump_json())
    with pytest.raises(SystemExit) as exited:
        main()
    assert exited.value.code == 0 and '"EVIDENCE_COMPLETE"' in capsys.readouterr().out


@pytest.mark.parametrize(
    "damage", ["missing", "digest", "invalid", "metadata", "oversized", "absolute", "traversal", "symlink"]
)
def test_evidence_files_must_exist_match_digest_and_stay_in_approved_directory(
    tmp_path: Path, damage: str
) -> None:
    manifest = materialize(complete(), tmp_path)
    record = manifest.evidence[0]
    path = tmp_path / record.evidence_reference
    if damage == "missing":
        path.unlink()
    elif damage == "digest":
        path.write_bytes(b"modified")
    elif damage in {"invalid", "metadata", "oversized"}:
        if damage == "invalid":
            raw = b"[]"
        elif damage == "metadata":
            value = json.loads(path.read_bytes())
            value["owner"] = "different-owner"
            raw = json.dumps(value).encode()
        else:
            raw = b"x" * 1_000_001
        path.write_bytes(raw)
        record = record.model_copy(update={"artifact_digest": hashlib.sha256(raw).hexdigest()})
    elif damage == "absolute":
        record = record.model_copy(update={"evidence_reference": str(path)})
    elif damage == "traversal":
        record = record.model_copy(update={"evidence_reference": "../quality.json"})
    else:
        target = tmp_path / "original.json"
        path.rename(target)
        path.symlink_to(target)
    assert not verified_artifact(record, tmp_path)
    assert not verified_artifact(record, None)
    manifest.evidence[0] = record
    result = evaluate(CANDIDATE, manifest, at=NOW, evidence_directory=tmp_path)
    assert result["status"] == "BLOCKED" and "ARTIFACT_NOT_VERIFIED" in result["gates"][0]["reasons"]  # type: ignore[index]
