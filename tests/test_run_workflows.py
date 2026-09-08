from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from talk2data.core.config import Settings
from talk2data.core.csv_config import CsvDemoSettings
from talk2data.domain.runs import RunRequest
from talk2data.main import create_app
from talk2data.services.csv_workspace import CsvDemoWorkspace
from tests.claude_support import RecordingClaude, config
from tests.test_csv_demo import new_session, sample, upload

BASE = "/v1/demo/csv"


def application(path: Path, **kwargs: Any) -> Any:
    return create_app(
        Settings(database_path=path.parent / "legacy.db", ollama_enabled=False, ollama_required=False),
        csv_settings=CsvDemoSettings(enabled=True, state_database_path=path),
        **kwargs,
    )


def payload(client: TestClient, auth: dict[str, str], **updates: Any) -> dict[str, Any]:
    state = client.get(BASE + "/state", headers=auth).json()
    return {
        "client_request_id": str(uuid4()),
        "conversation_id": state["sync"]["conversation"]["conversation_id"],
        "expected_revision": state["sync"]["conversation"]["revision"],
        "question": "What were mobile activations by region last month?",
        "as_of": "2026-08-01T12:00:00Z",
        "source_fingerprint": state["source"]["source_fingerprint"],
        "definition_snapshot_id": state["definitions"]["snapshot_id"],
        **updates,
    }


def submit(client: TestClient, auth: dict[str, str], value: dict[str, Any]) -> dict[str, Any]:
    response = client.post(BASE + "/runs", headers=auth, json=value)
    assert response.status_code == 202, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def completed(client: TestClient, auth: dict[str, str], identifier: str) -> dict[str, Any]:
    for _ in range(150):
        response = client.get(BASE + "/runs/" + identifier, headers=auth)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        result = response.json()
        if result["status"] in {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}:
            return result
        time.sleep(0.01)
    raise AssertionError("Run did not reach a terminal state.")


@pytest.fixture
def workspace(tmp_path: Path) -> Any:
    app = application(tmp_path / "csv.db")
    with TestClient(app) as client:
        yield app, client


def test_csv_durable_answer_replays_events_and_restores_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "csv.db"
    with TestClient(application(path)) as client:
        auth = new_session(client)
        source = upload(client, auth)
        value = payload(client, auth)
        accepted = submit(client, auth, value)
        result = completed(client, auth, accepted["run_id"])
        assert result["status"] == "COMPLETED", result
        assert result["result"]["receipt"]["result_rows"] == [{"REGION": "NORTHEAST", "value": 3100.0}]
        assert result["source_binding"] == source["source_fingerprint"]
        assert [step["role"] for step in result["progress"]["steps"]] == [
            "SEMANTIC_RESOLVER",
            "QUERY_PLANNER",
            "QUERY_EXECUTOR",
            "RESULT_VERIFIER",
            "ANSWER_COMPOSER",
        ]
        restored = submit(client, auth, value)
        assert restored == result
        state = client.get(BASE + "/state", headers=auth).json()
        assert state["last_response"] == result["result"] and state["sync"]["durable"]
        assert len(state["sync"]["runs"]) == 1 and state["sync"]["conversation"]["revision"] == 1
        full = client.get(BASE + f"/runs/{accepted['run_id']}/events", headers=auth)
        assert full.status_code == 200 and full.headers["cache-control"] == "no-store"
        events = [json.loads(line[6:]) for line in full.text.splitlines() if line.startswith("data: ")]
        assert [e["sequence"] for e in events] == list(range(1, result["sequence"] + 1))
        assert "result_rows" not in full.text and value["question"] not in full.text
        resumed = client.get(
            BASE + f"/runs/{accepted['run_id']}/events",
            headers={**auth, "Last-Event-ID": accepted["run_id"] + ":2"},
        )
        assert [
            json.loads(line[6:])["sequence"]
            for line in resumed.text.splitlines()
            if line.startswith("data: ")
        ] == list(range(3, result["sequence"] + 1))
        assert len(client.get(BASE + "/conversations", headers=auth).json()) == 1
        assert (
            len(client.get(BASE + "/conversations/" + value["conversation_id"], headers=auth).json()["runs"])
            == 1
        )
    assert auth["X-Demo-Session"].encode() not in path.read_bytes()
    with TestClient(application(path)) as client:
        state = client.get(BASE + "/state", headers=auth).json()
        assert state["source"] == source and state["last_response"] == result["result"]
        assert completed(client, auth, accepted["run_id"]) == result
        replacement = upload(client, auth, sample(amount=7))
        assert submit(client, auth, value) == result
        assert client.get(BASE + "/state", headers=auth).json()["source"] == replacement
        query_id = result["result"]["receipt"]["query_id"]
        historical = client.post(BASE + f"/history/{query_id}/rerun", headers=auth).json()
        assert historical["receipt"]["result_rows"] == result["result"]["receipt"]["result_rows"]
        assert historical["agent_run"]["usage"]["model_calls"] == 0
        assert client.post(BASE + "/clear", headers=auth).status_code == 204
    with TestClient(application(path)) as client:
        assert client.get(BASE + "/state", headers=auth).status_code == 401
        assert client.get(BASE + "/runs/" + accepted["run_id"], headers=auth).status_code == 401


@pytest.mark.parametrize("endpoint", ["", "/events", "/cancel"])
def test_run_reads_streams_and_cancellation_cannot_cross_sessions(workspace: Any, endpoint: str) -> None:
    _, client = workspace
    auth, other = new_session(client), new_session(client)
    upload(client, auth)
    accepted = submit(client, auth, payload(client, auth))
    completed(client, auth, accepted["run_id"])
    path = BASE + "/runs/" + accepted["run_id"] + endpoint
    response = client.post(path, headers=other) if endpoint == "/cancel" else client.get(path, headers=other)
    assert response.status_code == 404
    assert "3100" not in response.text


@pytest.mark.parametrize(
    "extra",
    [
        {"roles": ["ADMIN"]},
        {"connector_id": "bigquery"},
        {"model": "claude-other"},
        {"question": " "},
        {"expected_revision": -1},
        {"source_fingerprint": "file.csv"},
    ],
)
def test_invalid_durable_input_has_no_execution(workspace: Any, extra: Any) -> None:
    _, client = workspace
    auth = new_session(client)
    upload(client, auth)
    value = payload(client, auth, **extra)
    assert client.post(BASE + "/runs", headers=auth, json=value).status_code == 422
    assert client.get(BASE + "/state", headers=auth).json()["sync"]["runs"] == []


def test_source_revision_request_and_cursor_mismatches_fail_closed(workspace: Any) -> None:
    _, client = workspace
    auth = new_session(client)
    upload(client, auth)
    value = payload(client, auth)
    accepted = submit(client, auth, value)
    result = completed(client, auth, accepted["run_id"])
    for cursor in [str(uuid4()) + ":1", accepted["run_id"] + ":bad", accepted["run_id"] + ":999"]:
        assert (
            client.get(
                BASE + f"/runs/{accepted['run_id']}/events", headers={**auth, "Last-Event-ID": cursor}
            ).status_code
            == 409
        )
    assert client.get(BASE + f"/runs/{accepted['run_id']}/events?after=-1", headers=auth).status_code == 422
    assert (
        client.get(BASE + f"/runs/{accepted['run_id']}/events?after={result['sequence']}", headers=auth).text
        == ""
    )
    for update in [{"question": "A changed question"}, {"expected_revision": 1}]:
        assert client.post(BASE + "/runs", headers=auth, json={**value, **update}).status_code == 409
    assert (
        client.post(
            BASE + "/runs", headers=auth, json={**value, "client_request_id": str(uuid4())}
        ).status_code
        == 409
    )
    assert (
        client.post(
            BASE + "/runs", headers=auth, json=payload(client, auth, source_fingerprint="c" * 64)
        ).status_code
        == 409
    )
    assert (
        client.post(
            BASE + "/runs", headers=auth, json=payload(client, auth, conversation_id=str(uuid4()))
        ).status_code
        == 404
    )
    assert client.post(BASE + "/conversations", headers=auth).status_code == 409
    assert client.delete(BASE + "/conversations/" + value["conversation_id"], headers=auth).status_code == 409
    for headers in [{}, {"X-Demo-Session": "short"}]:
        assert client.get(BASE + "/conversations", headers=headers).status_code == 401


def test_running_csv_job_locks_source_and_cancels_without_saved_answer(
    workspace: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client = workspace
    entered = Event()
    original = app.state.csv_workspace._execute

    async def wait(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        await asyncio.Event().wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(app.state.csv_workspace, "_execute", wait)
    auth = new_session(client)
    upload(client, auth)
    value = payload(client, auth)
    accepted = submit(client, auth, value)
    assert entered.wait(3)
    assert submit(client, auth, value)["run_id"] == accepted["run_id"]
    assert (
        client.post(
            BASE + "/upload", headers={**auth, "Content-Type": "text/csv"}, content=sample(amount=7)
        ).status_code
        == 409
    )
    assert client.post(BASE + "/runs", headers=auth, json=payload(client, auth)).status_code == 409
    assert client.post(BASE + "/runs/" + accepted["run_id"] + "/cancel", headers=auth).status_code == 202
    final = completed(client, auth, accepted["run_id"])
    assert final["status"] == "CANCELLED" and final["result"] is None
    state = client.get(BASE + "/state", headers=auth).json()
    assert state["history"] == [] and state["last_response"] is None
    assert client.post(BASE + "/clear", headers=auth).status_code == 204


def test_provider_failure_is_saved_and_retrying_request_does_not_recall_model(tmp_path: Path) -> None:
    recording = RecordingClaude(responses=[httpx.Response(529, text="private provider body")])
    with TestClient(
        application(
            tmp_path / "csv.db", csv_language_config=config(), csv_language_transport=recording.transport()
        )
    ) as client:
        auth = new_session(client)
        upload(client, auth)
        value = payload(client, auth)
        accepted = submit(client, auth, value)
        final = completed(client, auth, accepted["run_id"])
        assert final["status"] == "FAILED" and final["error_code"] == "PROVIDER_UNAVAILABLE"
        assert "private provider body" not in json.dumps(final)
        assert submit(client, auth, value) == final
        assert len(recording.requests) == 2
        assert client.get(BASE + "/state", headers=auth).json()["history"] == []


def test_definition_revocation_blocks_saved_result_and_event_replay(workspace: Any) -> None:
    _, client = workspace
    auth = new_session(client)
    upload(client, auth)
    value = payload(client, auth)
    accepted = submit(client, auth, value)
    completed(client, auth, accepted["run_id"])
    view = client.get(BASE + "/state", headers=auth).json()["definitions"]
    assert (
        client.post(
            BASE + f"/definitions/snapshots/{view['snapshot_id']}/revoke",
            headers=auth,
            json={"expected_revision": view["revision"], "note": "Withdraw synthetic approval."},
        ).status_code
        == 204
    )
    for suffix in ["", "/events"]:
        assert client.get(BASE + "/runs/" + accepted["run_id"] + suffix, headers=auth).status_code == 409
    assert client.post(BASE + "/runs", headers=auth, json=value).status_code == 409
    assert client.get(BASE + "/state", headers=auth).json()["last_response"] is None


def test_checkpoint_expiry_and_capacity_survive_restart(tmp_path: Path) -> None:
    settings = CsvDemoSettings(enabled=True, state_database_path=tmp_path / "csv.db", maximum_sessions=1)
    first = CsvDemoWorkspace(settings)
    token = first.create_session()
    first.close()
    second = CsvDemoWorkspace(settings)
    with pytest.raises(RuntimeError, match="capacity"):
        second.create_session()
    assert second.get(token).conversation_id
    item = second.get(token)
    item.expires_wall = time.time() - 1
    item.expires_at = time.monotonic() - 1
    second.persist(token, item)
    second.close()
    third = CsvDemoWorkspace(settings)
    assert third.create_session() != token
    with pytest.raises(RuntimeError, match="expired"):
        third.get(token)
    third.close()
    with pytest.raises(ValidationError):
        CsvDemoSettings(state_database_path=Path("relative.db"))


async def test_restart_interrupts_accepted_csv_job_and_preserves_source(tmp_path: Path) -> None:
    settings = CsvDemoSettings(enabled=True, state_database_path=tmp_path / "csv.db")
    first = CsvDemoWorkspace(settings)
    token = first.create_session()
    async with first.lease(token) as item:
        source = await first.upload(item, sample())
    state = first.state(item)
    value = RunRequest(
        client_request_id=uuid4(),
        conversation_id=item.conversation_id,
        expected_revision=0,
        question="What were mobile activations last month?",
        as_of="2026-08-01T12:00:00Z",
        source_fingerprint=source["source_fingerprint"],
        definition_snapshot_id=state["definitions"]["snapshot_id"],
    )
    accepted = first.submit_run(token, value)
    await first.runs.close()
    first.close()
    second = CsvDemoWorkspace(settings)
    restored = second.check_run(token, accepted.run_id)
    assert restored.status == "INTERRUPTED" and restored.result is None
    assert second.state(second.get(token))["source"] == source
    assert second.submit_run(token, value) == restored
    second.close()
