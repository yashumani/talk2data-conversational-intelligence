"""Gemini proposes governed IDs; it never receives data rows or executes a tool."""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any, Literal

from pydantic import BaseModel, Field

from talk2data.core.gemini_config import GeminiConfiguration
from talk2data.domain.models import AccessContext, TenantDomainPack
from talk2data.services.agent_runtime import AgentFailure, AgentRun
from talk2data.services.gemini_transport import GeminiTransport
from talk2data.services.interpreter import HeuristicQuestionInterpreter
from talk2data.services.language_contract import (
    SYSTEM,
    GovernedProposal,
    catalog_for,
    permitted_pack,
    schema_for,
    validate_proposal,
)
from talk2data.services.secrets import EnvironmentSecretResolver, SecretResolutionError


class GeminiUsage(BaseModel):
    promptTokenCount: int = Field(strict=True, ge=0)
    candidatesTokenCount: int = Field(strict=True, ge=0)
    thoughtsTokenCount: int = Field(default=0, strict=True, ge=0)
    totalTokenCount: int = Field(strict=True, ge=0)
    cachedContentTokenCount: int = Field(default=0, strict=True, ge=0)
    toolUsePromptTokenCount: int = Field(default=0, strict=True, ge=0)


def request_payload(question: str, pack: TenantDomainPack, config: GeminiConfiguration) -> dict[str, Any]:
    generation: dict[str, Any] = {
        "candidateCount": 1,
        "maxOutputTokens": config.maximum_output_tokens,
        "responseMimeType": "application/json",
        "responseJsonSchema": schema_for(pack),
    }
    if config.thinking_level is not None:
        generation["thinkingConfig"] = {
            "thinkingLevel": config.thinking_level.upper(),
            "includeThoughts": False,
        }
    return {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": json.dumps({"catalog": catalog_for(pack), "question": question}, sort_keys=True)}
                ],
            }
        ],
        "generationConfig": generation,
    }


class GeminiRuntime:
    provider: Literal["gemini"] = "gemini"

    def __init__(
        self, config: GeminiConfiguration | None = None, transport: GeminiTransport | None = None
    ) -> None:
        self.config = config or GeminiConfiguration()
        self.transport, self.active = transport, 0
        if self.config.enabled and transport is None:
            try:
                secret = EnvironmentSecretResolver().resolve(self.config.secret_ref)
            except SecretResolutionError as exc:
                raise ValueError("Gemini is enabled but its configured secret is unavailable.") from exc
            self.transport = GeminiTransport(secret)

    def describe(self) -> dict[str, object]:
        return {
            "provider": "gemini" if self.config.enabled else "rules",
            "status": "CONFIGURED_NOT_LIVE_VERIFIED" if self.config.enabled else "NOT_CONFIGURED",
            "sends_questions": self.config.enabled,
            "sends_csv_rows": False,
            "data_policy": self.config.data_policy,
        }

    async def propose(
        self, question: str, pack: TenantDomainPack, access: AccessContext, run: AgentRun
    ) -> GovernedProposal:
        if not self.config.enabled or self.transport is None or self.config.model is None:
            raise AgentFailure("GEMINI_NOT_CONFIGURED", "Gemini is not configured.")
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
                raise AgentFailure("PROMPT_LIMIT", "The approved language input exceeds its byte limit.", 422)
            counted = await self.transport.request(
                self.config.model,
                "countTokens",
                {"generateContentRequest": {"model": f"models/{self.config.model}", **payload}},
                min(run.remaining(), self.config.request_timeout_seconds),
            )
            count = counted.get("totalTokens")
            if type(count) is not int or count < 0:
                raise AgentFailure("PROVIDER_SCHEMA", "Gemini returned an invalid token count.", 502)
            if count > self.config.maximum_input_tokens:
                raise AgentFailure("INPUT_TOKEN_LIMIT", "The language input token limit was reached.", 422)
            while True:
                run.reserve(count, self.config.maximum_output_tokens)
                try:
                    body = await self.transport.request(
                        self.config.model,
                        "generateContent",
                        payload,
                        min(run.remaining(), self.config.request_timeout_seconds),
                    )
                except AgentFailure as exc:
                    if not exc.retryable or run.report.usage.model_calls >= run.limits.maximum_model_calls:
                        raise
                    try:
                        delay = 1.0 if exc.retry_after is None else float(exc.retry_after)
                    except ValueError:
                        raise AgentFailure(
                            "RETRY_AFTER_INVALID", "Gemini requested an unsupported retry delay."
                        ) from exc
                    if not math.isfinite(delay) or delay < 0 or delay > min(5, run.remaining()):
                        raise AgentFailure(
                            "RETRY_DELAY_LIMIT", "Gemini retry delay exceeds the request budget."
                        ) from exc
                    await asyncio.sleep(delay)
                    continue
                return self._validate_response(body, allowed, run)
        finally:
            self.active -= 1

    def _validate_response(
        self, body: dict[str, Any], pack: TenantDomainPack, run: AgentRun
    ) -> GovernedProposal:
        try:
            if body.get("promptFeedback", {}).get("blockReason"):
                raise AgentFailure("PROVIDER_INCOMPLETE", "Gemini declined the interpretation.", 422)
            usage = GeminiUsage.model_validate(body["usageMetadata"])
            output = usage.candidatesTokenCount + usage.thoughtsTokenCount
            if (
                usage.totalTokenCount != usage.promptTokenCount + output
                or usage.cachedContentTokenCount > usage.promptTokenCount
                or usage.toolUsePromptTokenCount
            ):
                raise ValueError("Inconsistent usage")
            run.report.usage.input_tokens += usage.promptTokenCount
            run.report.usage.output_tokens += output
            run.report.usage.usage_complete = run.report.usage.model_calls == 1
            if (
                usage.promptTokenCount > self.config.maximum_input_tokens
                or output > self.config.maximum_output_tokens
                or run.report.usage.reserved_tokens - run.last_reservation + usage.totalTokenCount
                > run.limits.maximum_total_tokens
            ):
                raise AgentFailure(
                    "OBSERVED_TOKEN_LIMIT", "Gemini usage exceeded the run limit; no data query was released."
                )
            model = body["modelVersion"]
            if not isinstance(model, str) or not (
                model == self.config.model or model.startswith(str(self.config.model) + "-")
            ):
                raise ValueError("Unexpected model")
            run.report.model = model
            candidates = body["candidates"]
            if not isinstance(candidates, list) or len(candidates) != 1:
                raise ValueError("Expected one candidate")
            candidate = candidates[0]
            if candidate.get("finishReason") != "STOP":
                raise AgentFailure(
                    "PROVIDER_INCOMPLETE", "Gemini did not finish a valid interpretation.", 422
                )
            content = candidate["content"]
            parts = content["parts"]
            if (
                content.get("role") != "model"
                or not isinstance(parts, list)
                or len(parts) != 1
                or set(parts[0]) - {"text", "thoughtSignature"}
                or not isinstance(parts[0]["text"], str)
            ):
                raise ValueError("Expected a text-only proposal without tools or thoughts")
            return validate_proposal(parts[0]["text"], pack)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise AgentFailure(
                "PROVIDER_SCHEMA", "Gemini returned an invalid governed interpretation.", 502
            ) from exc
