from __future__ import annotations

from uuid import uuid4

import pytest

from talk2data.services.interpreter import InterpretationError


@pytest.mark.parametrize("path", ["/v1/chat/demo", "/v1/questions/evaluate", "/v1/query-plans/compile"])
def test_all_question_entry_points_enforce_tenant_and_session_ownership(client, full_access, path):
    payload = {"question": "Mobile activations last month", "access_context": full_access, "use_llm": False}
    response = client.post(path, json=payload)
    assert response.status_code == 200
    session = response.json()["session_id"]
    assert client.post(path, json=payload | {"session_id": session}).status_code == 200
    assert client.post(path, json=payload | {"session_id": str(uuid4())}).status_code == 404
    assert (
        client.post(
            path,
            json=payload | {"session_id": session, "access_context": full_access | {"user_id": "intruder"}},
        ).status_code
        == 403
    )
    assert (
        client.post(
            path, json=payload | {"access_context": full_access | {"tenant_id": "missing"}}
        ).status_code
        == 404
    )


@pytest.mark.parametrize("path", ["/v1/chat/demo", "/v1/questions/evaluate", "/v1/query-plans/compile"])
def test_required_interpretation_failure_has_consistent_503_without_internal_details(
    client, full_access, monkeypatch, path
):
    async def fail(*args, **kwargs):
        raise InterpretationError("private-provider.internal refused token test-secret")

    monkeypatch.setattr(client.app.state.admissibility_engine, "evaluate", fail)
    response = client.post(
        path, json={"question": "Mobile activations", "access_context": full_access, "use_llm": True}
    )
    assert response.status_code == 503
    assert "private-provider" not in response.text and "test-secret" not in response.text


def test_lookup_and_template_errors_are_explicit(client, full_access):
    admin = full_access | {"roles": ["TALK2DATA_ADMIN"]}
    assert client.get("/", follow_redirects=False).headers["location"] == "/demo"
    assert (
        client.get(
            f"/v1/sessions/{uuid4()}", headers={"X-Tenant-ID": "demo-telecom", "X-User-ID": "test"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/connectors/catalog", json={"access_context": full_access, "connector_id": "missing"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/physical-mappings/list", json={"access_context": admin | {"tenant_id": "missing"}}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/physical-mappings/connector", json={"access_context": admin, "connector_id": "missing"}
        ).status_code
        == 404
    )
    assert (
        client.post("/v1/runtime-packages/template", json={"access_context": full_access}).status_code == 403
    )
    assert (
        client.post(
            "/v1/runtime-packages/template", json={"access_context": admin | {"tenant_id": "missing"}}
        ).status_code
        == 404
    )
    response = client.post("/v1/runtime-packages/template", json={"access_context": admin})
    assert response.status_code == 200
    assert response.json()["domain_pack"]["tenant_id"] == "demo-telecom"


@pytest.mark.parametrize("ready", [True, False])
def test_readiness_reports_optional_provider_status(client, ready):
    class Provider:
        async def health(self):
            return ready, "provider state"

    client.app.state.ollama_client = Provider()
    client.app.state.hermes_client = Provider()
    response = client.get("/health/ready").json()
    assert response["components"]["ollama"]["status"] == ("ready" if ready else "degraded")
    assert response["components"]["hermes"]["status"] == ("ready" if ready else "degraded")


def test_chat_returns_compilation_failure_without_execution(client, full_access):
    response = client.post(
        "/v1/chat/demo",
        json={
            "question": "Postpaid churn by cell site last month",
            "access_context": full_access,
            "use_llm": False,
            "as_of": "2026-08-17T12:00:00Z",
        },
    ).json()
    assert response["status"] == "INVALID"
    assert response["receipt"] is None and response["answer"] is None
