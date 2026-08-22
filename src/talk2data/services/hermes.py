from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class HermesRuntimeError(RuntimeError):
    """Raised when the controlled Hermes runtime cannot complete a request."""


@dataclass(frozen=True)
class HermesConfiguration:
    base_url: str
    api_key: str
    timeout_seconds: float


class HermesGatewayClient:
    """HTTP adapter for a local Hermes Agent API server.

    The client is intentionally narrow. It does not grant data or memory access; Hermes can only use
    tools separately exposed by the Talk2Data policy and connector gateways.
    """

    def __init__(self, configuration: HermesConfiguration) -> None:
        self._configuration = configuration

    async def health(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=min(self._configuration.timeout_seconds, 10.0)) as client:
                response = await client.get(f"{self._configuration.base_url}/health")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return False, f"Hermes Agent is unavailable: {exc}"
        return True, "Hermes Agent gateway is reachable."

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        system_instruction: str | None = None,
    ) -> str:
        request_messages: list[dict[str, str]] = []
        if system_instruction:
            request_messages.append({"role": "system", "content": system_instruction})
        request_messages.extend(messages)
        payload: dict[str, Any] = {
            "model": "hermes-agent",
            "messages": request_messages,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self._configuration.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self._configuration.timeout_seconds) as client:
                response = await client.post(
                    f"{self._configuration.base_url}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise HermesRuntimeError(f"Hermes Agent request failed: {exc}") from exc
        if not isinstance(content, str) or not content.strip():
            raise HermesRuntimeError("Hermes Agent returned an empty response")
        return content
