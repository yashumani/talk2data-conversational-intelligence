from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClassificationLevel(StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


CLASSIFICATION_RANK: dict[ClassificationLevel, int] = {
    ClassificationLevel.PUBLIC: 0,
    ClassificationLevel.INTERNAL: 1,
    ClassificationLevel.CONFIDENTIAL: 2,
    ClassificationLevel.RESTRICTED: 3,
}


class SourceStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_READY = "NOT_READY"


class QuestionVerdict(StrEnum):
    ACCEPT_INTERNAL = "ACCEPT_INTERNAL"
    ACCEPT_KNOWLEDGE = "ACCEPT_KNOWLEDGE"
    ACCEPT_EXTERNAL_AUGMENTED = "ACCEPT_EXTERNAL_AUGMENTED"
    CLARIFY = "CLARIFY"
    VALID_NO_SOURCE = "VALID_NO_SOURCE"
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN"
    INVALID_ANALYTIC_REQUEST = "INVALID_ANALYTIC_REQUEST"
    DENY = "DENY"
    CONFLICTING_DEFINITIONS = "CONFLICTING_DEFINITIONS"
    SOURCE_NOT_READY = "SOURCE_NOT_READY"


class QuestionIntent(StrEnum):
    METRIC_LOOKUP = "METRIC_LOOKUP"
    TREND_ANALYSIS = "TREND_ANALYSIS"
    COMPARISON = "COMPARISON"
    DRIVER_ANALYSIS = "DRIVER_ANALYSIS"
    KNOWLEDGE_LOOKUP = "KNOWLEDGE_LOOKUP"
    UNKNOWN = "UNKNOWN"


class DataStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIALLY_AVAILABLE = "PARTIALLY_AVAILABLE"
    NOT_CONNECTED = "NOT_CONNECTED"
    NOT_READY = "NOT_READY"
    NOT_REQUIRED = "NOT_REQUIRED"


class AuthorizationStatus(StrEnum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"


class InterpreterMode(StrEnum):
    RULES = "RULES"
    OLLAMA_AND_RULES = "OLLAMA_AND_RULES"
    OLLAMA_FAILED_RULES_FALLBACK = "OLLAMA_FAILED_RULES_FALLBACK"


class AccessContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=256)
    roles: set[str] = Field(default_factory=set)
    departments: set[str] = Field(default_factory=set)
    regions: set[str] = Field(default_factory=set)
    business_units: set[str] = Field(default_factory=set)
    classification_clearance: ClassificationLevel = ClassificationLevel.INTERNAL
    permitted_actions: set[str] = Field(default_factory=set)

    @field_validator(
        "roles", "departments", "regions", "business_units", "permitted_actions", mode="after"
    )
    @classmethod
    def normalize_set_values(cls, values: set[str]) -> set[str]:
        return {value.strip().upper() for value in values if value.strip()}


class DataSourceReference(BaseModel):
    connector_id: str
    status: SourceStatus = SourceStatus.AVAILABLE
    description: str | None = None


class BusinessDomain(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    classification: ClassificationLevel = ClassificationLevel.INTERNAL


class MetricDefinition(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    domain_id: str
    definition: str
    allowed_dimensions: list[str] = Field(default_factory=list)
    classification: ClassificationLevel = ClassificationLevel.INTERNAL
    source: DataSourceReference


class BusinessEntity(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    domain_id: str
    classification: ClassificationLevel = ClassificationLevel.INTERNAL


class ExternalAdjacency(BaseModel):
    id: str
    name: str
    phrases: list[str]
    anchor_metric_ids: list[str] = Field(default_factory=list)
    anchor_entity_ids: list[str] = Field(default_factory=list)
    description: str | None = None


class ExcludedDomainRule(BaseModel):
    id: str
    name: str
    phrases: list[str]
    explanation: str


class TenantDomainPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    tenant_name: str
    industry: str
    subindustries: list[str] = Field(default_factory=list)
    version: str
    status: str = "APPROVED"
    effective_from: datetime
    default_currency: str = "USD"
    default_calendar: str = "GREGORIAN"
    domains: list[BusinessDomain]
    metrics: list[MetricDefinition]
    entities: list[BusinessEntity]
    external_adjacencies: list[ExternalAdjacency] = Field(default_factory=list)
    excluded_domains: list[ExcludedDomainRule] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        return value.strip().upper()


class InterpretationProposal(BaseModel):
    """Untrusted language interpretation proposed by rules and/or a local model."""

    model_config = ConfigDict(extra="forbid")

    intent: QuestionIntent = QuestionIntent.UNKNOWN
    candidate_metric_ids: list[str] = Field(default_factory=list)
    candidate_entity_ids: list[str] = Field(default_factory=list)
    candidate_domain_ids: list[str] = Field(default_factory=list)
    candidate_dimensions: list[str] = Field(default_factory=list)
    external_topics: list[str] = Field(default_factory=list)
    ambiguous_terms: list[str] = Field(default_factory=list)
    requested_operation: str | None = None
    summary: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class InterpretationResult(BaseModel):
    proposal: InterpretationProposal
    mode: InterpreterMode
    matched_external_adjacency_ids: list[str] = Field(default_factory=list)
    matched_exclusion_ids: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=8000)
    access_context: AccessContext
    session_id: UUID | None = None
    use_llm: bool = True

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("question cannot be blank")
        return normalized


class QuestionDecision(BaseModel):
    decision_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tenant_id: str
    user_id: str
    verdict: QuestionVerdict
    recognized_intent: QuestionIntent
    domain_anchor_ids: list[str] = Field(default_factory=list)
    candidate_metric_ids: list[str] = Field(default_factory=list)
    candidate_entity_ids: list[str] = Field(default_factory=list)
    candidate_dimension_ids: list[str] = Field(default_factory=list)
    external_topics: list[str] = Field(default_factory=list)
    unresolved_terms: list[str] = Field(default_factory=list)
    authorization_status: AuthorizationStatus
    data_status: DataStatus
    reason_codes: list[str] = Field(default_factory=list)
    user_message: str
    next_action: str
    domain_pack_version: str
    interpreter_mode: InterpreterMode
    warnings: list[str] = Field(default_factory=list)


class QuestionDecisionEnvelope(BaseModel):
    session_id: UUID
    decision: QuestionDecision


class SessionMessage(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime


class SessionSnapshot(BaseModel):
    session_id: UUID
    tenant_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    messages: list[SessionMessage]
    decisions: list[QuestionDecision]


class ComponentHealth(BaseModel):
    status: str
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReadinessResponse(BaseModel):
    status: str
    components: dict[str, ComponentHealth]
