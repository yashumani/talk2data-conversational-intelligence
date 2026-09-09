"""Public run evidence contains execution stages and usage, never model reasoning or prompts."""

from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

AgentRole = Literal[
    "SEMANTIC_RESOLVER", "QUERY_PLANNER", "QUERY_EXECUTOR", "RESULT_VERIFIER", "ANSWER_COMPOSER"
]


class AgentStep(BaseModel):
    role: AgentRole
    tool: str
    sequence: int
    status: Literal["RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"] = "RUNNING"
    duration_ms: int = 0


class AgentUsage(BaseModel):
    model_calls: int = 0
    counted_input_tokens: int = 0
    reserved_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usage_complete: bool = True


class AgentRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID = Field(default_factory=uuid4)
    status: str = "RUNNING"
    steps: list[AgentStep] = Field(default_factory=list)
    usage: AgentUsage = Field(default_factory=AgentUsage)
    provider: Literal["rules", "claude", "gemini"] = "rules"
    model: str | None = None
    replayed_interpretation: bool = False
    error_code: str | None = None
