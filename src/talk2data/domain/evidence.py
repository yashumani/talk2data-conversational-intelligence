from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EvidenceType(StrEnum):
    CERTIFIED_INTERNAL_DATA = "CERTIFIED_INTERNAL_DATA"
    CERTIFIED_EXTERNAL_DATA = "CERTIFIED_EXTERNAL_DATA"
    APPROVED_INTERNAL_KNOWLEDGE = "APPROVED_INTERNAL_KNOWLEDGE"
    LIVE_EXTERNAL_SOURCE = "LIVE_EXTERNAL_SOURCE"
    PRIOR_INVESTIGATION = "PRIOR_INVESTIGATION"


class ClaimType(StrEnum):
    CERTIFIED = "CERTIFIED"
    SUPPORTED = "SUPPORTED"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"


class EvidenceReceipt(BaseModel):
    evidence_id: UUID = Field(default_factory=uuid4)
    evidence_type: EvidenceType
    tenant_id: str
    source_id: str
    source_timestamp: datetime
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    classification: str
    policy_decision_id: str
    payload_hash: str
    payload: dict[str, Any]


class ApprovedClaim(BaseModel):
    claim_id: UUID = Field(default_factory=uuid4)
    claim_type: ClaimType
    statement: str
    evidence_ids: list[UUID] = Field(default_factory=list)
    confidence: str
    causality_status: str = "NOT_APPLICABLE"
    allowed_for_response: bool = False
