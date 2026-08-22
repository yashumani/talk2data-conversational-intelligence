from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class MetricValueType(StrEnum):
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    PERCENTAGE = "PERCENTAGE"
    CURRENCY = "CURRENCY"


class MetricAggregation(StrEnum):
    SUM = "SUM"
    COUNT = "COUNT"
    DISTINCT_COUNT = "DISTINCT_COUNT"
    AVERAGE = "AVERAGE"
    RATIO = "RATIO"
    LAST_VALUE = "LAST_VALUE"


class MetricAdditivity(StrEnum):
    ADDITIVE = "ADDITIVE"
    SEMI_ADDITIVE = "SEMI_ADDITIVE"
    NON_ADDITIVE = "NON_ADDITIVE"


class TimeGrain(StrEnum):
    HOUR = "HOUR"
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    QUARTER = "QUARTER"
    YEAR = "YEAR"


class TimePreset(StrEnum):
    CURRENT_DAY = "CURRENT_DAY"
    PREVIOUS_COMPLETE_DAY = "PREVIOUS_COMPLETE_DAY"
    CURRENT_WEEK = "CURRENT_WEEK"
    PREVIOUS_COMPLETE_WEEK = "PREVIOUS_COMPLETE_WEEK"
    CURRENT_MONTH = "CURRENT_MONTH"
    PREVIOUS_COMPLETE_MONTH = "PREVIOUS_COMPLETE_MONTH"
    CURRENT_QUARTER = "CURRENT_QUARTER"
    PREVIOUS_COMPLETE_QUARTER = "PREVIOUS_COMPLETE_QUARTER"
    CURRENT_YEAR = "CURRENT_YEAR"
    PREVIOUS_COMPLETE_YEAR = "PREVIOUS_COMPLETE_YEAR"
    ROLLING_30_DAYS = "ROLLING_30_DAYS"
    ROLLING_12_MONTHS = "ROLLING_12_MONTHS"
    CUSTOM = "CUSTOM"


class ComparisonType(StrEnum):
    NONE = "NONE"
    PRIOR_PERIOD = "PRIOR_PERIOD"
    YEAR_OVER_YEAR = "YEAR_OVER_YEAR"


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


class QueryCompilationStatus(StrEnum):
    COMPILED = "COMPILED"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    INVALID = "INVALID"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"


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

    @field_validator("roles", "departments", "regions", "business_units", "permitted_actions", mode="after")
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
    semantic_version: str = "1"
    value_type: MetricValueType = MetricValueType.DECIMAL
    aggregation: MetricAggregation = MetricAggregation.SUM
    additivity: MetricAdditivity = MetricAdditivity.ADDITIVE
    unit: str = "COUNT"
    allowed_dimensions: list[str] = Field(default_factory=list)
    supported_time_grains: list[TimeGrain] = Field(default_factory=lambda: [TimeGrain.MONTH])
    default_time_grain: TimeGrain = TimeGrain.MONTH
    default_time_window: TimePreset = TimePreset.PREVIOUS_COMPLETE_MONTH
    default_comparison: ComparisonType = ComparisonType.NONE
    valid_min: float | None = None
    valid_max: float | None = None
    classification: ClassificationLevel = ClassificationLevel.INTERNAL
    source: DataSourceReference

    @model_validator(mode="after")
    def validate_semantics(self) -> MetricDefinition:
        if self.default_time_grain not in self.supported_time_grains:
            raise ValueError("default_time_grain must be included in supported_time_grains")
        if self.valid_min is not None and self.valid_max is not None and self.valid_min > self.valid_max:
            raise ValueError("valid_min cannot exceed valid_max")
        if self.aggregation == MetricAggregation.RATIO and self.additivity != MetricAdditivity.NON_ADDITIVE:
            raise ValueError("ratio metrics must be NON_ADDITIVE")
        return self


class DimensionValue(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)


class BusinessEntity(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    domain_id: str
    values: list[DimensionValue] = Field(default_factory=list)
    classification: ClassificationLevel = ClassificationLevel.INTERNAL

    @model_validator(mode="after")
    def validate_values(self) -> BusinessEntity:
        value_ids = [value.id for value in self.values]
        if len(value_ids) != len(set(value_ids)):
            raise ValueError(f"duplicate values are not allowed for entity {self.id!r}")
        return self


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
    default_timezone: str = "UTC"
    domains: list[BusinessDomain]
    metrics: list[MetricDefinition]
    entities: list[BusinessEntity]
    external_adjacencies: list[ExternalAdjacency] = Field(default_factory=list)
    excluded_domains: list[ExcludedDomainRule] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_references(self) -> TenantDomainPack:
        domain_ids = [domain.id for domain in self.domains]
        metric_ids = [metric.id for metric in self.metrics]
        entity_ids = [entity.id for entity in self.entities]
        for label, values in (
            ("domain", domain_ids),
            ("metric", metric_ids),
            ("entity", entity_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label} IDs are not allowed")

        known_domains = set(domain_ids)
        known_metrics = set(metric_ids)
        known_entities = set(entity_ids)
        for metric in self.metrics:
            if metric.domain_id not in known_domains:
                raise ValueError(f"metric {metric.id!r} references unknown domain {metric.domain_id!r}")
            unknown_dimensions = set(metric.allowed_dimensions) - known_entities
            if unknown_dimensions:
                raise ValueError(
                    f"metric {metric.id!r} references unknown dimensions: "
                    + ", ".join(sorted(unknown_dimensions))
                )
        for entity in self.entities:
            if entity.domain_id not in known_domains:
                raise ValueError(f"entity {entity.id!r} references unknown domain {entity.domain_id!r}")
        for adjacency in self.external_adjacencies:
            unknown_metrics = set(adjacency.anchor_metric_ids) - known_metrics
            unknown_entities = set(adjacency.anchor_entity_ids) - known_entities
            if unknown_metrics or unknown_entities:
                raise ValueError(f"external adjacency {adjacency.id!r} contains unknown anchors")
        return self


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


class QueryCompilationRequest(QuestionRequest):
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TimeWindow(BaseModel):
    preset: TimePreset
    grain: TimeGrain
    calendar: str
    timezone: str
    anchor_date: date
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> TimeWindow:
        if self.preset == TimePreset.CUSTOM and (self.start_date is None or self.end_date is None):
            raise ValueError("custom time windows require start_date and end_date")
        if self.start_date is not None and self.end_date is not None and self.start_date > self.end_date:
            raise ValueError("start_date cannot be after end_date")
        return self


class ComparisonSpec(BaseModel):
    comparison_type: ComparisonType = ComparisonType.NONE


class FilterOperator(StrEnum):
    EQUALS = "EQUALS"
    IN = "IN"


class QueryFilter(BaseModel):
    dimension_id: str
    operator: FilterOperator = FilterOperator.IN
    values: list[str] = Field(min_length=1)


class AccessScope(BaseModel):
    roles: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    business_units: list[str] = Field(default_factory=list)
    permitted_actions: list[str] = Field(default_factory=list)
    classification_clearance: ClassificationLevel
    enforcement: str = "CONNECTOR_POLICY_PUSHDOWN_REQUIRED"


class BusinessQueryIR(BaseModel):
    query_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    decision_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tenant_id: str
    user_id: str
    question: str
    recognized_intent: QuestionIntent
    metric_id: str
    metric_name: str
    semantic_version: str
    value_type: MetricValueType
    aggregation: MetricAggregation
    additivity: MetricAdditivity
    unit: str
    currency: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    filters: list[QueryFilter] = Field(default_factory=list)
    time_window: TimeWindow
    comparison: ComparisonSpec
    access_scope: AccessScope
    source_connector_id: str
    domain_pack_version: str
    semantic_snapshot_hash: str
    plan_hash: str
    requires_external_context: bool = False
    warnings: list[str] = Field(default_factory=list)


class CompilationIssue(BaseModel):
    code: str
    message: str
    field: str | None = None


class QueryCompilationResult(BaseModel):
    session_id: UUID
    decision: QuestionDecision
    status: QueryCompilationStatus
    query_ir: BusinessQueryIR | None = None
    issues: list[CompilationIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MetricResolutionRequest(BaseModel):
    metric_id: str
    access_context: AccessContext

    @field_validator("metric_id")
    @classmethod
    def normalize_metric_id(cls, value: str) -> str:
        return value.strip().upper()


class MetricResolutionResponse(BaseModel):
    domain_pack_version: str
    semantic_snapshot_hash: str
    metric: MetricDefinition


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
    query_plans: list[BusinessQueryIR] = Field(default_factory=list)


class ComponentHealth(BaseModel):
    status: str
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReadinessResponse(BaseModel):
    status: str
    components: dict[str, ComponentHealth]
