from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from pydantic import ValidationError

from talk2data.connectors.demo_sqlite import (
    DemoConnectorValidationError,
    DemoSQLiteConnector,
    ResolvedRange,
    merge_comparison_rows,
    resolve_comparison_range,
    resolve_time_window,
)
from talk2data.domain.models import QueryFilter, TimeWindow
from tests.test_postgres_connector import build_access, build_plan


@pytest.mark.parametrize(
    ("preset", "start", "end"),
    [
        ("CURRENT_DAY", "2026-08-17", "2026-08-17"),
        ("PREVIOUS_COMPLETE_DAY", "2026-08-16", "2026-08-16"),
        ("CURRENT_WEEK", "2026-08-17", "2026-08-17"),
        ("PREVIOUS_COMPLETE_WEEK", "2026-08-10", "2026-08-16"),
        ("CURRENT_MONTH", "2026-08-01", "2026-08-17"),
        ("PREVIOUS_COMPLETE_MONTH", "2026-07-01", "2026-07-31"),
        ("CURRENT_QUARTER", "2026-07-01", "2026-08-17"),
        ("PREVIOUS_COMPLETE_QUARTER", "2026-04-01", "2026-06-30"),
        ("CURRENT_YEAR", "2026-01-01", "2026-08-17"),
        ("PREVIOUS_COMPLETE_YEAR", "2025-01-01", "2025-12-31"),
        ("ROLLING_30_DAYS", "2026-07-19", "2026-08-17"),
        ("ROLLING_12_MONTHS", "2025-09-01", "2026-08-17"),
    ],
)
def test_period_boundaries_have_exact_expected_dates(preset, start, end):
    window = build_plan().time_window.model_copy(update={"preset": preset})
    assert resolve_time_window(window) == ResolvedRange(date.fromisoformat(start), date.fromisoformat(end))


def test_year_rollover_leap_day_and_invalid_windows():
    template = build_plan().time_window
    rolling = template.model_copy(update={"preset": "ROLLING_12_MONTHS", "anchor_date": date(2026, 12, 31)})
    assert resolve_time_window(rolling).start == date(2026, 1, 1)
    leap = ResolvedRange(date(2024, 2, 29), date(2024, 2, 29))
    assert resolve_comparison_range(leap, "YEAR_OVER_YEAR") == ResolvedRange(
        date(2023, 2, 28), date(2023, 2, 28)
    )
    for update in [{"preset": "CUSTOM"}, {"start_date": date(2026, 8, 2), "end_date": date(2026, 8, 1)}]:
        with pytest.raises(ValidationError):
            TimeWindow.model_validate(template.model_dump() | update)
    for preset in ["CUSTOM", "unsupported"]:
        with pytest.raises(ValueError):
            resolve_time_window(template.model_copy(update={"preset": preset}))
    with pytest.raises(ValueError):
        resolve_comparison_range(leap, "unsupported")


def test_zero_comparison_is_undefined_percentage_not_infinity():
    rows = merge_comparison_rows(
        current_rows=[{"REGION": "WEST", "value": 5}],
        comparison_rows=[{"REGION": "WEST", "value": 0}],
        dimensions=["REGION"],
    )
    assert rows == [
        {
            "REGION": "WEST",
            "value": 5,
            "comparison_value": 0.0,
            "absolute_change": 5.0,
            "percent_change": None,
        }
    ]


@pytest.fixture
async def connector(tmp_path):
    connector = DemoSQLiteConnector(
        connector_id="telecom_semantic_warehouse",
        database_path=tmp_path / "facts.db",
        allowed_metric_ids={"POSTPAID_CHURN", "MOBILE_ACTIVATIONS"},
    )
    await connector.initialize()
    return connector


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("updates", "access_updates", "code"),
    [
        ({"connector_id": "wrong"}, {}, "CONNECTOR_ID_MISMATCH"),
        ({"tenant_id": "wrong"}, {}, "TENANT_SCOPE_MISMATCH"),
        ({}, {"permitted_actions": set()}, "DATA_ACTION_NOT_ALLOWED"),
        ({"metric_id": "UNKNOWN"}, {}, "METRIC_NOT_AVAILABLE_ON_CONNECTOR"),
        ({"aggregation": "SUM"}, {}, "AGGREGATION_CONTRACT_MISMATCH"),
        ({"dimensions": ["HOUR"]}, {}, "DIMENSION_NOT_ALLOWED"),
        ({"row_limit": 100_000}, {}, "ROW_LIMIT_EXCEEDED"),
        ({"filters": [QueryFilter(dimension_id="HOUR", values=["1"])]}, {}, "FILTER_DIMENSION_NOT_ALLOWED"),
        (
            {
                "filters": [
                    QueryFilter(dimension_id="PLAN", values=["A"]).model_copy(update={"operator": "NOT_IN"})
                ]
            },
            {},
            "FILTER_OPERATOR_NOT_SUPPORTED",
        ),
        ({"filters": [QueryFilter(dimension_id="REGION", values=["WEST"])]}, {}, "REGION_SCOPE_VIOLATION"),
        (
            {"time_window": build_plan().time_window.model_copy(update={"preset": "invalid"})},
            {},
            "INVALID_TIME_WINDOW",
        ),
    ],
)
async def test_sqlite_rejects_invalid_plans_before_query(connector, updates, access_updates, code):
    plan = build_plan().model_copy(update=updates)
    access = build_access().model_copy(update=access_updates)
    assert code in await connector.validate_plan(plan, access)
    with pytest.raises(DemoConnectorValidationError, match=code):
        await connector.execute_read_only(plan, access)


@pytest.mark.asyncio
async def test_sqlite_health_discovery_estimation_scope_and_cancel(connector, monkeypatch):
    assert (
        await connector.discover_catalog(build_access().model_copy(update={"permitted_actions": set()})) == []
    )
    assert (await connector.estimate_cost(build_plan()))["estimated_rows"] > 0
    assert await connector.cancel_query("not-active") is False
    receipt = await connector.execute_read_only(build_plan(), build_access())
    assert len(receipt.result_rows) == 3
    assert receipt.source_kind == "synthetic_demo"
    monkeypatch.setattr(connector, "_select_one_sync", lambda: 0)
    assert not (await connector.test_connection())[0]

    def fail():
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(connector, "_select_one_sync", fail)
    assert not (await connector.test_connection())[0]
