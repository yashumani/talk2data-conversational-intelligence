"""Synthetic Gemini wire responses; no credentials, network or cloud connections."""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import SecretStr

from talk2data.core.gemini_config import GeminiConfiguration
from talk2data.services.gemini_interpreter import GeminiRuntime
from talk2data.services.gemini_transport import GeminiTransport
from tests.claude_support import proposal


def config(**updates: Any) -> GeminiConfiguration:
    return GeminiConfiguration.model_validate(
        {
            "enabled": True,
            "model": "gemini-3-flash-preview",
            "allow_preview": True,
            "egress_approved": True,
            "allowed_tenants": ["demo-telecom"],
            "allowed_metric_ids": ["MOBILE_ACTIVATIONS"],
            **updates,
        }
    )


def message(**updates: Any) -> dict[str, Any]:
    return {
        "modelVersion": "gemini-3-flash-preview",
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"role": "model", "parts": [{"text": json.dumps(proposal())}]},
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 1000,
            "candidatesTokenCount": 80,
            "thoughtsTokenCount": 20,
            "totalTokenCount": 1100,
        },
        **updates,
    }


class RecordingGemini:
    def __init__(self, responses: list[Any] | None = None, count: Any = 1000) -> None:
        self.responses = list(responses or [])
        self.count = count
        self.requests: list[httpx.Request] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "generativelanguage.googleapis.com"
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": self.count})
        value = self.responses.pop(0) if self.responses else message()
        if isinstance(value, BaseException):
            raise value
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)

    def transport(self) -> GeminiTransport:
        return GeminiTransport(SecretStr("synthetic-gemini-secret"), httpx.MockTransport(self.handle))

    def runtime(self, **updates: Any) -> GeminiRuntime:
        return GeminiRuntime(config(**updates), self.transport())
