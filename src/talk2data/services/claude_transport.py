"""Direct Anthropic HTTPS port with bounded bodies, explicit timeouts and no implicit retries."""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import SecretStr

from talk2data.services.agent_runtime import AgentFailure


class ClaudeTransport:
    def __init__(self, secret: SecretStr, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._secret, self._transport = secret, transport

    async def request(
        self, path: str, payload: dict[str, Any], request_deadline_seconds: float
    ) -> tuple[dict[str, Any], str | None]:
        if path not in {"messages", "messages/count_tokens"}:
            raise AgentFailure("PROVIDER_PATH", "The language-provider operation is not allowed.")
        headers = {
            "x-api-key": self._secret.get_secret_value(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=request_deadline_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST", "https://api.anthropic.com/v1/" + path, json=payload, headers=headers
                ) as response:
                    if response.status_code != 200:
                        # Provider bodies may contain submitted data; never propagate them.
                        code = (
                            "PROVIDER_RATE_LIMIT" if response.status_code == 429 else "PROVIDER_UNAVAILABLE"
                        )
                        failure = AgentFailure(
                            code,
                            "Claude is unavailable. No alternate provider or source was used.",
                        )
                        failure.retry_after = response.headers.get("retry-after")
                        failure.retryable = response.status_code in {429, 529}
                        raise failure
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > 65536:
                            raise AgentFailure(
                                "PROVIDER_RESPONSE_LIMIT", "Claude returned an oversized response.", 502
                            )
                    data = json.loads(chunks)
                    if not isinstance(data, dict):
                        raise ValueError("Expected an object")
                    return data, response.headers.get("request-id")
        except httpx.TimeoutException as exc:
            raise AgentFailure(
                "PROVIDER_TIMEOUT", "Claude timed out; no automatic retry or data query was performed.", 504
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentFailure(
                "PROVIDER_UNAVAILABLE", "Claude is temporarily unavailable; no alternate provider was used."
            ) from exc
        except (ValueError, UnicodeError) as exc:
            raise AgentFailure("PROVIDER_SCHEMA", "Claude returned an invalid response.", 502) from exc
