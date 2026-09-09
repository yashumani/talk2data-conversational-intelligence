"""Bounded Gemini Developer API HTTPS transport; independent from BigQuery credentials."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import SecretStr

from talk2data.services.agent_runtime import AgentFailure


class GeminiTransport:
    def __init__(self, secret: SecretStr, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._secret, self._transport = secret, transport

    async def request(
        self, model: str, operation: str, payload: dict[str, Any], request_deadline_seconds: float
    ) -> dict[str, Any]:
        if operation not in {"countTokens", "generateContent"} or not re.fullmatch(
            r"gemini-[a-z0-9][a-z0-9.-]{2,99}", model
        ):
            raise AgentFailure("PROVIDER_PATH", "The language-provider operation is not allowed.")
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=request_deadline_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST",
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:{operation}",
                    json=payload,
                    headers={
                        "x-goog-api-key": self._secret.get_secret_value(),
                        "content-type": "application/json",
                    },
                ) as response:
                    if response.status_code != 200:
                        failure = AgentFailure(
                            "PROVIDER_RATE_LIMIT" if response.status_code == 429 else "PROVIDER_UNAVAILABLE",
                            "Gemini is unavailable. No alternate provider, model or source was used.",
                        )
                        failure.retry_after = response.headers.get("retry-after")
                        failure.retryable = response.status_code in {429, 503}
                        raise failure
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > 65536:
                            raise AgentFailure(
                                "PROVIDER_RESPONSE_LIMIT", "Gemini returned an oversized response.", 502
                            )
                    data = json.loads(chunks)
                    if not isinstance(data, dict):
                        raise ValueError("Expected an object")
                    return data
        except httpx.TimeoutException as exc:
            raise AgentFailure(
                "PROVIDER_TIMEOUT", "Gemini timed out; no automatic retry was performed.", 504
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentFailure("PROVIDER_UNAVAILABLE", "Gemini is temporarily unavailable.") from exc
        except (ValueError, UnicodeError) as exc:
            raise AgentFailure("PROVIDER_SCHEMA", "Gemini returned an invalid response.", 502) from exc
