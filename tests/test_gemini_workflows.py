from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError

from talk2data.core.config import Settings
from talk2data.core.csv_config import CsvDemoSettings
from talk2data.core.internal_config import InternalRuntimeConfig
from talk2data.internal.bootstrap import create_internal_app
from talk2data.main import create_app
from talk2data.services.gemini_interpreter import GeminiRuntime
from tests.claude_support import RecordingClaude
from tests.claude_support import config as claude_config
from tests.gemini_support import RecordingGemini, config
from tests.internal_support import RecordingCloud, private_config
from tests.test_csv_demo import ask, new_session, upload
from tests.test_internal_api import headers, question
from tests.test_run_workflows import application, completed, payload, submit

BASE = "/v1/demo/csv"


def test_csv_gemini_answer_and_saved_replay_survive_restart_and_provider_change(tmp_path):
    path = tmp_path / "csv.db"
    gemini = RecordingGemini()
    with TestClient(
        application(path, csv_language_config=config(), csv_language_transport=gemini.transport())
    ) as client:
        auth = new_session(client)
        source = upload(client, auth)
        state = client.get(BASE + "/state", headers=auth).json()
        assert state["interpreter"] == "gemini" and not state["internal_connections_available"]
        assert state["language"]["data_policy"] == "synthetic_demo"
        result = ask(client, auth, source["source_fingerprint"]).json()
        assert result["agent_run"]["provider"] == "gemini" and result["status"] == "ANSWERED"
        assert result["receipt"]["result_rows"] == [{"REGION": "NORTHEAST", "value": 3100.0}]
        assert len(result["agent_run"]["steps"]) == 5 and len(gemini.requests) == 2
        saved = result["receipt"]["query_id"]
        for request in gemini.requests:
            outbound = json.loads(request.content)
            assert "3100" not in json.dumps(outbound) and "source_fingerprint" not in json.dumps(outbound)
    claude = RecordingClaude()
    with TestClient(
        application(path, csv_language_config=claude_config(), csv_language_transport=claude.transport())
    ) as client:
        assert client.get(BASE + "/state", headers=auth).json()["interpreter"] == "claude"
        replay = client.post(BASE + f"/history/{saved}/rerun", headers=auth)
        assert replay.status_code == 200, replay.text
        restored = replay.json()
        assert restored["receipt"]["result_rows"] == result["receipt"]["result_rows"]
        assert restored["semantic_context"] == result["semantic_context"]
        assert restored["ai_model"] == result["ai_model"] == "gemini-3-flash-preview"
        assert restored["agent_run"]["provider"] == "gemini"
        assert restored["agent_run"]["replayed_interpretation"]
        assert restored["agent_run"]["usage"]["model_calls"] == 0 and not claude.requests


def test_durable_gemini_failure_has_no_saved_answer_or_query_receipt(tmp_path):
    recording = RecordingGemini([httpx.Response(429, text="private-provider-details")])
    with TestClient(
        application(
            tmp_path / "csv.db", csv_language_config=config(), csv_language_transport=recording.transport()
        )
    ) as client:
        auth = new_session(client)
        upload(client, auth)
        accepted = submit(client, auth, payload(client, auth))
        failed = completed(client, auth, accepted["run_id"])
        assert failed["status"] == "FAILED" and failed["result"] is None
        assert failed["error_code"] == "PROVIDER_RATE_LIMIT"
        assert "private-provider-details" not in json.dumps(failed)
        state = client.get(BASE + "/state", headers=auth).json()
        assert state["last_response"] is None and state["history"] == []
        assert len(recording.requests) == 2


def test_gemini_file_selection_is_backend_only_and_disabled_csv_never_resolves_it(tmp_path, monkeypatch):
    path = tmp_path / "gemini.json"
    path.write_text(config().model_dump_json())
    monkeypatch.setenv("T2D_CSV_LANGUAGE_CONFIG_FILE", str(path))
    monkeypatch.setenv("T2D_GEMINI_API_KEY", "synthetic-private-value")
    settings = Settings(database_path=tmp_path / "reference.db", ollama_enabled=False, ollama_required=False)
    app = create_app(settings, csv_settings=CsvDemoSettings(enabled=True))
    with TestClient(app) as client:
        auth = new_session(client)
        state = client.get(BASE + "/state", headers=auth)
        assert state.json()["interpreter"] == "gemini" and "synthetic-private-value" not in state.text
    assert isinstance(app.state.csv_workspace.language, GeminiRuntime)
    path.unlink()
    monkeypatch.delenv("T2D_GEMINI_API_KEY")
    with TestClient(create_app(settings, csv_settings=CsvDemoSettings(enabled=False))) as disabled:
        assert disabled.app.state.csv_workspace is None


def test_internal_gemini_requires_enterprise_policy_and_excludes_a_second_provider(tmp_path):
    raw = private_config(tmp_path).model_dump(mode="json")
    raw["gemini"] = config().model_dump(mode="json")
    with pytest.raises(ValidationError, match="enterprise data policy"):
        InternalRuntimeConfig.model_validate(raw)
    raw["gemini"]["data_policy"] = "approved_enterprise"
    accepted = InternalRuntimeConfig.model_validate(raw)
    assert accepted.language_configuration.provider == "gemini"
    raw["claude"] = claude_config().model_dump(mode="json")
    with pytest.raises(ValidationError, match="exactly one"):
        InternalRuntimeConfig.model_validate(raw)


def test_signed_internal_gemini_keeps_bigquery_identity_and_rows_separate(tmp_path, monkeypatch):
    raw = private_config(tmp_path).model_dump(mode="json")
    raw["gemini"] = config(data_policy="approved_enterprise").model_dump(mode="json")
    recording, cloud = RecordingGemini(), RecordingCloud()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app = create_internal_app(
        InternalRuntimeConfig.model_validate(raw),
        transport_factory=lambda _: cloud,
        language_transport=recording.transport(),
    )
    monkeypatch.setattr(
        app.state.verifier.keys, "get_signing_key_from_jwt", lambda _: SimpleNamespace(key=key.public_key())
    )
    with TestClient(app) as client:
        assert client.post("/v1/internal/chat", json=question()).status_code == 401
        assert not recording.requests and not cloud.jobs
        response = client.post("/v1/internal/chat", headers=headers(key), json=question())
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["status"] == "ANSWERED" and result["agent_run"]["provider"] == "gemini"
        assert result["receipt"]["cloud_job"]["billing_project"] == "example-project"
        assert len(cloud.jobs) == 1
        for request in recording.requests:
            outbound = request.content.decode()
            assert "example-project" not in outbound and "synthetic-private-value" not in outbound
        assert client.get("/v1/internal/language", headers=headers(key)).json()["provider"] == "gemini"
        assert client.post(BASE + "/sessions").status_code == 401
