from __future__ import annotations

import json
from pathlib import Path

from talk2data.deployment.huggingface import build_space_bundle, validate_space_bundle


def test_huggingface_bundle_is_self_contained_and_secret_free(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    destination = tmp_path / "space"

    manifest = build_space_bundle(
        repository_root,
        destination,
        source_revision="test-revision",
    )

    assert validate_space_bundle(destination) == []
    assert (destination / "app.py").is_file()
    assert (destination / "talk2data" / "services" / "demo_chat.py").is_file()
    assert not list(destination.rglob("*.db"))
    assert not list(destination.rglob(".env"))
    persisted = json.loads((destination / "DEPLOYMENT_MANIFEST.json").read_text())
    assert persisted["source_revision"] == "test-revision"
    assert persisted["files"] == manifest.files


def test_bundle_validator_reports_missing_space_metadata(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# no metadata\n", encoding="utf-8")
    errors = validate_space_bundle(tmp_path)
    assert any("sdk: gradio" in error for error in errors)
    assert any("missing required file app.py" in error for error in errors)
