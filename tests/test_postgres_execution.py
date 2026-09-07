"""Exercise the adapter's real SQL builder and transaction lifecycle without credentials.

The separate live PostgreSQL CI job verifies these contracts against the actual driver/server.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest

from talk2data.connectors.demo_sqlite import resolve_time_window
from talk2data.connectors.postgres import (
    PostgreSQLConnector,
    PostgreSQLConnectorUnavailableError,
    PostgreSQLConnectorValidationError,
    PostgreSQLSourceNotReadyError,
)
from talk2data.domain.models import ComparisonSpec, ComparisonType, QueryFilter
from tests.test_postgres_connector import build_access, build_connector, build_plan


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Connection:
    connection = None  # psycopg's offline identifier escaping, with no server encoding.

    def __init__(self, connector):
        self.columns = connector._required_columns
        self.health = [{"value": 1}]
        self.source = [
            {
                "source_snapshot": datetime(2026, 8, 17, tzinfo=UTC),
                "coverage_start": date(2025, 1, 1),
                "coverage_end": date(2026, 7, 31),
            }
        ]
        self.results = [[{"PLAN": "PREMIUM", "value": Decimal("0.02")}]]
        self.calls = []
        self.rolled_back = False
        self.closed = False
        self.cancelled = False
        self.failure = None

    def execute(self, query, parameters=None):
        statement = query if isinstance(query, str) else query.as_string()
        self.calls.append((statement, parameters))
        if self.failure:
            raise self.failure
        if "information_schema" in statement:
            return Cursor([{"column_name": name} for name in self.columns])
        if "SELECT 1 AS value" in statement:
            return Cursor(self.health)
        if "CURRENT_TIMESTAMP" in statement:
            return Cursor(self.source)
        if statement.startswith("SELECT ") and " FROM " in statement:
            return Cursor(self.results.pop(0))
        return Cursor([])

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True

    def cancel(self):
        if self.failure:
            raise self.failure
        self.cancelled = True


@pytest.fixture
def database(monkeypatch):
    connector = build_connector()
    connection = Connection(connector)
    calls = []

    def connect(dsn, **kwargs):
        calls.append((dsn, kwargs))
        return connection

    monkeypatch.setattr(psycopg, "connect", connect)
    return connector, connection, calls


@pytest.mark.asyncio
async def test_parameterized_execution_pins_receipt_and_closes_read_only_transaction(database):
    connector, connection, calls = database
    await connector.initialize()
    assert (await connector.test_connection())[0]
    assert (await connector.get_freshness()).status == "AVAILABLE"
    catalog = await connector.discover_catalog(build_access())
    assert all(item["synthetic"] is False for item in catalog)
    assert (
        await connector.discover_catalog(build_access().model_copy(update={"permitted_actions": set()})) == []
    )
    plan = build_plan().model_copy(
        update={"filters": [QueryFilter(dimension_id="PLAN", values=["PREMIUM' OR 1=1 --"])]}
    )
    receipt = await connector.execute_read_only(plan, build_access())
    assert receipt.source_kind == "postgresql"
    assert receipt.result_rows == [{"PLAN": "PREMIUM", "value": 0.02}]
    assert receipt.policy_decision_id == str(plan.decision_id)
    assert receipt.physical_mapping_hash == connector.descriptor.mapping_hash
    statement, parameters = next(call for call in connection.calls if "GROUP BY" in call[0])
    assert "PREMIUM'" not in statement
    assert ["PREMIUM' OR 1=1 --"] in parameters
    assert ["NORTHEAST"] in parameters
    assert parameters[-1] == plan.row_limit + 1
    assert "REPEATABLE READ READ ONLY" in connection.calls[0][0]
    assert calls[0][1]["autocommit"] is False
    assert connection.closed and connection.rolled_back
    assert connector._active_connections == {}
    assert (await connector.estimate_cost(plan))["estimated_rows"] == 100


@pytest.mark.asyncio
async def test_comparison_calculation_and_sum_query(database):
    connector, connection, _ = database
    plan = build_plan().model_copy(
        update={
            "metric_id": "MOBILE_ACTIVATIONS",
            "aggregation": "SUM",
            "dimensions": [],
            "comparison": ComparisonSpec(comparison_type=ComparisonType.PRIOR_PERIOD),
        }
    )
    connection.results = [[{"value": 120}], [{"value": 100}]]
    receipt = await connector.execute_read_only(plan, build_access())
    assert receipt.result_rows == [
        {"value": 120.0, "comparison_value": 100.0, "absolute_change": 20.0, "percent_change": 0.2}
    ]
    assert receipt.comparison_end == date(2026, 6, 30)
    assert all("GROUP BY" not in query for query, _ in connection.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        "no_rows",
        "null_dates",
        "outside",
        "comparison_outside",
        "truncated",
        "comparison_truncated",
        "nan",
        "driver_error",
    ],
)
async def test_source_failures_never_issue_a_receipt_and_always_close(database, scenario):
    connector, connection, _ = database
    plan = build_plan()
    expected = PostgreSQLSourceNotReadyError
    if scenario == "no_rows":
        connection.source = []
    elif scenario == "null_dates":
        connection.source[0]["coverage_start"] = None
    elif scenario == "outside":
        connection.source[0]["coverage_end"] = date(2026, 6, 30)
    elif scenario == "comparison_outside":
        connection.source[0]["coverage_start"] = date(2026, 7, 1)
        plan = plan.model_copy(update={"comparison": ComparisonSpec(comparison_type="PRIOR_PERIOD")})
    elif scenario in {"truncated", "comparison_truncated"}:
        expected = PostgreSQLConnectorValidationError
        plan = plan.model_copy(update={"row_limit": 1})
        rows = [{"PLAN": "A", "value": 0.1}, {"PLAN": "B", "value": 0.2}]
        connection.results = [rows]
        if scenario == "comparison_truncated":
            plan = plan.model_copy(update={"comparison": ComparisonSpec(comparison_type="PRIOR_PERIOD")})
            connection.results.insert(0, [{"PLAN": "A", "value": 0.1}])
    elif scenario == "nan":
        connection.results = [[{"value": float("nan")}]]
        expected = PostgreSQLConnectorValidationError
    else:
        connection.failure = psycopg.OperationalError("private database unavailable")
        expected = PostgreSQLConnectorUnavailableError
    with pytest.raises(expected) as error:
        await connector.execute_read_only(plan, build_access())
    assert "private database" not in str(error.value)
    assert connection.closed and connection.rolled_back
    assert connector._active_connections == {}


@pytest.mark.asyncio
async def test_freshness_health_initialization_and_cancellation_edges(database):
    connector, connection, _ = database
    connection.health = []
    assert (await connector.test_connection())[0] is False
    connection.source[0]["source_snapshot"] = datetime(2026, 8, 1)
    assert (await connector.get_freshness()).last_refreshed_at.tzinfo == UTC
    connection.source = []
    assert (await connector.get_freshness()).status == "NOT_READY"
    connection.columns = set()
    with pytest.raises(PostgreSQLConnectorUnavailableError):
        await connector.initialize()
    assert await connector.cancel_query("missing") is False
    connector._active_connections["active"] = connection
    assert await connector.cancel_query("active") is True
    assert connection.cancelled
    connection.failure = psycopg.OperationalError("cancel failed")
    assert await connector.cancel_query("active") is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("updates", "access_updates", "code"),
    [
        ({"connector_id": "wrong"}, {}, "CONNECTOR_ID_MISMATCH"),
        ({"tenant_id": "other"}, {}, "TENANT_SCOPE_MISMATCH"),
        ({}, {"permitted_actions": set()}, "DATA_ACTION_NOT_ALLOWED"),
        ({}, {"regions": set()}, "REGION_SCOPE_REQUIRED"),
        ({"aggregation": "SUM"}, {}, "AGGREGATION_CONTRACT_MISMATCH"),
        ({"dimensions": ["HOUR"]}, {}, "DIMENSION_NOT_ALLOWED"),
        ({"row_limit": 10_001}, {}, "ROW_LIMIT_EXCEEDED"),
        ({"filters": [QueryFilter(dimension_id="HOUR", values=["12"])]}, {}, "FILTER_DIMENSION_NOT_ALLOWED"),
        (
            {
                "filters": [
                    QueryFilter(dimension_id="PLAN", values=["X"]).model_copy(update={"operator": "NOT_IN"})
                ]
            },
            {},
            "FILTER_OPERATOR_NOT_SUPPORTED",
        ),
        (
            {"time_window": build_plan().time_window.model_copy(update={"preset": "invalid"})},
            {},
            "INVALID_TIME_WINDOW",
        ),
    ],
)
async def test_invalid_plans_are_rejected_before_opening_a_connection(
    database, updates, access_updates, code
):
    connector, _, calls = database
    plan = build_plan().model_copy(update=updates)
    access = build_access().model_copy(update=access_updates)
    assert code in await connector.validate_plan(plan, access)
    with pytest.raises(PostgreSQLConnectorValidationError, match=code):
        await connector.execute_read_only(plan, access)
    assert calls == []


@pytest.mark.parametrize("updates", [{"dsn": " "}, {"mapping_version": " "}, {"mapping_hash": "short"}])
def test_invalid_adapter_configuration_fails_at_construction(updates):
    template = build_connector()
    config = dict(
        mapping=template._mapping,
        mapping_version="1",
        mapping_hash="a" * 64,
        dsn="postgresql://example.invalid",
    )
    with pytest.raises(ValueError):
        PostgreSQLConnector(**(config | updates))


def test_sql_builder_rejects_incomplete_or_unmapped_contracts():
    connector = build_connector()
    plan = build_plan()
    mapping = connector._metric_mappings[plan.metric_id]
    for broken in [
        mapping.model_copy(update={"denominator_column": None}),
        mapping.model_copy(update={"aggregation": "SUM", "amount_column": None}),
    ]:
        with pytest.raises(PostgreSQLConnectorValidationError, match="incomplete"):
            connector._build_query(plan, build_access(), resolve_time_window(plan.time_window), broken)
    with pytest.raises(PostgreSQLConnectorValidationError, match="REGION_SCOPE_UNMAPPED"):
        connector._build_query(
            plan, build_access(regions={"EUROPE"}), resolve_time_window(plan.time_window), mapping
        )


def test_null_aggregate_is_preserved_for_rejection_by_result_validator(database):
    connector, connection, _ = database
    connection.results = [[{"value": None}]]
    assert connector._query(connection, "SELECT value FROM facts", ()) == [{"value": None}]
