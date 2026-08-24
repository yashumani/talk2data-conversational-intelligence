from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from talk2data.domain.chat import QueryReceipt
from talk2data.domain.models import (
    AccessContext,
    ComparisonSpec,
    MetricAggregation,
    MetricValueType,
    QueryFilter,
    SourceStatus,
    TimeWindow,
)


class ConnectorCapability(StrEnum):
    CATALOG_DISCOVERY = "CATALOG_DISCOVERY"
    SCHEMA_INTROSPECTION = "SCHEMA_INTROSPECTION"
    PARAMETERIZED_FILTERS = "PARAMETERIZED_FILTERS"
    AGGREGATION = "AGGREGATION"
    WINDOW_FUNCTIONS = "WINDOW_FUNCTIONS"
    QUERY_CANCELLATION = "QUERY_CANCELLATION"
    SECURITY_PUSHDOWN = "SECURITY_PUSHDOWN"


class ConnectorDescriptor(BaseModel):
    connector_id: str
    connector_type: str
    dialect: str | None = None
    capabilities: set[ConnectorCapability] = Field(default_factory=set)
    read_only: bool = True
    maximum_rows: int = Field(default=10_000, ge=1)
    query_timeout_seconds: int = Field(default=60, ge=1)
    mapping_version: str | None = None
    mapping_hash: str | None = None


class SourceFreshness(BaseModel):
    status: SourceStatus
    last_refreshed_at: datetime | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    expected_refresh: str | None = None
    known_delay: str | None = None


class StructuredQueryPlan(BaseModel):
    plan_id: UUID = Field(default_factory=uuid4)
    query_id: UUID
    decision_id: UUID
    plan_hash: str
    tenant_id: str
    connector_id: str
    metric_id: str
    semantic_version: str
    value_type: MetricValueType
    aggregation: MetricAggregation
    unit: str
    currency: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    filters: list[QueryFilter] = Field(default_factory=list)
    time_window: TimeWindow
    comparison: ComparisonSpec
    row_limit: int = Field(default=100, ge=1, le=10_000)


class DataConnector(Protocol):
    descriptor: ConnectorDescriptor

    async def initialize(self) -> None: ...

    async def test_connection(self) -> tuple[bool, str]: ...

    async def discover_catalog(self, access: AccessContext) -> list[dict[str, Any]]: ...

    async def validate_plan(
        self,
        plan: StructuredQueryPlan,
        access: AccessContext,
    ) -> list[str]: ...

    async def estimate_cost(self, plan: StructuredQueryPlan) -> dict[str, Any]: ...

    async def execute_read_only(
        self,
        plan: StructuredQueryPlan,
        access: AccessContext,
    ) -> QueryReceipt: ...

    async def get_freshness(self) -> SourceFreshness: ...

    async def cancel_query(self, execution_id: str) -> bool: ...
