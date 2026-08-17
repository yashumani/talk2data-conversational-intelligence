from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from talk2data.domain.models import AccessContext


class MemoryType(StrEnum):
    SESSION = "SESSION"
    USER_PREFERENCE = "USER_PREFERENCE"
    INVESTIGATION = "INVESTIGATION"
    BUSINESS_DEFINITION = "BUSINESS_DEFINITION"
    BUSINESS_DECISION = "BUSINESS_DECISION"
    POLICY = "POLICY"
    BUSINESS_EVENT = "BUSINESS_EVENT"
    EXTERNAL_INTELLIGENCE = "EXTERNAL_INTELLIGENCE"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"


class MemoryQuery(BaseModel):
    tenant_id: str
    memory_types: set[MemoryType] = Field(default_factory=set)
    domain_ids: set[str] = Field(default_factory=set)
    metric_ids: set[str] = Field(default_factory=set)
    entity_ids: set[str] = Field(default_factory=set)
    effective_at: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)


class MemoryEvidence(BaseModel):
    memory_id: UUID
    memory_type: MemoryType
    source_id: str
    content: str
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    status: str
    authority_level: int
    provenance: dict[str, str] = Field(default_factory=dict)


class ContextCoverageReceipt(BaseModel):
    coverage_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tenant_id: str
    domain_pack_version: str
    partitions_requested: list[str]
    partitions_searched: list[str]
    latest_ingestion_watermark: datetime | None = None
    incomplete_sources: list[str] = Field(default_factory=list)
    policy_exclusions: list[str] = Field(default_factory=list)
    conflicting_knowledge_ids: list[str] = Field(default_factory=list)
    coverage_status: str


class MemoryProvider(Protocol):
    async def retrieve(
        self,
        query: MemoryQuery,
        access: AccessContext,
    ) -> tuple[list[MemoryEvidence], ContextCoverageReceipt]: ...
