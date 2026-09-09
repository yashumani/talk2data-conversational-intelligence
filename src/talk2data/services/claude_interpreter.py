"""Claude proposes governed IDs; shared services retain data and numerical authority."""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any, Literal

from pydantic import BaseModel, Field

from talk2data.core.claude_config import ClaudeConfiguration
from talk2data.domain.models import AccessContext, TenantDomainPack
from talk2data.services.agent_runtime import AgentFailure, AgentRun
from talk2data.services.claude_transport import ClaudeTransport
from talk2data.services.interpreter import HeuristicQuestionInterpreter
from talk2data.services.language_contract import (
    SYSTEM,
    catalog_for,
    permitted_pack,
    schema_for,
    validate_proposal,
)
from talk2data.services.language_contract import BoundQuestionInterpreter as BoundQuestionInterpreter
from talk2data.services.language_contract import GovernedProposal as ClaudeProposal
from talk2data.services.secrets import EnvironmentSecretResolver, SecretResolutionError


class Usage(BaseModel):
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)
    cache_creation_input_tokens: int = Field(default=0, strict=True, ge=0)
    cache_read_input_tokens: int = Field(default=0, strict=True, ge=0)


def request_payload(question: str, pack: TenantDomainPack, config: ClaudeConfiguration) -> dict[str, Any]:
    return {
        "model": config.model,
        "system": SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": json.dumps({"catalog": catalog_for(pack), "question": question}, sort_keys=True),
            }
        ],
        "output_config": {"format": {"type": "json_schema", "schema": schema_for(pack)}},
    }


class ClaudeRuntime:
    provider: Literal["claude"] = "claude"

    def __init__(
        self, config: ClaudeConfiguration | None = None, transport: ClaudeTransport | None = None
    ) -> None:
        self.config = config or ClaudeConfiguration()
        self.active = 0
        self.transport = transport
        if self.config.enabled and transport is None:
            try:
                secret = EnvironmentSecretResolver().resolve(self.config.secret_ref)
            except SecretResolutionError as exc:
                raise ValueError("Claude is enabled but its configured secret is unavailable.") from exc
            self.transport = ClaudeTransport(secret)

    def describe(self) -> dict[str, object]:
        return {
            "provider": "claude" if self.config.enabled else "rules",
            "status": "CONFIGURED_NOT_LIVE_VERIFIED" if self.config.enabled else "NOT_CONFIGURED",
            "sends_questions": self.config.enabled,
            "sends_csv_rows": False,
        }

    async def propose(
        self, question: str, pack: TenantDomainPack, access: AccessContext, run: AgentRun
    ) -> ClaudeProposal:
        if not self.config.enabled or self.transport is None:
            raise AgentFailure("CLAUDE_NOT_CONFIGURED", "Claude is not configured.")
        if self.active >= self.config.maximum_concurrent_requests:
            raise AgentFailure(
                "LANGUAGE_CAPACITY", "Language interpretation capacity is occupied; retry later."
            )
        self.active += 1
        try:
            allowed = permitted_pack(pack, access, self.config)
            recognized = HeuristicQuestionInterpreter().interpret(question, pack).proposal
            if set(recognized.candidate_metric_ids) - {m.id for m in allowed.metrics} or set(
                recognized.candidate_entity_ids
            ) - {d.id for d in allowed.entities}:
                raise AgentFailure(
                    "LANGUAGE_CONTEXT_DENIED",
                    "The named business context is not approved for this language-provider scope.",
                    403,
                )
            payload = request_payload(question, allowed, self.config)
            if len(json.dumps(payload).encode()) > self.config.maximum_prompt_bytes:
                raise AgentFailure(
                    "PROMPT_LIMIT",
                    "The question and approved definitions exceed the language input limit.",
                    422,
                )
            counted, _ = await self.transport.request(
                "messages/count_tokens", payload, min(run.remaining(), self.config.request_timeout_seconds)
            )
            count = counted.get("input_tokens")
            if type(count) is not int or count < 0:
                raise AgentFailure("PROVIDER_SCHEMA", "Claude returned an invalid token count.", 502)
            if count > self.config.maximum_input_tokens:
                raise AgentFailure("INPUT_TOKEN_LIMIT", "The language input token limit was reached.", 422)
            while True:
                run.reserve(count, self.config.maximum_output_tokens)
                run.report.usage.usage_complete = False
                try:
                    body, _ = await self.transport.request(
                        "messages",
                        {**payload, "max_tokens": self.config.maximum_output_tokens},
                        min(run.remaining(), self.config.request_timeout_seconds),
                    )
                except AgentFailure as exc:
                    if not exc.retryable or run.report.usage.model_calls >= run.limits.maximum_model_calls:
                        raise
                    delay = 1.0
                    if exc.retry_after is not None:
                        try:
                            delay = float(exc.retry_after)
                        except ValueError:
                            raise AgentFailure(
                                "RETRY_AFTER_INVALID", "Claude requested an unsupported retry delay."
                            ) from exc
                    if not math.isfinite(delay) or delay < 0 or delay > min(5, run.remaining()):
                        raise AgentFailure(
                            "RETRY_DELAY_LIMIT", "Claude retry delay exceeds the request budget."
                        ) from exc
                    await asyncio.sleep(delay)
                    continue
                return self._validate_response(body, allowed, run)
        finally:
            self.active -= 1

    def _validate_response(
        self, body: dict[str, Any], pack: TenantDomainPack, run: AgentRun
    ) -> ClaudeProposal:
        try:
            usage = Usage.model_validate(body["usage"])
            consumed_input = (
                usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens
            )
            run.report.usage.input_tokens += consumed_input
            run.report.usage.output_tokens += usage.output_tokens
            # Retry reservations remain charged when failed-attempt usage is unknown.
            run.report.usage.usage_complete = run.report.usage.model_calls == 1
            if (
                consumed_input > self.config.maximum_input_tokens
                or usage.output_tokens > self.config.maximum_output_tokens
                or run.report.usage.reserved_tokens
                - run.last_reservation
                + consumed_input
                + usage.output_tokens
                > run.limits.maximum_total_tokens
            ):
                raise AgentFailure(
                    "OBSERVED_TOKEN_LIMIT",
                    "Claude usage exceeded the configured limit; no data query was released.",
                )
            model = body["model"]
            if not isinstance(model, str) or not (
                model == self.config.model or model.startswith(str(self.config.model) + "-")
            ):
                raise ValueError("Unexpected model")
            run.report.model = model
            if body.get("stop_reason") != "end_turn":
                raise AgentFailure(
                    "PROVIDER_INCOMPLETE",
                    "Claude declined or did not finish a valid interpretation. Please refine the question.",
                    422,
                )
            blocks = body["content"]
            if not isinstance(blocks, list) or len(blocks) != 1 or blocks[0].get("type") != "text":
                raise ValueError("Expected one text result")
            return validate_proposal(blocks[0]["text"], pack)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise AgentFailure(
                "PROVIDER_SCHEMA", "Claude returned an invalid governed interpretation.", 502
            ) from exc
