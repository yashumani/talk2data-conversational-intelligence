from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from talk2data.domain.models import (
    BusinessQueryIR,
    QueryCompilationRequest,
    QueryCompilationStatus,
    QuestionDecision,
)


class ChatStatus(StrEnum):
    ANSWERED = "ANSWERED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN"
    DENIED = "DENIED"
    NO_SOURCE = "NO_SOURCE"
    SOURCE_NOT_READY = "SOURCE_NOT_READY"
    CONTEXT_NOT_CONNECTED = "CONTEXT_NOT_CONNECTED"
    INVALID = "INVALID"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class DemoChatRequest(QueryCompilationRequest):
    """End-to-end chat request for the synthetic, receipt-backed demo runtime."""

    include_debug: bool = True


class QueryReceipt(BaseModel):
    receipt_id: UUID = Field(default_factory=uuid4)
    query_id: UUID
    decision_id: UUID
    plan_hash: str
    connector_id: str
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_snapshot: datetime
    coverage_start: date
    coverage_end: date
    resolved_start: date
    resolved_end: date
    comparison_start: date | None = None
    comparison_end: date | None = None
    row_count: int = Field(ge=0)
    result_rows: list[dict[str, Any]]
    result_hash: str
    sql_hash: str
    data_quality_status: str
    data_quality_checks: list[str] = Field(default_factory=list)
    policy_decision_id: str
    warnings: list[str] = Field(default_factory=list)


class VerificationReport(BaseModel):
    status: VerificationStatus
    checks: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class CertifiedClaim(BaseModel):
    claim_id: UUID = Field(default_factory=uuid4)
    statement: str
    metric_id: str
    dimensions: dict[str, str] = Field(default_factory=dict)
    value: float
    formatted_value: str
    comparison_value: float | None = None
    formatted_comparison_value: str | None = None
    absolute_change: float | None = None
    percent_change: float | None = None
    receipt_id: UUID


class CertifiedAnswer(BaseModel):
    headline: str
    text: str
    claims: list[CertifiedClaim] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)


class DemoChatResponse(BaseModel):
    status: ChatStatus
    session_id: UUID
    message: str
    decision: QuestionDecision
    compilation_status: QueryCompilationStatus | None = None
    query_ir: BusinessQueryIR | None = None
    receipt: QueryReceipt | None = None
    verification: VerificationReport | None = None
    answer: CertifiedAnswer | None = None
    ai_model: str | None = None
    synthetic_data: bool = True
    context_used: bool = False
    warnings: list[str] = Field(default_factory=list)
