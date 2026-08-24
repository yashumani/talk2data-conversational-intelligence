from __future__ import annotations

from datetime import date
from uuid import uuid4

import psycopg
import pytest

from talk2data.connectors.base import StructuredQueryPlan
from talk2data.connectors.postgres import PostgreSQLConnector
from talk2data.domain.models import (
    AccessContext,
    ClassificationLevel,
    ComparisonSpec,
    MetricAggregation,
    MetricValueType,
    QueryFilter,
    SourceStatus,
    TimeGrain,
    TimePreset,
    TimeWindow,
)


def build_connector() -> PostgreSQLConnector:
    return PostgreSQLConnector(
        connector_id="telecom_semantic_warehouse",
        dsn="postgresql://example.invalid/talk2data",
        schema_name="talk2data",
        table_name="metric_facts",
        allowed_metric_ids={"POSTPAID_CHURN", "MOBILE_ACTIVATIONS"},
    )


def build_access() -> AccessContext:
    return AccessContext(
        tenant_id="demo-telecom",
        user_id="postgres-test",
        roles={"BI_MANAGER"},
        regions={"NORTHEAST"},
        classification_clearance=ClassificationLevel.CONFIDENTIAL,
        permitted_actions={"READ_AGGREGATED_DATA"},
    )


def build_plan() -> StructuredQueryPlan:
    return StructuredQueryPlan(
        query_id=uuid4(),
        decision_id=uuid4(),
        plan_hash="a" * 64,
        tenant_id="demo-telecom",
        connector_id="telecom_semantic_warehouse",
        metric_id="POSTPAID_CHURN",
        semantic_version="2.0",
        value_type=MetricValueType.PERCENTAGE,
        aggregation=MetricAggregation.RATIO,
        unit="PERCENT",
        dimensions=["PLAN"],
        filters=[],
        time_window=TimeWindow(
            preset=TimePreset.PREVIOUS_COMPLETE_MONTH,
            grain=TimeGrain.MONTH,
            calendar="CORPORATE_FISCAL",
            timezone="America/New_York",
            anchor_date=date(2026, 8, 17),
        ),
        comparison=ComparisonSpec(),
        row_limit=100,
    )


def test_rejects_untrusted_postgres_identifiers() -> None:
    with pytest.raises(ValueError, match="simple PostgreSQL identifier"):
        PostgreSQLConnector(
            connector_id="telecom_semantic_warehouse",
            dsn="postgresql://example.invalid/talk2data",
            schema_name="talk2data; DROP SCHEMA public",
            table_name="metric_facts",
            allowed_metric_ids={"POSTPAID_CHURN"},
        )


@pytest.mark.asyncio
async def test_validates_plan_without_connecting_to_source() -> None:
    connector = build_connector()

    assert await connector.validate_plan(build_plan(), build_access()) == []


@pytest.mark.asyncio
async def test_rejects_region_scope_violation_before_execution() -> None:
    connector = build_connector()
    plan = build_plan().model_copy(
        update={
            "filters": [
                QueryFilter(
                    dimension_id="REGION",
                    values=["WEST"],
                )
            ]
        }
    )

    errors = await connector.validate_plan(plan, build_access())

    assert "REGION_SCOPE_VIOLATION" in errors


@pytest.mark.asyncio
async def test_rejects_metric_not_bound_to_connector() -> None:
    connector = build_connector()
    plan = build_plan().model_copy(update={"metric_id": "NETWORK_CONGESTION"})

    errors = await connector.validate_plan(plan, build_access())

    assert errors == ["METRIC_NOT_AVAILABLE_ON_CONNECTOR"]


@pytest.mark.asyncio
async def test_connection_health_does_not_expose_source_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = build_connector()

    def fail_health_query() -> int:
        raise psycopg.OperationalError("connection to secret-db.internal failed")

    monkeypatch.setattr(connector, "_select_one_sync", fail_health_query)

    ready, detail = await connector.test_connection()

    assert ready is False
    assert detail == "PostgreSQL connector is unavailable."
    assert "secret-db.internal" not in detail


@pytest.mark.asyncio
async def test_freshness_failure_does_not_expose_source_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = build_connector()

    def fail_freshness_query(_: frozenset[str]) -> None:
        raise psycopg.OperationalError("connection to secret-db.internal failed")

    monkeypatch.setattr(connector, "_source_state_sync", fail_freshness_query)

    freshness = await connector.get_freshness()

    assert freshness.status == SourceStatus.UNAVAILABLE
    assert freshness.known_delay == "Source freshness check failed."
    assert "secret-db.internal" not in freshness.known_delay
