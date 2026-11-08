from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from talk2data.deployment.huggingface import build_space_bundle, validate_space_bundle
from talk2data.services.demo_chat import DemoChatService


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


def test_space_app_passes_every_required_demo_chat_argument() -> None:
    # The Space app imports Gradio, which the test profile does not install, so read its call
    # to DemoChatService statically. A new required argument must also be added to the Space.
    app_source = (Path(__file__).resolve().parents[1] / "hf_space" / "app.py").read_text()
    calls = [
        node
        for node in ast.walk(ast.parse(app_source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "DemoChatService"
    ]
    assert len(calls) == 1
    passed = {keyword.arg for keyword in calls[0].keywords}
    required = {
        name
        for name, parameter in inspect.signature(DemoChatService.__init__).parameters.items()
        if name != "self" and parameter.default is inspect.Parameter.empty
    }
    assert required <= passed, f"hf_space/app.py is missing {sorted(required - passed)}"
    synthetic = next(keyword for keyword in calls[0].keywords if keyword.arg == "synthetic_data")
    assert isinstance(synthetic.value, ast.Constant) and synthetic.value.value is True


def test_bundle_validator_reports_missing_space_metadata(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# no metadata\n", encoding="utf-8")
    errors = validate_space_bundle(tmp_path)
    assert any("sdk: gradio" in error for error in errors)
    assert any("missing required file app.py" in error for error in errors)
