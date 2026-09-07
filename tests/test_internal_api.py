from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient

from talk2data.core.config import Settings
from talk2data.core.csv_config import CsvDemoSettings
from talk2data.core.internal_config import IdentitySettings
from talk2data.domain.models import ClassificationLevel
from talk2data.internal.bootstrap import create_internal_app
from talk2data.internal.runtime import InternalQueryBusy
from talk2data.main import create_app
from talk2data.services.identity import IdentityUnavailable
from tests.internal_support import RecordingCloud, access, private_config, write_grants
from tests.test_internal_identity import signed_token


@pytest.fixture(scope="module")
def api_key() -> Any:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def internal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api_key: Any) -> Any:
    config = private_config(tmp_path)
    cloud = RecordingCloud()
    app = create_internal_app(config, transport_factory=lambda _: cloud)
    monkeypatch.setattr(
        app.state.verifier.keys,
        "get_signing_key_from_jwt",
        lambda _: SimpleNamespace(key=api_key.public_key()),
    )
    with TestClient(app) as client:
        yield app, client, cloud, config
    assert cloud.closed


def headers(key: Any, subject: str = "analyst") -> dict[str, str]:
    return {"Authorization": "Bearer " + signed_token(key, sub=subject)}


def question(**updates: Any) -> dict[str, Any]:
    return {
        "question": "What were mobile activations by region last month?",
        "as_of": "2026-08-01T12:00:00Z",
        **updates,
    }


def test_authenticated_internal_question_and_definition(internal: Any, api_key: Any) -> None:
    _, client, cloud, _ = internal
    auth = headers(api_key)
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").status_code == 401
    assert client.get("/health/ready", headers=auth).json()["profile"] == "internal"
    identity = client.get("/v1/internal/me", headers=auth)
    assert identity.json()["tenant_id"] == "demo-telecom"
    assert identity.headers["cache-control"] == "no-store"
    definitions = client.get("/v1/internal/metrics", headers=auth)
    assert any(d["id"] == "MOBILE_ACTIVATIONS" for d in definitions.json())
    response = client.post("/v1/internal/chat", headers=auth, json=question())
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["status"] == "ANSWERED" and result["verification"]["status"] == "VERIFIED", result
    assert result["receipt"]["result_rows"] == [{"REGION": "NORTHEAST", "value": 3100.0}]
    assert result["receipt"]["cloud_job"]["job_id"] == cloud.jobs[0]
    assert result["ai_model"] is None


def test_internal_queries_respect_a_lower_configured_row_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api_key: Any
) -> None:
    config = private_config(tmp_path)
    config = config.model_copy(update={"bigquery": config.bigquery.model_copy(update={"maximum_rows": 3})})
    cloud = RecordingCloud()
    app = create_internal_app(config, transport_factory=lambda _: cloud)
    monkeypatch.setattr(
        app.state.verifier.keys,
        "get_signing_key_from_jwt",
        lambda _: SimpleNamespace(key=api_key.public_key()),
    )
    with TestClient(app) as client:
        response = client.post("/v1/internal/chat", headers=headers(api_key), json=question())
        assert response.json()["result"]["status"] == "ANSWERED"
    assert cloud.statements[0].maximum_result_rows == 4


def test_signed_iap_header_uses_verified_es256_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = private_config(tmp_path)
    config = config.model_copy(
        update={
            "identity": IdentitySettings(
                issuer="https://cloud.google.com/iap",
                audience="/projects/123/global/backendServices/456",
                jwks_url="https://www.gstatic.com/iap/verify/public_key-jwk",
                algorithm="ES256",
                token_header="x-goog-iap-jwt-assertion",
                maximum_token_lifetime_seconds=660,
            )
        }
    )
    grants = json.loads(config.entitlements_path.read_text())
    grants["issuer"] = config.identity.issuer
    config.entitlements_path.write_text(json.dumps(grants))
    key = ec.generate_private_key(ec.SECP256R1())
    app = create_internal_app(config, transport_factory=lambda _: RecordingCloud())
    monkeypatch.setattr(
        app.state.verifier.keys, "get_signing_key_from_jwt", lambda _: SimpleNamespace(key=key.public_key())
    )
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": config.identity.issuer,
            "aud": config.identity.audience,
            "sub": "analyst",
            "iat": now,
            "exp": now + 600,
        },
        key,
        algorithm="ES256",
        headers={"kid": "iap-test"},
    )
    with TestClient(app) as client:
        assert client.get("/v1/internal/me", headers={"x-goog-iap-jwt-assertion": token}).status_code == 200
        assert client.get("/v1/internal/me", headers={"authorization": "Bearer " + token}).status_code == 401


@pytest.mark.parametrize(
    "key",
    [
        "tenant_id",
        "roles",
        "access_context",
        "connector_id",
        "sql",
        "session_id",
        "use_llm",
        "source_fingerprint",
        "billing_project",
    ],
)
def test_caller_authority_and_connection_overrides_are_rejected(
    internal: Any, api_key: Any, key: str
) -> None:
    _, client, cloud, _ = internal
    response = client.post(
        "/v1/internal/chat", headers=headers(api_key), json=question(**{key: "private-marker"})
    )
    assert response.status_code == 422
    assert "private-marker" not in response.text
    assert not cloud.jobs


@pytest.mark.parametrize("auth", [None, "Basic credential", "Bearer", "Bearer ", "Bearer invalid"])
def test_missing_or_invalid_identity_is_not_a_demo_fallback(internal: Any, auth: str | None) -> None:
    _, client, cloud, _ = internal
    response = client.post(
        "/v1/internal/chat", headers={} if auth is None else {"Authorization": auth}, json=question()
    )
    assert response.status_code == 401 and not cloud.jobs


def test_duplicate_headers_and_untrusted_identity_headers(internal: Any, api_key: Any) -> None:
    _, client, cloud, _ = internal
    token = headers(api_key)["Authorization"]
    assert (
        client.get(
            "/v1/internal/me", headers=[("Authorization", token), ("Authorization", token)]
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/v1/internal/me", headers={"X-Goog-Authenticated-User-Email": "admin@example.test"}
        ).status_code
        == 401
    )
    assert not cloud.jobs


def test_legacy_and_csv_endpoints_are_not_mounted(internal: Any, api_key: Any) -> None:
    _, client, cloud, _ = internal
    for path in ["/v1/demo/csv/sessions", "/v1/chat/demo", "/v1/query-plans/compile"]:
        assert client.post(path, headers=headers(api_key), json={}).status_code == 404
    for path in ["/demo", "/workspace/", "/docs", "/openapi.json"]:
        assert client.get(path, headers=headers(api_key)).status_code == 404
    assert not cloud.jobs


def test_scope_and_definition_visibility_are_server_owned(internal: Any, api_key: Any) -> None:
    _, client, cloud, config = internal
    limited = access().model_copy(update={"classification_clearance": ClassificationLevel.INTERNAL})
    write_grants(config.entitlements_path, limited)
    visible = client.get("/v1/internal/metrics", headers=headers(api_key)).json()
    assert "MOBILE_ACTIVATIONS" in {m["id"] for m in visible}
    assert "POSTPAID_CHURN" not in {m["id"] for m in visible}
    write_grants(config.entitlements_path, access().model_copy(update={"permitted_actions": set()}))
    assert client.get("/v1/internal/metrics", headers=headers(api_key)).status_code == 403
    assert client.post("/v1/internal/chat", headers=headers(api_key), json=question()).status_code == 403
    assert not cloud.jobs


def test_unknown_tenant_and_revoked_subject(internal: Any, api_key: Any) -> None:
    _, client, _, config = internal
    write_grants(config.entitlements_path, access(tenant="unconfigured-tenant"))
    assert client.get("/v1/internal/me", headers=headers(api_key)).status_code == 403
    write_grants(config.entitlements_path)
    assert client.get("/v1/internal/me", headers=headers(api_key)).status_code == 401


def test_identity_availability_errors_are_sanitized(
    internal: Any, api_key: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client, _, _ = internal

    async def unavailable(_: str) -> Any:
        raise IdentityUnavailable("PRIVATE-KEY-URL")

    monkeypatch.setattr(app.state.verifier, "verify", unavailable)
    response = client.get("/v1/internal/me", headers=headers(api_key))
    assert response.status_code == 503 and "PRIVATE-KEY-URL" not in response.text


def test_authority_is_rechecked_before_releasing_results(
    internal: Any, api_key: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client, cloud, config = internal
    execute = cloud.execute

    def revoke_during_query(*args: Any) -> Any:
        result = execute(*args)
        write_grants(config.entitlements_path, access().model_copy(update={"regions": {"SOUTHEAST"}}))
        return result

    monkeypatch.setattr(cloud, "execute", revoke_during_query)
    response = client.post("/v1/internal/chat", headers=headers(api_key), json=question())
    assert response.status_code == 403
    assert "3100" not in response.text


@pytest.mark.parametrize(
    "failure,status",
    [(InternalQueryBusy("occupied"), 409), (TimeoutError(), 504), (asyncio.CancelledError(), 409)],
)
def test_busy_timeout_and_cancellation_responses(
    internal: Any, api_key: Any, monkeypatch: pytest.MonkeyPatch, failure: BaseException, status: int
) -> None:
    app, client, _, _ = internal

    async def fail(**_: Any) -> Any:
        raise failure

    monkeypatch.setattr(app.state.runtime, "answer", fail)
    assert client.post("/v1/internal/chat", headers=headers(api_key), json=question()).status_code == status


def test_cancel_unknown_request_is_private(internal: Any, api_key: Any) -> None:
    _, client, _, _ = internal
    assert client.post(f"/v1/internal/queries/{uuid4()}/cancel", headers=headers(api_key)).status_code == 404


async def test_only_owner_can_cancel_and_active_requests_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api_key: Any
) -> None:
    config = private_config(tmp_path).model_copy(update={"maximum_active_queries": 1})
    cloud = RecordingCloud()
    cloud.gate = Event()
    app = create_internal_app(config, transport_factory=lambda _: cloud)
    monkeypatch.setattr(
        app.state.verifier.keys,
        "get_signing_key_from_jwt",
        lambda _: SimpleNamespace(key=api_key.public_key()),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        request_id = str(uuid4())
        task = asyncio.create_task(
            client.post("/v1/internal/chat", headers=headers(api_key), json=question(request_id=request_id))
        )
        assert await asyncio.to_thread(cloud.started.wait, 2)
        duplicate = await client.post(
            "/v1/internal/chat", headers=headers(api_key), json=question(request_id=request_id)
        )
        assert duplicate.status_code == 409
        occupied = await client.post("/v1/internal/chat", headers=headers(api_key), json=question())
        assert occupied.status_code == 409
        route = f"/v1/internal/queries/{request_id}/cancel"
        assert (await client.post(route, headers=headers(api_key, "second-analyst"))).status_code == 404
        assert (await client.post(route, headers=headers(api_key))).status_code == 202
        assert (await task).status_code == 409
        assert not app.state.runtime.active
    assert cloud.closed and cloud.cancellations


def test_internal_startup_rejects_missing_semantic_bindings_before_cloud_initialization(
    tmp_path: Path,
) -> None:
    config = private_config(tmp_path)
    payload = json.loads(config.bigquery_catalog_path.read_text())
    payload["mappings"][0]["metrics"].pop()
    config.bigquery_catalog_path.write_text(json.dumps(payload))
    calls = []
    with pytest.raises(ValueError, match="Every available"):
        create_internal_app(config, transport_factory=lambda settings: calls.append(settings))
    assert not calls


def test_startup_source_failure_closes_transport(tmp_path: Path) -> None:
    config = private_config(tmp_path)
    cloud = RecordingCloud()
    cloud.failure = ValueError("View schema mismatch")
    app = create_internal_app(config, transport_factory=lambda _: cloud)
    with pytest.raises(ValueError, match="schema"):
        with TestClient(app):
            pass
    assert cloud.closed


def test_internal_entrypoint_is_a_factory_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    config = private_config(tmp_path)
    app = create_internal_app(config, transport_factory=lambda _: RecordingCloud())
    monkeypatch.setattr("talk2data.internal.bootstrap.create_internal_app", lambda: app)
    assert importlib.import_module("talk2data.internal_main").app is app


def test_internal_factory_loads_explicit_private_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = private_config(tmp_path)
    config_path = tmp_path / "runtime.json"
    config_path.write_text(config.model_dump_json())
    monkeypatch.setenv("T2D_INTERNAL_CONFIG_FILE", str(config_path))
    app = create_internal_app(transport_factory=lambda _: RecordingCloud())
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200


def test_public_csv_profile_never_initializes_bigquery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(**_: Any) -> Any:
        raise AssertionError("The public demo must not initialize a GCP client")

    monkeypatch.setattr("google.cloud.bigquery.Client", forbidden)
    app = create_app(
        Settings(database_path=tmp_path / "demo.db", ollama_enabled=False, ollama_required=False),
        csv_settings=CsvDemoSettings(enabled=True),
    )
    with TestClient(app) as client:
        assert client.post("/v1/demo/csv/sessions").status_code == 201
        assert client.get("/v1/internal/me").status_code == 404
