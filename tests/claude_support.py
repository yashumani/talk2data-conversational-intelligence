"""Synthetic Claude HTTP responses and approved demo scope; no credentials or network dependency."""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import SecretStr

from talk2data.core.claude_config import ClaudeConfiguration
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import AccessContext, TenantDomainPack
from talk2data.services.claude_interpreter import ClaudeRuntime
from talk2data.services.claude_transport import ClaudeTransport

QUESTION = "What were mobile activations by region last month?"


def config(**updates: Any) -> ClaudeConfiguration:
    return ClaudeConfiguration.model_validate(
        {
            "enabled": True,
            "model": "claude-contract-test",
            "egress_approved": True,
            "allowed_tenants": ["demo-telecom"],
            "allowed_metric_ids": ["MOBILE_ACTIVATIONS"],
            **updates,
        }
    )


def pack() -> TenantDomainPack:
    registry = DomainPackRegistry()
    registry.load()
    return registry.get("demo-telecom")


def actor(**updates: Any) -> AccessContext:
    return AccessContext.model_validate(
        {
            "tenant_id": "demo-telecom",
            "user_id": "analyst",
            "roles": ["BI_MANAGER"],
            "regions": ["NORTHEAST"],
            "business_units": ["CONSUMER"],
            "permitted_actions": ["ASK_BUSINESS_QUESTIONS", "READ_AGGREGATED_DATA"],
            **updates,
        }
    )


def proposal(**updates: Any) -> dict[str, Any]:
    return {
        "metric_id": "MOBILE_ACTIVATIONS",
        "dimensions": ["REGION"],
        "intent": "METRIC_LOOKUP",
        "needs_clarification": False,
        **updates,
    }


def message(**updates: Any) -> dict[str, Any]:
    return {
        "id": "msg_synthetic",
        "type": "message",
        "role": "assistant",
        "model": "claude-contract-test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": json.dumps(proposal())}],
        "usage": {"input_tokens": 1000, "output_tokens": 80},
        **updates,
    }


class RecordingClaude:
    def __init__(self, responses: list[Any] | None = None, count: Any = 1000) -> None:
        self.responses = list(responses or [])
        self.count = count
        self.requests: list[httpx.Request] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "api.anthropic.com"
        if request.url.path.endswith("/count_tokens"):
            return httpx.Response(200, json={"input_tokens": self.count})
        value = self.responses.pop(0) if self.responses else message()
        if isinstance(value, BaseException):
            raise value
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)

    def transport(self) -> ClaudeTransport:
        return ClaudeTransport(SecretStr("synthetic-secret"), httpx.MockTransport(self.handle))

    def runtime(self, **updates: Any) -> ClaudeRuntime:
        return ClaudeRuntime(config(**updates), self.transport())
