"""Bounded internal HTTP admission and operational records without request content."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from collections import deque
from collections.abc import Callable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class HttpOperations(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    maximum_body_bytes: int = Field(default=65536, ge=4096, le=1048576)
    body_timeout_seconds: float = Field(default=5, ge=0.1, le=30)
    maximum_inflight: int = Field(default=128, ge=1, le=1024)


def emit(record: dict[str, object]) -> None:
    logger = logging.getLogger("talk2data.operations")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    logger.info(json.dumps(record, separators=(",", ":")))


class OperationalHttp:
    def __init__(
        self, app: ASGIApp, settings: HttpOperations, sink: Callable[[dict[str, object]], None] = emit
    ) -> None:
        self.app, self.settings, self.sink = app, settings, sink
        self.inflight = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        identifier, started, status = str(uuid4()), time.monotonic(), 500
        outcome = "ERROR"
        counted = False

        async def respond(code: int, detail: str) -> None:
            await observed(
                {
                    "type": "http.response.start",
                    "status": code,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await observed({"type": "http.response.body", "body": json.dumps({"detail": detail}).encode()})

        async def observed(message: Message) -> None:
            nonlocal status, outcome
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in {b"x-request-id", b"cache-control"}
                ]
                message = {
                    **message,
                    "headers": [
                        *headers,
                        (b"x-request-id", identifier.encode()),
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                    ],
                }
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                outcome = "COMPLETED"

        try:
            if self.inflight >= self.settings.maximum_inflight:
                await respond(503, "HTTP capacity is occupied. Retry later.")
                return
            self.inflight += 1
            counted = True
            lengths = [v for k, v in scope.get("headers", []) if k.lower() == b"content-length"]
            if len(lengths) > 1 or (lengths and (not lengths[0].isdigit() or len(lengths[0]) > 10)):
                await respond(400, "Invalid content length.")
                return
            if lengths and int(lengths[0]) > self.settings.maximum_body_bytes:
                await respond(413, "Request body exceeds the internal API limit.")
                return
            body = bytearray()
            try:
                async with asyncio.timeout(self.settings.body_timeout_seconds):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            status = 499
                            outcome = "DISCONNECTED"
                            return
                        if message["type"] != "http.request":
                            await respond(400, "Invalid request body framing.")
                            return
                        chunk = message.get("body", b"")
                        if len(body) + len(chunk) > self.settings.maximum_body_bytes:
                            await respond(413, "Request body exceeds the internal API limit.")
                            return
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                await respond(408, "Request body was not received within the deadline.")
                return
            messages: deque[Message] = deque(
                [{"type": "http.request", "body": bytes(body), "more_body": False}]
            )

            async def buffered() -> Message:
                return messages.popleft() if messages else await receive()

            await self.app(scope, buffered, observed)
        except asyncio.CancelledError:
            status = 499
            outcome = "DISCONNECTED"
            raise
        except Exception:
            outcome = "ERROR"
            raise
        finally:
            if counted:
                self.inflight -= 1
            route = scope.get("route")
            # Only registered route templates are logged. Unknown paths and query strings are omitted.
            record: dict[str, object] = {
                "event": "http_request",
                "request_id": identifier,
                "method": scope["method"]
                if scope["method"] in {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}
                else "OTHER",
                "route": getattr(route, "path", "UNMATCHED"),
                "status": status,
                "outcome": outcome,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            }
            try:
                self.sink(record)
            except Exception:
                # Operational telemetry is best effort, unlike the transactional business journal.
                pass
