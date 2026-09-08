from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from talk2data.core.config import Settings
from talk2data.core.csv_config import CsvDemoSettings
from talk2data.domain.chat import VerificationStatus
from talk2data.internal.bootstrap import create_internal_app
from talk2data.main import create_app
from talk2data.services.certification import ResultSenseValidator
from talk2data.services.claude_interpreter import ClaudeRuntime
from tests.claude_support import RecordingClaude, config, message, proposal
from tests.internal_support import RecordingCloud, private_config
from tests.test_csv_demo import ask, new_session, sample, upload
from tests.test_definition_workflows import publish
from tests.test_internal_api import headers, question

BASE = "/v1/demo/csv"


@pytest.fixture
def workspace(tmp_path: Path) -> Any:
    recording = RecordingClaude()
    app = create_app(
        Settings(database_path=tmp_path / "demo.db", ollama_enabled=False, ollama_required=False),
        csv_settings=CsvDemoSettings(enabled=True),
        csv_language_config=config(),
        csv_language_transport=recording.transport(),
    )
    with TestClient(app) as client:
        yield client, recording


def test_csv_claude_query_runs_specialists_without_sharing_data(workspace: Any) -> None:
    client, recording = workspace
    auth = new_session(client)
    source = upload(client, auth)
    assert not recording.requests
    assert client.get(BASE + "/state", headers=auth).json()["language"]["sends_questions"]
    result = ask(client, auth, source["source_fingerprint"]).json()
    assert result["status"] == "ANSWERED", result
    assert result["ai_model"] == "claude-contract-test"
    assert result["receipt"]["result_rows"] == [{"REGION": "NORTHEAST", "value": 3100.0}]
    report = result["agent_run"]
    assert report["status"] == "ANSWERED"
    assert [s["role"] for s in report["steps"]] == [
        "SEMANTIC_RESOLVER",
        "QUERY_PLANNER",
        "QUERY_EXECUTOR",
        "RESULT_VERIFIER",
        "ANSWER_COMPOSER",
    ]
    assert all(s["status"] == "SUCCEEDED" for s in report["steps"])
    assert report["usage"]["model_calls"] == 1
    for request in recording.requests:
        outbound = request.content.decode()
        assert "3100" not in outbound and "source_fingerprint" not in outbound
        assert "synthetic-secret" not in outbound and "csv_demo" not in outbound


def test_paraphrase_resolves_to_approved_metric_and_exact_numeric_answer(workspace: Any) -> None:
    client, _ = workspace
    auth = new_session(client)
    source = upload(client, auth)
    result = ask(
        client,
        auth,
        source["source_fingerprint"],
        question="How many newly opened mobile lines were there by region last month?",
    ).json()
    assert result["status"] == "ANSWERED", result
    assert result["query_ir"]["metric_id"] == "MOBILE_ACTIVATIONS"
    assert result["receipt"]["result_rows"][0]["value"] == 3100


def test_saved_csv_answers_replay_interpretation_without_another_model_call(workspace: Any) -> None:
    client, recording = workspace
    auth = new_session(client)
    source = upload(client, auth)
    original = ask(client, auth, source["source_fingerprint"]).json()
    run_id = original["receipt"]["query_id"]
    publish(client, auth)
    replacement = upload(client, auth, sample(amount=7))
    recording.responses = [httpx.ConnectError("Provider must not be needed for replay")]
    reproduced = client.post(BASE + f"/history/{run_id}/rerun", headers=auth).json()
    assert reproduced["status"] == "ANSWERED"
    assert reproduced["receipt"]["result_rows"] == original["receipt"]["result_rows"]
    assert reproduced["semantic_context"] == original["semantic_context"]
    assert reproduced["agent_run"]["replayed_interpretation"]
    assert reproduced["agent_run"]["usage"]["model_calls"] == 0
    assert len(recording.requests) == 2
    assert client.get(BASE + "/state", headers=auth).json()["source"] == replacement


def test_published_definitions_are_visible_to_the_next_model_request(workspace: Any) -> None:
    client, recording = workspace
    auth = new_session(client)
    source = upload(client, auth)
    current = publish(client, auth, definition="Completed approved synthetic sales starts.")
    result = ask(
        client, auth, source["source_fingerprint"], definition_snapshot_id=current["snapshot_id"]
    ).json()
    assert result["status"] == "ANSWERED"
    outbound = json.loads(json.loads(recording.requests[0].content)["messages"][0]["content"])
    assert outbound["catalog"]["metrics"][0]["definition"] == "Completed approved synthetic sales starts."
    assert result["semantic_context"]["metric"]["definition_version"] == 2


def test_model_failure_releases_no_answer_and_does_not_fall_back(workspace: Any) -> None:
    client, recording = workspace
    auth = new_session(client)
    source = upload(client, auth)
    assert ask(client, auth, source["source_fingerprint"]).json()["status"] == "ANSWERED"
    recording.responses = [httpx.Response(529, text="private question")]
    response = ask(client, auth, source["source_fingerprint"])
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "PROVIDER_UNAVAILABLE"
    assert response.json()["agent_run"]["steps"][0]["status"] == "FAILED"
    state = client.get(BASE + "/state", headers=auth).json()
    assert state["last_response"] is None and len(state["history"]) == 1
    assert "private question" not in response.text


@pytest.mark.parametrize(
    "extra",
    [
        {"use_llm": False},
        {"agent": "admin"},
        {"tool": "execute_sql"},
        {"model": "another"},
        {"access_context": {"roles": ["ADMIN"]}},
        {"source": "bigquery"},
        {"api_key": "synthetic-secret"},
    ],
)
def test_request_cannot_override_provider_tools_or_authority(workspace: Any, extra: Any) -> None:
    client, recording = workspace
    auth = new_session(client)
    source = upload(client, auth)
    assert ask(client, auth, source["source_fingerprint"], **extra).status_code == 422
    assert not recording.requests


@pytest.mark.parametrize("question_text", [" ", "ab"])
def test_invalid_question_is_rejected_before_provider_execution(workspace: Any, question_text: str) -> None:
    client, recording = workspace
    auth = new_session(client)
    source = upload(client, auth)
    assert ask(client, auth, source["source_fingerprint"], question=question_text).status_code == 422
    assert not recording.requests


def test_ambiguous_request_stops_before_data_execution(workspace: Any) -> None:
    client, recording = workspace
    auth = new_session(client)
    source = upload(client, auth)
    recording.responses = [
        message(content=[{"type": "text", "text": json.dumps(proposal(needs_clarification=True))}])
    ]
    result = ask(client, auth, source["source_fingerprint"]).json()
    assert result["status"] == "CLARIFICATION_REQUIRED" and result["receipt"] is None
    assert len(result["agent_run"]["steps"]) == 1


def test_verification_failure_cannot_be_saved_as_a_successful_run(
    workspace: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = workspace
    auth = new_session(client)
    source = upload(client, auth)
    original = ResultSenseValidator.validate

    def reject(self: Any, **kwargs: Any) -> Any:
        receipt, report = original(self, **kwargs)
        report.status = VerificationStatus.FAILED
        return receipt, report

    monkeypatch.setattr(ResultSenseValidator, "validate", reject)
    result = ask(client, auth, source["source_fingerprint"]).json()
    assert result["status"] == "VERIFICATION_FAILED" and result["answer"] is None
    assert len(result["agent_run"]["steps"]) == 4
    assert client.get(BASE + "/state", headers=auth).json()["history"] == []


def test_demo_question_budget_is_independent_of_saved_reproduction(workspace: Any) -> None:
    client, recording = workspace
    auth = new_session(client)
    source = upload(client, auth)
    item = client.app.state.csv_workspace.get(auth["X-Demo-Session"])
    result = ask(client, auth, source["source_fingerprint"]).json()
    item.language_questions = client.app.state.csv_workspace.settings.maximum_language_questions
    rejected = ask(client, auth, source["source_fingerprint"])
    assert rejected.status_code == 429 and rejected.json()["agent_run"] is None
    replay = client.post(BASE + f"/history/{result['receipt']['query_id']}/rerun", headers=auth)
    assert replay.status_code == 200 and len(recording.requests) == 2


def test_csv_loads_its_own_optional_language_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "csv-language.json"
    path.write_text(config().model_dump_json())
    monkeypatch.setenv("T2D_CSV_LANGUAGE_CONFIG_FILE", str(path))
    monkeypatch.setenv("T2D_CLAUDE_API_KEY", "synthetic-config-secret")
    app = create_app(
        Settings(database_path=tmp_path / "demo.db", ollama_enabled=False, ollama_required=False),
        csv_settings=CsvDemoSettings(enabled=True),
    )
    with TestClient(app) as client:
        auth = new_session(client)
        assert client.get(BASE + "/state", headers=auth).json()["interpreter"] == "claude"
    assert isinstance(app.state.csv_workspace.language, ClaudeRuntime)


def test_signed_internal_workflow_uses_claude_without_public_demo_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = private_config(tmp_path).model_copy(update={"claude": config()})
    recording, cloud = RecordingClaude(), RecordingCloud()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app = create_internal_app(
        private, transport_factory=lambda _: cloud, language_transport=recording.transport()
    )
    monkeypatch.setattr(
        app.state.verifier.keys, "get_signing_key_from_jwt", lambda _: SimpleNamespace(key=key.public_key())
    )
    with TestClient(app) as client:
        assert client.post("/v1/internal/chat", json=question()).status_code == 401
        assert not recording.requests
        response = client.post("/v1/internal/chat", headers=headers(key), json=question())
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["status"] == "ANSWERED" and result["agent_run"]["provider"] == "claude"
        assert result["receipt"]["cloud_job"]["billing_project"] == "example-project"
        assert len(cloud.jobs) == 1
        outbound = json.loads(json.loads(recording.requests[0].content)["messages"][0]["content"])
        assert "example-project" not in json.dumps(outbound)
        assert client.get("/v1/internal/language", headers=headers(key)).json()["provider"] == "claude"
        assert client.post(BASE + "/sessions").status_code == 401
