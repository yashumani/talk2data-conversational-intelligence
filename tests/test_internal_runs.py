from __future__ import annotations

import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from talk2data.domain.runs import principal
from talk2data.internal.bootstrap import create_internal_app
from tests.internal_support import RecordingCloud, access, private_config, write_grants
from tests.test_internal_api import headers

BASE = "/v1/internal"


@pytest.fixture(scope="module")
def signing_key() -> Any:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def application(config: Any, key: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, RecordingCloud]:
    cloud = RecordingCloud()
    app = create_internal_app(config, transport_factory=lambda _: cloud)
    monkeypatch.setattr(
        app.state.verifier.keys, "get_signing_key_from_jwt", lambda _: SimpleNamespace(key=key.public_key())
    )
    return app, cloud


@pytest.fixture
def internal(tmp_path: Path, signing_key: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    config = private_config(tmp_path).model_copy(update={"state_database_path": tmp_path / "runs.db"})
    app, cloud = application(config, signing_key, monkeypatch)
    with TestClient(app) as client:
        yield app, client, cloud, config, headers(signing_key)


def payload(client: TestClient, auth: dict[str, str], **updates: Any) -> dict[str, Any]:
    conversation = client.post(BASE + "/conversations", headers=auth)
    assert conversation.status_code == 201, conversation.text
    definitions = client.get(BASE + "/definitions", headers=auth)
    assert definitions.status_code == 200, definitions.text
    return {
        "client_request_id": str(uuid4()),
        "conversation_id": conversation.json()["conversation_id"],
        "expected_revision": 0,
        "question": "What were mobile activations by region last month?",
        "as_of": "2026-08-01T12:00:00Z",
        "definition_snapshot_id": definitions.json()["snapshot_id"],
        **updates,
    }


def wait(client: TestClient, auth: dict[str, str], identifier: str) -> dict[str, Any]:
    for _ in range(200):
        response = client.get(BASE + "/runs/" + identifier, headers=auth)
        assert response.status_code == 200, response.text
        result = response.json()
        if result["status"] in {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}:
            return result
        time.sleep(0.01)
    raise AssertionError("Internal run did not finish.")


def test_internal_durable_result_and_duplicate_request_use_one_cloud_job(
    internal: Any, signing_key: Any
) -> None:
    _, client, cloud, config, auth = internal
    value = payload(client, auth)
    accepted = client.post(BASE + "/runs", headers=auth, json=value)
    assert accepted.status_code == 202, accepted.text
    identifier = accepted.json()["run_id"]
    result = wait(client, auth, identifier)
    assert result["status"] == "COMPLETED", result
    assert result["result"]["receipt"]["result_rows"] == [{"REGION": "NORTHEAST", "value": 3100.0}]
    assert result["result"]["receipt"]["source_kind"] == "bigquery"
    assert client.post(BASE + "/runs", headers=auth, json=value).json() == result
    assert len(cloud.jobs) == 1
    stream = client.get(BASE + "/runs/" + identifier + "/events", headers=auth)
    assert stream.status_code == 200 and "result_rows" not in stream.text
    assert "request_id" not in stream.text and "3100" not in stream.text
    assert auth["Authorization"].split(" ")[1].encode() not in config.state_database_path.read_bytes()
    other = headers(signing_key, "second-analyst")
    for suffix in ["", "/events"]:
        assert client.get(BASE + "/runs/" + identifier + suffix, headers=other).status_code == 404
    assert client.post(BASE + "/runs/" + identifier + "/cancel", headers=other).status_code == 404
    assert client.post(BASE + "/runs/" + identifier + "/cancel", headers=auth).json()["status"] == "COMPLETED"
    assert client.delete(BASE + "/conversations/" + value["conversation_id"], headers=auth).status_code == 204
    assert client.get(BASE + "/runs/" + identifier, headers=auth).status_code == 404


def test_internal_terminal_answer_survives_restart_without_querying_again(
    tmp_path: Path, signing_key: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = private_config(tmp_path).model_copy(update={"state_database_path": tmp_path / "runs.db"})
    app, cloud = application(config, signing_key, monkeypatch)
    auth = headers(signing_key)
    with TestClient(app) as client:
        value = payload(client, auth)
        identifier = client.post(BASE + "/runs", headers=auth, json=value).json()["run_id"]
        result = wait(client, auth, identifier)
        assert result["status"] == "COMPLETED" and len(cloud.jobs) == 1
    replacement, new_cloud = application(config, signing_key, monkeypatch)
    with TestClient(replacement) as client:
        assert wait(client, auth, identifier) == result
        assert client.post(BASE + "/runs", headers=auth, json=value).json() == result
        assert new_cloud.jobs == []
        replacement.state.runtime.source_binding = "c" * 64
        assert client.get(BASE + "/runs/" + identifier, headers=auth).status_code == 403
        assert client.post(BASE + "/runs", headers=auth, json=value).status_code == 409


def test_changed_permissions_hide_prior_conversations_and_result_streams(internal: Any) -> None:
    _, client, _, config, auth = internal
    value = payload(client, auth)
    identifier = client.post(BASE + "/runs", headers=auth, json=value).json()["run_id"]
    wait(client, auth, identifier)
    write_grants(config.entitlements_path, access().model_copy(update={"regions": {"WEST"}}))
    assert client.get(BASE + "/conversations", headers=auth).json() == []
    assert client.get(BASE + "/runs/" + identifier, headers=auth).status_code == 404
    assert client.get(BASE + "/runs/" + identifier + "/events", headers=auth).status_code == 404
    write_grants(config.entitlements_path, access().model_copy(update={"permitted_actions": set()}))
    assert client.get(BASE + "/conversations", headers=auth).status_code == 403


def test_mid_run_permission_change_withholds_completed_warehouse_data(internal: Any) -> None:
    app, client, cloud, config, auth = internal
    cloud.gate = Event()
    value = payload(client, auth)
    identifier = client.post(BASE + "/runs", headers=auth, json=value).json()["run_id"]
    assert cloud.started.wait(3)
    write_grants(config.entitlements_path, access().model_copy(update={"regions": {"WEST"}}))
    cloud.gate.set()
    owner, scope = principal("internal", access())
    for _ in range(200):
        result = app.state.runtime.run_store.read(owner, scope, UUID(identifier))
        if result.status == "FAILED":
            break
        time.sleep(0.01)
    assert result.status == "FAILED" and result.result is None
    assert client.get(BASE + "/runs/" + identifier, headers=auth).status_code == 404


def test_internal_cancel_reaches_cloud_and_retains_no_answer(internal: Any) -> None:
    _, client, cloud, _, auth = internal
    cloud.gate = Event()
    value = payload(client, auth)
    identifier = client.post(BASE + "/runs", headers=auth, json=value).json()["run_id"]
    assert cloud.started.wait(3)
    response = client.post(BASE + "/runs/" + identifier + "/cancel", headers=auth)
    assert response.status_code == 202
    result = wait(client, auth, identifier)
    assert result["status"] == "CANCELLED" and result["result"] is None
    assert cloud.cancellations
    cloud.gate.set()


@pytest.mark.parametrize(
    "extra,status",
    [
        ({"source_fingerprint": "a" * 64}, 422),
        ({"roles": ["ADMIN"]}, 422),
        ({"connector_id": "csv"}, 422),
        ({"definition_snapshot_id": "c" * 64}, 404),
    ],
)
def test_internal_submission_cannot_change_binding_or_authority(
    internal: Any, extra: Any, status: int
) -> None:
    _, client, cloud, _, auth = internal
    value = payload(client, auth, **extra)
    response = client.post(BASE + "/runs", headers=auth, json=value)
    assert response.status_code == status, response.text
    assert cloud.jobs == []
