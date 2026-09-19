from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from talk2data.core.config import RuntimeProfile, Settings


@dataclass
class _Rate:
    count: int
    reset_at: float


class _RequestTooLarge(Exception):
    pass


class _ResponseInvalid(Exception):
    pass


class RuntimeAdmission:
    """Fail-closed admission and bounded response buffering for public synthetic requests."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self._rates: OrderedDict[str, _Rate] = OrderedDict()
        self._in_flight = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        if self.settings.runtime_profile == RuntimeProfile.DISABLED and path not in {
            "/health/live",
            "/health/ready",
        }:
            await self._error(send, 503, "runtime profile is disabled")
            return
        if self.settings.runtime_profile != RuntimeProfile.PUBLIC_SYNTHETIC:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin1").lower(): value.decode("latin1") for key, value in scope.get("headers", [])
        }
        if scope.get("method") == "POST" and headers.get("origin") not in self.settings.cors_allowed_origins:
            await self._error(send, 403, "origin denied")
            return
        try:
            if int(headers.get("content-length", "0")) > self.settings.public_maximum_request_bytes:
                await self._error(send, 413, "request exceeded the configured limit")
                return
        except ValueError:
            await self._error(send, 400, "invalid content length")
            return
        identity = self._identity(scope)
        if not self._admit_rate(identity):
            await self._error(send, 429, "rate limit exceeded")
            return
        if self._in_flight >= self.settings.public_maximum_in_flight:
            await self._error(send, 503, "public runtime capacity reached")
            return
        self._in_flight += 1
        try:
            await self._buffered_call(scope, receive, send)
        except TimeoutError:
            await self._error(send, 504, "public runtime deadline exceeded")
        except _RequestTooLarge:
            await self._error(send, 413, "request exceeded the configured limit")
        except _ResponseInvalid:
            await self._error(send, 502, "runtime returned an invalid or oversized response")
        finally:
            self._in_flight -= 1

    async def _buffered_call(self, scope: Scope, receive: Receive, send: Send) -> None:
        request_size = 0
        messages: list[Message] = []
        response_size = 0

        async def bounded_receive() -> Message:
            nonlocal request_size
            message = await receive()
            if message["type"] == "http.request":
                request_size += len(message.get("body", b""))
                if request_size > self.settings.public_maximum_request_bytes:
                    raise _RequestTooLarge
            return message

        async def buffer(message: Message) -> None:
            nonlocal response_size
            if message["type"] not in {"http.response.start", "http.response.body"}:
                raise _ResponseInvalid
            if message["type"] == "http.response.body":
                response_size += len(message.get("body", b""))
                if response_size > self.settings.public_maximum_response_bytes:
                    raise _ResponseInvalid
            messages.append(message)

        async with asyncio.timeout(self.settings.public_response_timeout_seconds):
            await self.app(scope, bounded_receive, buffer)
        if not messages or messages[0]["type"] != "http.response.start":
            raise _ResponseInvalid
        bodies = [message for message in messages if message["type"] == "http.response.body"]
        if not bodies or bodies[-1].get("more_body", False):
            raise _ResponseInvalid
        for message in messages:
            await send(message)
            await asyncio.sleep(0)

    def _admit_rate(self, identity: str) -> bool:
        now = time.monotonic()
        expired = [key for key, rate in self._rates.items() if rate.reset_at <= now]
        for key in expired:
            self._rates.pop(key, None)
        while len(self._rates) >= 1024:
            self._rates.popitem(last=False)
        rate = self._rates.get(identity)
        if rate is None:
            self._rates[identity] = _Rate(count=1, reset_at=now + 60)
            return True
        rate.count += 1
        self._rates.move_to_end(identity)
        return rate.count <= self.settings.public_requests_per_minute

    @staticmethod
    def _identity(scope: Scope) -> str:
        client = scope.get("client")
        return str(client[0]) if client else "unknown"

    @staticmethod
    async def _error(send: Send, status: int, detail: str) -> None:
        body = ('{"detail":"' + detail + '"}').encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
