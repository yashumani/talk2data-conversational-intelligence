from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from talk2data.api.runtime_security import RuntimeAdmission
from talk2data.bootstrap import create_app
from talk2data.core.config import Settings
from talk2data.core.csv_config import CsvDemoSettings


def public_settings(**updates: Any) -> Settings:
    values = {
        "runtime_profile": "public_synthetic",
        "ollama_enabled": False,
        "ollama_required": False,
        "hermes_enabled": False,
        "hermes_api_key": None,
        "cors_allowed_origins": ["http://testserver"],
    }
    values.update(updates)
    return Settings(**values)


def scope(
    method: str = "GET", path: str = "/", headers: list[tuple[bytes, bytes]] | None = None
) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }


async def invoke(
    middleware: RuntimeAdmission,
    request_scope: dict[str, Any],
    messages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    incoming = list(messages or [{"type": "http.request", "body": b"", "more_body": False}])
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return incoming.pop(0) if incoming else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await middleware(request_scope, receive, send)
    return sent


async def complete_app(
    _: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    await receive()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok", "more_body": False})


def status(messages: list[dict[str, Any]]) -> int:
    return int(messages[0]["status"])


def test_public_settings_reject_external_authority_and_origins() -> None:
    with pytest.raises(ValidationError, match="exact allowed"):
        public_settings(cors_allowed_origins=[])
    with pytest.raises(ValidationError, match="exact http"):
        public_settings(cors_allowed_origins=["https://example.com/path"])
    with pytest.raises(ValidationError, match="wildcards"):
        public_settings(cors_allowed_origins=["https://*.example.com"])
    with pytest.raises(ValidationError, match="synthetic SQLite"):
        public_settings(data_backend="postgresql", postgres_dsn="postgresql://example.invalid")
    with pytest.raises(ValidationError, match="external model"):
        public_settings(ollama_enabled=True)
    with pytest.raises(ValidationError, match="external model"):
        public_settings(hermes_api_key="must-fail-even-disabled")
    with pytest.raises(ValidationError, match="tenant"):
        public_settings(default_tenant_id="external")
    with pytest.raises(ValidationError, match="packaged synthetic"):
        public_settings(domain_pack_directory=Path("external"))


@pytest.mark.asyncio
async def test_disabled_profile_blocks_non_health_and_allows_health() -> None:
    middleware = RuntimeAdmission(complete_app, Settings(ollama_enabled=False))
    assert status(await invoke(middleware, scope(path="/demo"))) == 503
    assert status(await invoke(middleware, scope(path="/health/live"))) == 200


@pytest.mark.asyncio
async def test_trusted_profile_bypasses_public_admission() -> None:
    middleware = RuntimeAdmission(
        complete_app, Settings(runtime_profile="trusted_local", ollama_enabled=False)
    )
    assert status(await invoke(middleware, scope(method="POST"))) == 200


@pytest.mark.asyncio
async def test_public_post_requires_exact_origin() -> None:
    middleware = RuntimeAdmission(complete_app, public_settings())
    assert status(await invoke(middleware, scope(method="POST"))) == 403
    denied = scope(method="POST", headers=[(b"origin", b"https://example.com")])
    assert status(await invoke(middleware, denied)) == 403
    allowed = scope(method="POST", headers=[(b"origin", b"http://testserver")])
    assert status(await invoke(middleware, allowed)) == 200


@pytest.mark.asyncio
async def test_public_rejects_invalid_and_oversized_content_lengths() -> None:
    middleware = RuntimeAdmission(complete_app, public_settings(public_maximum_request_bytes=4))
    invalid = scope(headers=[(b"content-length", b"invalid")])
    oversized = scope(headers=[(b"content-length", b"5")])
    assert status(await invoke(middleware, invalid)) == 400
    assert status(await invoke(middleware, oversized)) == 413


@pytest.mark.asyncio
async def test_public_counts_streamed_request_bytes() -> None:
    middleware = RuntimeAdmission(complete_app, public_settings(public_maximum_request_bytes=4))
    messages = [{"type": "http.request", "body": b"12345", "more_body": False}]
    assert status(await invoke(middleware, scope(), messages)) == 413


@pytest.mark.asyncio
async def test_public_bounds_rate_identities_and_concurrency() -> None:
    middleware = RuntimeAdmission(complete_app, public_settings(public_requests_per_minute=1))
    assert status(await invoke(middleware, scope())) == 200
    assert status(await invoke(middleware, scope())) == 429
    middleware._in_flight = middleware.settings.public_maximum_in_flight
    assert status(await invoke(middleware, scope())) == 429
    middleware._rates.clear()
    assert status(await invoke(middleware, scope())) == 503
    middleware._in_flight = 0
    for index in range(1026):
        middleware._admit_rate(str(index))
    assert len(middleware._rates) == 1024


@pytest.mark.asyncio
async def test_public_rejects_oversized_or_incomplete_responses() -> None:
    async def oversized(_: dict[str, Any], __: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"12345", "more_body": False})

    async def incomplete(_: dict[str, Any], __: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"x", "more_body": True})

    settings = public_settings(public_maximum_response_bytes=4)
    assert status(await invoke(RuntimeAdmission(oversized, settings), scope())) == 502
    assert status(await invoke(RuntimeAdmission(incomplete, settings), scope())) == 502


@pytest.mark.asyncio
async def test_public_rejects_malformed_response_and_timeout() -> None:
    async def malformed(_: dict[str, Any], __: Any, send: Any) -> None:
        await send({"type": "websocket.send", "text": "wrong protocol"})

    async def stalled(_: dict[str, Any], __: Any, ___: Any) -> None:
        await asyncio.sleep(1)

    assert status(await invoke(RuntimeAdmission(malformed, public_settings()), scope())) == 502
    deadline = public_settings(public_response_timeout_seconds=0.01)
    assert status(await invoke(RuntimeAdmission(stalled, deadline), scope())) == 504


def test_public_app_rejects_csv_composition_and_redacts_readiness(tmp_path: Path) -> None:
    settings = public_settings(database_path=tmp_path / "public.db")
    with pytest.raises(ValueError, match="cannot compose"):
        create_app(settings, csv_settings=CsvDemoSettings(enabled=True))
    with TestClient(create_app(settings, csv_settings=CsvDemoSettings(enabled=False))) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        payload = response.json()
        assert set(payload["components"]) == {
            "domain_packs",
            "physical_mappings",
            "session_store",
            "synthetic_connector",
            "external_models",
        }
        assert all(
            component["detail"] is None and component["metadata"] == {}
            for component in payload["components"].values()
        )
        assert client.get("/demo").status_code == 200


def test_default_app_is_fail_closed(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "disabled.db", ollama_enabled=False)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/demo").status_code == 503
