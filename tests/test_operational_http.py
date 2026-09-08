from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from talk2data.operations.http import HttpOperations, OperationalHttp, emit


def application(records: list[dict[str, object]]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(OperationalHttp, settings=HttpOperations(), sink=records.append)

    @app.post("/runs/{identifier}")
    async def run(identifier: str, request: Request) -> dict[str, bool]:
        assert await request.body()
        return {"accepted": True}

    return app


def test_internal_telemetry_uses_route_template_and_server_request_id_only() -> None:
    records: list[dict[str, object]] = []
    with TestClient(application(records)) as client:
        response = client.post(
            "/runs/private-run-id?query=secret-question",
            content=b"private-data",
            headers={"Authorization": "Bearer secret-token", "X-Request-ID": "untrusted-identifier"},
        )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-request-id"] != "untrusted-identifier"
        assert records[-1]["request_id"] == response.headers["x-request-id"]
        assert records[-1]["route"] == "/runs/{identifier}" and records[-1]["outcome"] == "COMPLETED"
        raw = json.dumps(records)
        assert all(
            value not in raw
            for value in (
                "private-run-id",
                "secret-question",
                "secret-token",
                "private-data",
                "untrusted-identifier",
            )
        )
        assert client.get("/secret-unregistered-path").status_code == 404
        assert records[-1]["route"] == "UNMATCHED"


async def exercise(
    messages: list[Any],
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    app: Any = None,
    settings: HttpOperations | None = None,
    method: str = "POST",
) -> tuple[list[Any], list[Any], OperationalHttp]:
    queue = deque(messages)
    sent, records = [], []

    async def receive() -> Any:
        value = queue.popleft()
        if isinstance(value, BaseException):
            raise value
        if value == "wait":
            await asyncio.Event().wait()
        return value

    async def send(message: Any) -> None:
        sent.append(message)

    async def echo(scope: Any, incoming: Any, outgoing: Any) -> None:
        value = await incoming()
        await outgoing(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"cache-control", b"public"), (b"x-request-id", b"bad")],
            }
        )
        await outgoing({"type": "http.response.body", "body": value["body"]})

    middleware = OperationalHttp(
        app or echo,
        settings or HttpOperations(maximum_body_bytes=4096, body_timeout_seconds=0.1),
        records.append,
    )
    await middleware({"type": "http", "method": method, "headers": headers or []}, receive, send)
    return sent, records, middleware


@pytest.mark.parametrize(
    "headers,expected",
    [
        ([(b"content-length", b"-1")], 400),
        ([(b"content-length", b"1"), (b"content-length", b"1")], 400),
        ([(b"content-length", b"9" * 12)], 400),
        ([(b"content-length", b"5000")], 413),
    ],
)
async def test_rejects_invalid_or_oversized_headers_without_reading_body(headers: Any, expected: int) -> None:
    sent, records, middleware = await exercise([], headers=headers)
    assert sent[0]["status"] == expected and records[-1]["status"] == expected
    assert middleware.inflight == 0


async def test_chunked_request_budget_timeout_framing_and_disconnect() -> None:
    sent, records, _ = await exercise(
        [
            {"type": "http.request", "body": b"a" * 4000, "more_body": True},
            {"type": "http.request", "body": b"b" * 100},
        ]
    )
    assert sent[0]["status"] == 413
    sent, _, _ = await exercise(["wait"])
    assert sent[0]["status"] == 408
    sent, _, _ = await exercise([{"type": "invalid"}])
    assert sent[0]["status"] == 400
    sent, records, _ = await exercise([{"type": "http.disconnect"}])
    assert not sent and records[-1]["status"] == 499 and records[-1]["outcome"] == "DISCONNECTED"


async def test_chunk_coalescing_and_stream_disconnect_preserve_asgi_contract() -> None:
    async def stream(scope: Any, receive: Any, send: Any) -> None:
        assert (await receive())["body"] == b"abcd"
        assert (await receive())["type"] == "http.disconnect"
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"event", "more_body": True})
        await send({"type": "http.response.body", "body": b""})

    sent, records, _ = await exercise(
        [
            {"type": "http.request", "body": b"ab", "more_body": True},
            {"type": "http.request", "body": b"cd"},
            {"type": "http.disconnect"},
        ],
        app=stream,
        method="UNSUPPORTED",
    )
    assert len(sent) == 3 and records[-1]["method"] == "OTHER" and records[-1]["outcome"] == "COMPLETED"


async def test_concurrent_capacity_rejection_does_not_consume_another_slot() -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    sent, records = [], []

    async def held(scope: Any, receive: Any, send: Any) -> None:
        entered.set()
        await release.wait()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> Any:
        return {"type": "http.request", "body": b""}

    async def send(message: Any) -> None:
        sent.append(message)

    middleware = OperationalHttp(held, HttpOperations(maximum_inflight=1), records.append)
    scope = {"type": "http", "method": "GET", "headers": []}
    task = asyncio.create_task(middleware(scope, receive, send))
    await entered.wait()
    await middleware(scope, receive, send)
    assert sent[0]["status"] == 503 and middleware.inflight == 1
    release.set()
    await task
    assert middleware.inflight == 0 and records[-1]["status"] == 204


async def test_cancellation_failure_and_logging_failure_do_not_leak_capacity() -> None:
    records = []

    async def fail(scope: Any, receive: Any, send: Any) -> None:
        raise RuntimeError("private-error")

    async def receive() -> Any:
        return {"type": "http.request", "body": b""}

    async def send(message: Any) -> None:
        pass

    middleware = OperationalHttp(fail, HttpOperations(), records.append)
    with pytest.raises(RuntimeError):
        await middleware({"type": "http", "method": "POST"}, receive, send)
    assert (
        middleware.inflight == 0
        and records[-1]["status"] == 500
        and "private-error" not in json.dumps(records)
    )

    async def cancel(scope: Any, receive: Any, send: Any) -> None:
        raise asyncio.CancelledError

    middleware.app = cancel
    with pytest.raises(asyncio.CancelledError):
        await middleware({"type": "http", "method": "POST"}, receive, send)
    assert middleware.inflight == 0 and records[-1]["status"] == 499

    def broken_sink(record: Any) -> None:
        raise OSError("telemetry unavailable")

    middleware.sink = broken_sink
    middleware.app = fail
    with pytest.raises(RuntimeError, match="private-error"):
        await middleware({"type": "http", "method": "POST"}, receive, send)


async def test_non_http_scope_is_forwarded_and_json_emitter_is_reusable() -> None:
    scopes = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        scopes.append(scope)

    async def receive() -> Any:
        return {}

    async def send(message: Any) -> None:
        pass

    await OperationalHttp(app, HttpOperations())({"type": "lifespan"}, receive, send)
    assert scopes == [{"type": "lifespan"}]
    emit({"event": "synthetic-operations-test"})
    emit({"event": "synthetic-operations-test"})
