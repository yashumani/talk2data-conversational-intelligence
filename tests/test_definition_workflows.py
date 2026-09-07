from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from talk2data.core.config import Settings
from talk2data.core.csv_config import CsvDemoSettings
from talk2data.core.internal_config import InternalRuntimeConfig
from talk2data.domain.governance import DefinitionEdit
from talk2data.domain.models import ClassificationLevel
from talk2data.internal.bootstrap import create_internal_app
from talk2data.main import create_app
from talk2data.services.csv_workspace import CsvDemoWorkspace
from talk2data.services.definition_governance import EDIT, PUBLISH, REVIEW, REVOKE
from talk2data.services.definition_store import DefinitionUnavailable
from talk2data.services.demo_chat import DemoChatService
from tests.internal_support import RecordingCloud, access, private_config, write_grants
from tests.test_csv_demo import ask, new_session, sample, upload
from tests.test_internal_api import headers, question

BASE = "/v1/demo/csv"


@pytest.fixture
def client(tmp_path: Path) -> Any:
    app = create_app(
        Settings(database_path=tmp_path / "sessions.db", ollama_enabled=False, ollama_required=False),
        csv_settings=CsvDemoSettings(enabled=True),
    )
    with TestClient(app) as client:
        yield client


def view(client: TestClient, auth: dict[str, str]) -> dict[str, Any]:
    return client.get(BASE + "/state", headers=auth).json()


def edit(snapshot_id: str, **updates: Any) -> dict[str, Any]:
    return {
        "base_snapshot_id": snapshot_id,
        "kind": "METRIC",
        "definition_id": "MOBILE_ACTIVATIONS",
        "name": "Mobile Activations",
        "definition": "Completed activations observed in the selected CSV days.",
        "owner": "Demo Sales Analytics",
        "aliases": ["new connections"],
        "reason": "Clarify business meaning.",
        **updates,
    }


def publish(client: TestClient, auth: dict[str, str], **updates: Any) -> dict[str, Any]:
    current = view(client, auth)["definitions"]
    response = client.post(
        BASE + "/definitions/drafts", headers=auth, json=edit(current["snapshot_id"], **updates)
    )
    assert response.status_code == 201, response.text
    draft = response.json()
    for action in ("submit", "approve", "publish"):
        response = client.post(
            BASE + f"/definitions/drafts/{draft['draft_id']}/{action}",
            headers=auth,
            json={"expected_revision": draft["revision"], "note": "Reviewed against synthetic CSV contract."},
        )
        assert response.status_code == 200, response.text
        draft = response.json()
    return view(client, auth)["definitions"]


def test_csv_publication_binds_current_definitions_and_preserves_old_answers(client: TestClient) -> None:
    auth = new_session(client)
    source = upload(client, auth)
    initial = view(client, auth)
    assert initial["connections"] == [
        {"id": "csv", "status": "AVAILABLE"},
        {"id": "bigquery", "status": "NOT_CONFIGURED"},
    ]
    original = ask(
        client,
        auth,
        source["source_fingerprint"],
        definition_snapshot_id=initial["definitions"]["snapshot_id"],
    ).json()
    pin = original["semantic_context"]
    assert pin["metric"]["definition_version"] == 1
    assert [dimension["id"] for dimension in pin["dimensions"]] == ["REGION"]
    assert original["receipt"]["definition_snapshot_id"] == pin["snapshot_id"]
    published = publish(client, auth)
    assert published["mode"] == "DEMO_SINGLE_USER"
    assert published["snapshot_id"] != pin["snapshot_id"]
    assert view(client, auth)["last_response"]["semantic_context"] == pin
    stale = ask(client, auth, source["source_fingerprint"], definition_snapshot_id=pin["snapshot_id"])
    assert stale.status_code == 409 and stale.headers["cache-control"] == "no-store"
    fresh = ask(
        client, auth, source["source_fingerprint"], definition_snapshot_id=published["snapshot_id"]
    ).json()
    assert fresh["semantic_context"]["metric"]["definition_version"] == 2
    assert fresh["semantic_context"]["metric"]["semantic_version"] == pin["metric"]["semantic_version"]
    assert fresh["receipt"]["result_rows"] == original["receipt"]["result_rows"]
    dimension = publish(
        client,
        auth,
        kind="DIMENSION",
        definition_id="REGION",
        name="Sales Region",
        definition="The reporting territory assigned to the activation.",
        aliases=["territory"],
    )
    after = ask(
        client, auth, source["source_fingerprint"], definition_snapshot_id=dimension["snapshot_id"]
    ).json()
    assert after["semantic_context"]["dimensions"][0]["definition_version"] == 2
    assert after["query_ir"]["semantic_snapshot_hash"] != fresh["query_ir"]["semantic_snapshot_hash"]


def test_historical_rerun_keeps_its_csv_and_snapshot_after_replacement(client: TestClient) -> None:
    auth, other = new_session(client), new_session(client)
    source = upload(client, auth)
    original = ask(client, auth, source["source_fingerprint"]).json()
    run_id = original["receipt"]["query_id"]
    publish(client, auth)
    replacement = upload(client, auth, sample(amount=7))
    response = client.post(BASE + f"/history/{run_id}/rerun", headers=auth)
    assert response.status_code == 200, response.text
    reproduced = response.json()
    assert reproduced["receipt"]["result_rows"] == original["receipt"]["result_rows"]
    assert reproduced["semantic_context"] == original["semantic_context"]
    assert reproduced["receipt"]["source_fingerprint"] == source["source_fingerprint"]
    assert view(client, auth)["source"] == replacement
    assert view(client, auth)["last_response"] is None
    assert client.post(BASE + f"/history/{run_id}/rerun", headers=other).status_code == 409
    for _ in range(4):
        assert ask(client, auth, replacement["source_fingerprint"]).status_code == 200
    assert len(view(client, auth)["history"]) == 4
    assert client.post(BASE + f"/history/{run_id}/rerun", headers=auth).status_code == 409
    assert client.post(BASE + "/clear", headers=auth).status_code == 204
    assert client.post(BASE + f"/history/{run_id}/rerun", headers=auth).status_code == 401


def test_revocation_removes_current_answer_and_blocks_new_and_saved_queries(client: TestClient) -> None:
    auth = new_session(client)
    source = upload(client, auth)
    result = ask(client, auth, source["source_fingerprint"]).json()
    current = view(client, auth)["definitions"]
    endpoint = BASE + f"/definitions/snapshots/{current['snapshot_id']}/revoke"
    response = client.post(
        endpoint,
        headers=auth,
        json={"expected_revision": current["revision"], "note": "Definition requires correction."},
    )
    assert response.status_code == 204
    state = view(client, auth)
    assert state["last_response"] is None
    assert state["definitions"]["status"] == "REVOKED"
    assert ask(client, auth, source["source_fingerprint"]).status_code == 409
    assert (
        client.post(BASE + f"/history/{result['receipt']['query_id']}/rerun", headers=auth).status_code == 409
    )
    corrected = publish(client, auth)
    assert corrected["status"] == "PUBLISHED"
    assert ask(client, auth, source["source_fingerprint"]).json()["status"] == "ANSWERED"


def test_definition_api_rejects_invalid_edits_cross_session_drafts_and_transitions(
    client: TestClient,
) -> None:
    auth, other = new_session(client), new_session(client)
    data = edit(view(client, auth)["definitions"]["snapshot_id"])
    endpoint = BASE + "/definitions/drafts"
    for update in (
        {"formula": "SUM(secret)"},
        {"roles": ["ADMIN"]},
        {"owner": " "},
        {"effective_from": "2026-01-01"},
    ):
        assert client.post(endpoint, headers=auth, json={**data, **update}).status_code == 422
    assert client.post(endpoint, headers=auth, json={**data, "definition_id": "UNKNOWN"}).status_code == 404
    draft = client.post(endpoint, headers=auth, json=data).json()
    route = endpoint + f"/{draft['draft_id']}/submit"
    body = {"expected_revision": 1, "note": "Ready for review."}
    assert client.post(route, headers=other, json=body).status_code == 404
    assert client.post(route, headers=auth, json={**body, "note": ""}).status_code == 422
    assert client.post(route, headers=auth, json=body).status_code == 200
    assert client.post(route, headers=auth, json=body).status_code == 409


@pytest.mark.parametrize("revoke", [False, True])
async def test_mid_query_publication_keeps_pin_but_revocation_blocks_release(
    monkeypatch: pytest.MonkeyPatch, revoke: bool
) -> None:
    workspace = CsvDemoWorkspace(CsvDemoSettings(enabled=True))
    item = workspace.get(workspace.create_session())
    await workspace.upload(item, sample())
    service, actor = item.definitions, workspace._access(item)
    before = service.resolve(actor)
    original_answer = DemoChatService.answer

    async def mutate_then_answer(self: DemoChatService, request: Any) -> Any:
        if revoke:
            service.revoke(
                actor, before.snapshot_id, service.view(actor)["revision"], "Withdrawn during query."
            )
        else:
            draft = service.create_draft(actor, DefinitionEdit.model_validate(edit(before.snapshot_id)))
            for action in ("submit", "approve", "publish"):
                draft = service.transition(actor, draft.draft_id, action, draft.revision, "Demo review.")
        return await original_answer(self, request)

    monkeypatch.setattr(DemoChatService, "answer", mutate_then_answer)
    assert item.dataset
    args = {
        "question": question()["question"],
        "as_of": datetime(2026, 8, 1, 12, tzinfo=UTC),
        "source_fingerprint": item.dataset.fingerprint,
    }
    if revoke:
        with pytest.raises(DefinitionUnavailable):
            await workspace.answer(item, **args)
        assert item.last_response is None and not item.history
    else:
        response = await workspace.answer(item, **args)
        assert response.semantic_context and response.semantic_context.snapshot_id == before.snapshot_id
        assert service.resolve(actor).snapshot_id != before.snapshot_id
    workspace.close()


def test_expiration_deletes_definition_namespace() -> None:
    workspace = CsvDemoWorkspace(CsvDemoSettings(enabled=True))
    token = workspace.create_session()
    item = workspace.get(token)
    namespace = item.definitions.namespace
    item.expires_at = 0
    workspace.create_session()
    with pytest.raises(DefinitionUnavailable):
        workspace._definition_store.read(namespace)
    workspace.close()


def test_internal_governance_requires_server_grants_and_different_reviewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = private_config(tmp_path)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    author = access("author").model_copy(
        update={
            "classification_clearance": ClassificationLevel.RESTRICTED,
            "permitted_actions": access().permitted_actions | {EDIT, REVIEW, PUBLISH, REVOKE},
        }
    )
    reviewer = author.model_copy(update={"user_id": "reviewer"})
    write_grants(config.entitlements_path, author, reviewer, access())
    app = create_internal_app(config, transport_factory=lambda _: RecordingCloud())
    monkeypatch.setattr(
        app.state.verifier.keys, "get_signing_key_from_jwt", lambda _: SimpleNamespace(key=key.public_key())
    )
    base = "/v1/internal/definitions"
    auth = headers(key, "author")
    with TestClient(app) as client:
        assert client.get(base).status_code == 401
        initial = client.get(base, headers=auth).json()
        assert initial["mode"] == "SEPARATE_REVIEWER"
        data = edit(initial["snapshot_id"])
        assert client.post(base + "/drafts", headers=headers(key), json=data).status_code == 403
        created = client.post(base + "/drafts", headers=auth, json=data)
        assert created.status_code == 201, created.text
        draft = created.json()
        body = {"expected_revision": 1, "note": "Ready for independent review."}
        path = base + f"/drafts/{draft['draft_id']}"
        assert client.post(path + "/submit", headers=auth, json=body).status_code == 200
        body["expected_revision"] = 2
        assert client.post(path + "/approve", headers=auth, json=body).status_code == 403
        assert client.post(path + "/approve", headers=headers(key, "reviewer"), json=body).status_code == 200
        body["expected_revision"] = 3
        assert client.post(path + "/publish", headers=auth, json=body).status_code == 200
        current = client.get(base, headers=auth).json()
        ordinary = client.get(base, headers=headers(key)).json()
        assert ordinary["drafts"] == [] and ordinary["events"] == []
        assert all(d["classification"] != "RESTRICTED" for d in ordinary["dimensions"])
        assert (
            client.post(
                "/v1/internal/chat",
                headers=auth,
                json=question(definition_snapshot_id=initial["snapshot_id"]),
            ).status_code
            == 409
        )
        response = client.post(
            "/v1/internal/chat", headers=auth, json=question(definition_snapshot_id=current["snapshot_id"])
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["semantic_context"]["metric"]["definition_version"] == 2
        metrics = client.get("/v1/internal/metrics", headers=auth).json()
        assert next(m for m in metrics if m["id"] == "MOBILE_ACTIVATIONS")["definition_version"] == 2
        assert (
            client.post(
                base + f"/snapshots/{current['snapshot_id']}/revoke",
                headers=auth,
                json={"expected_revision": current["revision"], "note": "Withdraw approved definition."},
            ).status_code
            == 204
        )
        assert client.post("/v1/internal/chat", headers=auth, json=question()).status_code == 409
        assert client.post(BASE + "/sessions", headers=auth).status_code == 404


def test_internal_durable_store_path_must_be_absolute(tmp_path: Path) -> None:
    from pydantic import ValidationError

    config = private_config(tmp_path).model_dump()
    with pytest.raises(ValidationError, match="absolute"):
        InternalRuntimeConfig.model_validate({**config, "governance_database_path": "relative.db"})
    assert InternalRuntimeConfig.model_validate(
        {**config, "governance_database_path": str(tmp_path / "definitions.db")}
    ).governance_database_path
