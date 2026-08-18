from __future__ import annotations

import asyncio
import hashlib
import json
import math
import sqlite3
from calendar import monthrange
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from talk2data.connectors.base import (
    ConnectorCapability,
    ConnectorDescriptor,
    SourceFreshness,
    StructuredQueryPlan,
)
from talk2data.domain.chat import QueryReceipt
from talk2data.domain.models import (
    AccessContext,
    ComparisonType,
    FilterOperator,
    MetricAggregation,
    SourceStatus,
    TimePreset,
    TimeWindow,
)
from talk2data.services.policy import READ_DATA_ACTION


class DemoConnectorError(RuntimeError):
    """Base error for the synthetic demonstration connector."""


class DemoConnectorValidationError(DemoConnectorError):
    """Raised when a governed query plan cannot be executed safely."""


class DemoSourceNotReadyError(DemoConnectorError):
    """Raised when the requested period extends beyond certified demo coverage."""


@dataclass(frozen=True)
class MetricSpec:
    aggregation: MetricAggregation
    allowed_dimensions: frozenset[str]


@dataclass(frozen=True)
class ResolvedRange:
    start: date
    end: date


DIMENSION_COLUMNS: dict[str, str] = {
    "PLAN": "plan_id",
    "MARKET": "market_id",
    "REGION": "region_id",
    "CHANNEL": "channel_id",
    "STORE": "store_id",
    "CELL_SITE": "cell_site_id",
    "HOUR": "hour_id",
    "TECHNOLOGY": "technology_id",
}

METRIC_SPECS: dict[str, MetricSpec] = {
    "POSTPAID_CHURN": MetricSpec(
        aggregation=MetricAggregation.RATIO,
        allowed_dimensions=frozenset({"PLAN", "MARKET", "REGION", "CHANNEL"}),
    ),
    "MOBILE_ACTIVATIONS": MetricSpec(
        aggregation=MetricAggregation.SUM,
        allowed_dimensions=frozenset({"STORE", "MARKET", "REGION", "CHANNEL", "PLAN"}),
    ),
    "NETWORK_CONGESTION": MetricSpec(
        aggregation=MetricAggregation.RATIO,
        allowed_dimensions=frozenset({"MARKET", "CELL_SITE", "HOUR", "TECHNOLOGY"}),
    ),
}

DEMO_COVERAGE_START = date(2025, 7, 1)
DEMO_COVERAGE_END = date(2026, 7, 31)
DEMO_SNAPSHOT = datetime(2026, 8, 1, 6, 0, tzinfo=UTC)
DEMO_SEED_VERSION = "2026.08.1"
KNOWN_REGIONS = frozenset({"NORTHEAST", "SOUTHEAST", "CENTRAL", "WEST"})


class DemoSQLiteConnector:
    """Read-only, parameterized SQLite connector over synthetic telecom facts."""

    def __init__(
        self,
        *,
        connector_id: str,
        database_path: Path,
        allowed_metric_ids: set[str],
    ) -> None:
        self.descriptor = ConnectorDescriptor(
            connector_id=connector_id,
            connector_type="SQLITE_DEMO",
            dialect="SQLite",
            capabilities={
                ConnectorCapability.CATALOG_DISCOVERY,
                ConnectorCapability.PARAMETERIZED_FILTERS,
                ConnectorCapability.AGGREGATION,
                ConnectorCapability.SECURITY_PUSHDOWN,
            },
            read_only=True,
            maximum_rows=100,
            query_timeout_seconds=10,
        )
        self._database_path = database_path
        self._allowed_metric_ids = frozenset(allowed_metric_ids)

    async def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._initialize_sync)

    async def test_connection(self) -> tuple[bool, str]:
        try:
            row = await asyncio.to_thread(self._select_one_sync)
        except (OSError, sqlite3.Error) as exc:
            return False, f"Demo connector is unavailable: {exc}"
        if row != 1:
            return False, "Demo connector health query returned an unexpected value."
        return True, f"Demo connector {self.descriptor.connector_id} is ready."

    async def discover_catalog(self, access: AccessContext) -> list[dict[str, Any]]:
        if READ_DATA_ACTION not in access.permitted_actions and "TALK2DATA_ADMIN" not in access.roles:
            return []
        return [
            {
                "connector_id": self.descriptor.connector_id,
                "metric_id": metric_id,
                "dimensions": sorted(METRIC_SPECS[metric_id].allowed_dimensions),
                "synthetic": True,
            }
            for metric_id in sorted(self._allowed_metric_ids)
        ]

    async def validate_plan(
        self,
        plan: StructuredQueryPlan,
        access: AccessContext,
    ) -> list[str]:
        errors: list[str] = []
        if plan.connector_id != self.descriptor.connector_id:
            errors.append("CONNECTOR_ID_MISMATCH")
        if plan.tenant_id != access.tenant_id:
            errors.append("TENANT_SCOPE_MISMATCH")
        if READ_DATA_ACTION not in access.permitted_actions and "TALK2DATA_ADMIN" not in access.roles:
            errors.append("DATA_ACTION_NOT_ALLOWED")
        if plan.metric_id not in self._allowed_metric_ids:
            errors.append("METRIC_NOT_AVAILABLE_ON_CONNECTOR")
            return errors

        spec = METRIC_SPECS[plan.metric_id]
        if plan.aggregation != spec.aggregation:
            errors.append("AGGREGATION_CONTRACT_MISMATCH")
        if set(plan.dimensions) - spec.allowed_dimensions:
            errors.append("DIMENSION_NOT_ALLOWED")
        if plan.row_limit > self.descriptor.maximum_rows:
            errors.append("ROW_LIMIT_EXCEEDED")

        scoped_regions = access.regions & KNOWN_REGIONS
        for query_filter in plan.filters:
            if query_filter.dimension_id not in spec.allowed_dimensions:
                errors.append("FILTER_DIMENSION_NOT_ALLOWED")
            if query_filter.operator not in {FilterOperator.IN, FilterOperator.EQUALS}:
                errors.append("FILTER_OPERATOR_NOT_SUPPORTED")
            if query_filter.dimension_id == "REGION" and scoped_regions:
                if set(query_filter.values) - scoped_regions:
                    errors.append("REGION_SCOPE_VIOLATION")
        try:
            requested = resolve_time_window(plan.time_window)
        except ValueError:
            errors.append("INVALID_TIME_WINDOW")
        else:
            if requested.start < DEMO_COVERAGE_START or requested.end > DEMO_COVERAGE_END:
                errors.append("SOURCE_COVERAGE_INCOMPLETE")
        return list(dict.fromkeys(errors))

    async def estimate_cost(self, plan: StructuredQueryPlan) -> dict[str, Any]:
        return {
            "connector_id": self.descriptor.connector_id,
            "estimated_rows": min(plan.row_limit, 100),
            "estimated_cost": 0,
            "unit": "synthetic-demo",
        }

    async def execute_read_only(
        self,
        plan: StructuredQueryPlan,
        access: AccessContext,
    ) -> QueryReceipt:
        errors = await self.validate_plan(plan, access)
        if "SOURCE_COVERAGE_INCOMPLETE" in errors:
            raise DemoSourceNotReadyError(
                f"Certified demonstration data is available only through {DEMO_COVERAGE_END.isoformat()}."
            )
        if errors:
            raise DemoConnectorValidationError(", ".join(errors))
        return await asyncio.to_thread(self._execute_sync, plan, access)

    async def get_freshness(self) -> SourceFreshness:
        return SourceFreshness(
            status=SourceStatus.AVAILABLE,
            last_refreshed_at=DEMO_SNAPSHOT,
            coverage_start=datetime.combine(DEMO_COVERAGE_START, datetime.min.time(), tzinfo=UTC),
            coverage_end=datetime.combine(DEMO_COVERAGE_END, datetime.max.time(), tzinfo=UTC),
            expected_refresh="Fixed synthetic demonstration snapshot",
        )

    async def cancel_query(self, execution_id: str) -> bool:
        del execution_id
        return False

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA query_only = OFF")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize_sync(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS demo_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metric_facts (
                    fact_date TEXT NOT NULL,
                    metric_id TEXT NOT NULL,
                    amount REAL,
                    numerator REAL,
                    denominator REAL,
                    plan_id TEXT,
                    market_id TEXT,
                    region_id TEXT,
                    channel_id TEXT,
                    store_id TEXT,
                    cell_site_id TEXT,
                    hour_id TEXT,
                    technology_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_demo_metric_date
                    ON metric_facts(metric_id, fact_date);
                """
            )
            current = connection.execute(
                "SELECT value FROM demo_metadata WHERE key = 'seed_version'"
            ).fetchone()
            if current is None or str(current[0]) != DEMO_SEED_VERSION:
                connection.execute("DELETE FROM metric_facts")
                connection.executemany(
                    """
                    INSERT INTO metric_facts(
                        fact_date, metric_id, amount, numerator, denominator,
                        plan_id, market_id, region_id, channel_id, store_id,
                        cell_site_id, hour_id, technology_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _seed_rows(),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO demo_metadata(key, value) VALUES ('seed_version', ?)",
                    (DEMO_SEED_VERSION,),
                )
            connection.commit()

    def _select_one_sync(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT 1").fetchone()
        return 0 if row is None else int(row[0])

    def _execute_sync(self, plan: StructuredQueryPlan, access: AccessContext) -> QueryReceipt:
        current_range = resolve_time_window(plan.time_window)
        comparison_range = resolve_comparison_range(current_range, plan.comparison.comparison_type)
        sql, parameters = self._build_sql(plan, access, current_range)
        current_rows = self._query(sql, parameters)

        comparison_rows: list[dict[str, Any]] = []
        comparison_sql: str | None = None
        if comparison_range is not None:
            comparison_sql, comparison_parameters = self._build_sql(plan, access, comparison_range)
            comparison_rows = self._query(comparison_sql, comparison_parameters)

        result_rows = merge_comparison_rows(
            current_rows=current_rows,
            comparison_rows=comparison_rows,
            dimensions=plan.dimensions,
        )
        canonical_results = json.dumps(
            result_rows,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        sql_payload = sql if comparison_sql is None else f"{sql}\n-- comparison\n{comparison_sql}"
        return QueryReceipt(
            query_id=plan.query_id,
            decision_id=plan.decision_id,
            plan_hash=plan.plan_hash,
            connector_id=plan.connector_id,
            source_snapshot=DEMO_SNAPSHOT,
            coverage_start=DEMO_COVERAGE_START,
            coverage_end=DEMO_COVERAGE_END,
            resolved_start=current_range.start,
            resolved_end=current_range.end,
            comparison_start=None if comparison_range is None else comparison_range.start,
            comparison_end=None if comparison_range is None else comparison_range.end,
            row_count=len(result_rows),
            result_rows=result_rows,
            result_hash=hashlib.sha256(canonical_results.encode("utf-8")).hexdigest(),
            sql_hash=hashlib.sha256(sql_payload.encode("utf-8")).hexdigest(),
            data_quality_status="EXECUTED",
            data_quality_checks=[
                "PARAMETERIZED_SQL",
                "READ_ONLY_SOURCE",
                "SOURCE_COVERAGE_CONFIRMED",
                "POLICY_SCOPE_APPLIED",
            ],
            policy_decision_id=str(plan.decision_id),
            warnings=["SYNTHETIC_DEMONSTRATION_DATA"],
        )

    def _query(self, sql: str, parameters: list[Any]) -> list[dict[str, Any]]:
        with self._connection() as connection:
            connection.execute("PRAGMA query_only = ON")
            rows = connection.execute(sql, parameters).fetchall()
        normalized: list[dict[str, Any]] = []
        for row in rows:
            item = {key: row[key] for key in row.keys()}
            value = item.get("value")
            if value is not None:
                item["value"] = float(value)
            normalized.append(item)
        return normalized

    def _build_sql(
        self,
        plan: StructuredQueryPlan,
        access: AccessContext,
        resolved_range: ResolvedRange,
    ) -> tuple[str, list[Any]]:
        spec = METRIC_SPECS[plan.metric_id]
        dimension_columns = [DIMENSION_COLUMNS[dimension] for dimension in plan.dimensions]
        select_dimensions = ", ".join(
            f"{column} AS {dimension}"
            for column, dimension in zip(dimension_columns, plan.dimensions, strict=True)
        )
        value_expression = (
            "CASE WHEN SUM(denominator) = 0 THEN NULL ELSE SUM(numerator) / SUM(denominator) END"
            if spec.aggregation == MetricAggregation.RATIO
            else "SUM(amount)"
        )
        select_clause = (
            f"{select_dimensions}, {value_expression} AS value"
            if select_dimensions
            else f"{value_expression} AS value"
        )
        where = ["metric_id = ?", "fact_date >= ?", "fact_date <= ?"]
        parameters: list[Any] = [
            plan.metric_id,
            resolved_range.start.isoformat(),
            resolved_range.end.isoformat(),
        ]

        for query_filter in plan.filters:
            column = DIMENSION_COLUMNS[query_filter.dimension_id]
            placeholders = ", ".join("?" for _ in query_filter.values)
            where.append(f"{column} IN ({placeholders})")
            parameters.extend(query_filter.values)

        scoped_regions = sorted(access.regions & KNOWN_REGIONS)
        if scoped_regions and "REGION" in spec.allowed_dimensions:
            placeholders = ", ".join("?" for _ in scoped_regions)
            where.append(f"region_id IN ({placeholders})")
            parameters.extend(scoped_regions)

        sql = f"SELECT {select_clause} FROM metric_facts WHERE " + " AND ".join(where)
        if dimension_columns:
            group_by = ", ".join(dimension_columns)
            sql += f" GROUP BY {group_by} ORDER BY {group_by}"
        sql += " LIMIT ?"
        parameters.append(plan.row_limit)
        return sql, parameters


def resolve_time_window(window: TimeWindow) -> ResolvedRange:
    anchor = window.anchor_date
    if window.preset == TimePreset.CUSTOM:
        if window.start_date is None or window.end_date is None:
            raise ValueError("custom window requires dates")
        return ResolvedRange(window.start_date, window.end_date)
    if window.preset == TimePreset.CURRENT_DAY:
        return ResolvedRange(anchor, anchor)
    if window.preset == TimePreset.PREVIOUS_COMPLETE_DAY:
        prior = anchor - timedelta(days=1)
        return ResolvedRange(prior, prior)
    if window.preset == TimePreset.CURRENT_WEEK:
        start = anchor - timedelta(days=anchor.weekday())
        return ResolvedRange(start, anchor)
    if window.preset == TimePreset.PREVIOUS_COMPLETE_WEEK:
        end = anchor - timedelta(days=anchor.weekday() + 1)
        return ResolvedRange(end - timedelta(days=6), end)
    if window.preset == TimePreset.CURRENT_MONTH:
        return ResolvedRange(anchor.replace(day=1), anchor)
    if window.preset == TimePreset.PREVIOUS_COMPLETE_MONTH:
        previous_end = anchor.replace(day=1) - timedelta(days=1)
        return ResolvedRange(previous_end.replace(day=1), previous_end)
    if window.preset == TimePreset.CURRENT_QUARTER:
        start_month = ((anchor.month - 1) // 3) * 3 + 1
        return ResolvedRange(date(anchor.year, start_month, 1), anchor)
    if window.preset == TimePreset.PREVIOUS_COMPLETE_QUARTER:
        current_start_month = ((anchor.month - 1) // 3) * 3 + 1
        current_start = date(anchor.year, current_start_month, 1)
        end = current_start - timedelta(days=1)
        start_month = ((end.month - 1) // 3) * 3 + 1
        return ResolvedRange(date(end.year, start_month, 1), end)
    if window.preset == TimePreset.CURRENT_YEAR:
        return ResolvedRange(date(anchor.year, 1, 1), anchor)
    if window.preset == TimePreset.PREVIOUS_COMPLETE_YEAR:
        return ResolvedRange(date(anchor.year - 1, 1, 1), date(anchor.year - 1, 12, 31))
    if window.preset == TimePreset.ROLLING_30_DAYS:
        return ResolvedRange(anchor - timedelta(days=29), anchor)
    if window.preset == TimePreset.ROLLING_12_MONTHS:
        start_month = anchor.month + 1
        start_year = anchor.year - 1
        if start_month == 13:
            start_month = 1
            start_year += 1
        return ResolvedRange(date(start_year, start_month, 1), anchor)
    raise ValueError(f"unsupported time preset: {window.preset}")


def resolve_comparison_range(
    current: ResolvedRange,
    comparison_type: ComparisonType,
) -> ResolvedRange | None:
    if comparison_type == ComparisonType.NONE:
        return None
    if comparison_type == ComparisonType.PRIOR_PERIOD:
        duration = current.end - current.start
        end = current.start - timedelta(days=1)
        return ResolvedRange(end - duration, end)
    if comparison_type == ComparisonType.YEAR_OVER_YEAR:
        return ResolvedRange(_shift_year(current.start, -1), _shift_year(current.end, -1))
    raise ValueError(f"unsupported comparison type: {comparison_type}")


def merge_comparison_rows(
    *,
    current_rows: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
    dimensions: list[str],
) -> list[dict[str, Any]]:
    comparison_by_key = {
        tuple(row.get(dimension) for dimension in dimensions): row for row in comparison_rows
    }
    merged: list[dict[str, Any]] = []
    for row in current_rows:
        value = row.get("value")
        if value is None or not math.isfinite(float(value)):
            continue
        item = dict(row)
        key = tuple(row.get(dimension) for dimension in dimensions)
        comparison = comparison_by_key.get(key)
        if comparison is not None and comparison.get("value") is not None:
            comparison_value = float(comparison["value"])
            current_value = float(value)
            absolute_change = current_value - comparison_value
            item["comparison_value"] = comparison_value
            item["absolute_change"] = absolute_change
            item["percent_change"] = (
                None if comparison_value == 0 else absolute_change / abs(comparison_value)
            )
        merged.append(item)
    return merged


def _shift_year(value: date, years: int) -> date:
    target_year = value.year + years
    day = min(value.day, monthrange(target_year, value.month)[1])
    return date(target_year, value.month, day)


def _month_starts(start: date, end: date) -> list[date]:
    months: list[date] = []
    current = start.replace(day=1)
    while current <= end:
        months.append(current)
        next_month = current.month + 1
        next_year = current.year
        if next_month == 13:
            next_month = 1
            next_year += 1
        current = date(next_year, next_month, 1)
    return months


def _seed_rows() -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    months = _month_starts(DEMO_COVERAGE_START, DEMO_COVERAGE_END)
    regions = ["NORTHEAST", "SOUTHEAST", "CENTRAL", "WEST"]
    channels = ["RETAIL", "DIGITAL", "CARE"]
    plans = ["STARTER", "UNLIMITED", "PREMIUM"]
    plan_rates = {"STARTER": 0.024, "UNLIMITED": 0.019, "PREMIUM": 0.014}
    region_rate_offsets = {
        "NORTHEAST": 0.0010,
        "SOUTHEAST": 0.0005,
        "CENTRAL": 0.0,
        "WEST": -0.0005,
    }
    channel_rate_offsets = {"RETAIL": 0.0, "DIGITAL": -0.0004, "CARE": 0.0007}

    for month_index, month in enumerate(months):
        for plan_index, plan in enumerate(plans):
            for region_index, region in enumerate(regions):
                for channel_index, channel in enumerate(channels):
                    denominator = 5_000 + plan_index * 900 + region_index * 350 + channel_index * 200
                    rate = max(
                        0.004,
                        plan_rates[plan]
                        - month_index * 0.00011
                        + region_rate_offsets[region]
                        + channel_rate_offsets[channel],
                    )
                    numerator = round(denominator * rate)
                    rows.append(
                        (
                            month.isoformat(),
                            "POSTPAID_CHURN",
                            None,
                            numerator,
                            denominator,
                            plan,
                            f"{region}_MARKET",
                            region,
                            channel,
                            None,
                            None,
                            None,
                            None,
                        )
                    )

        activation_baseline = {
            "NORTHEAST": 10_800,
            "SOUTHEAST": 9_700,
            "CENTRAL": 8_600,
            "WEST": 11_800,
        }
        channel_weights = {"RETAIL": 0.50, "DIGITAL": 0.35, "CARE": 0.15}
        for region in regions:
            monthly_total = round(activation_baseline[region] * (1 + month_index * 0.012))
            allocated = 0
            for channel_index, channel in enumerate(channels):
                amount = (
                    monthly_total - allocated
                    if channel_index == len(channels) - 1
                    else round(monthly_total * channel_weights[channel])
                )
                allocated += amount
                rows.append(
                    (
                        month.isoformat(),
                        "MOBILE_ACTIVATIONS",
                        amount,
                        None,
                        None,
                        None,
                        f"{region}_MARKET",
                        region,
                        channel,
                        f"{region}_STORE_{channel_index + 1}",
                        None,
                        None,
                        None,
                    )
                )

        markets = [
            ("NY_METRO", "NORTHEAST"),
            ("ATLANTA", "SOUTHEAST"),
            ("CHICAGO", "CENTRAL"),
            ("LOS_ANGELES", "WEST"),
        ]
        technology_hour_rates = {
            ("LTE", "MORNING"): 0.035,
            ("LTE", "EVENING"): 0.080,
            ("FIVE_G", "MORNING"): 0.045,
            ("FIVE_G", "EVENING"): 0.110,
        }
        for market_index, (market, region) in enumerate(markets):
            for technology, hour in technology_hour_rates:
                denominator = 2_000
                rate = technology_hour_rates[(technology, hour)] + market_index * 0.004 - month_index * 0.0005
                numerator = round(denominator * max(rate, 0.005))
                rows.append(
                    (
                        month.isoformat(),
                        "NETWORK_CONGESTION",
                        None,
                        numerator,
                        denominator,
                        None,
                        market,
                        region,
                        None,
                        None,
                        f"{market}_SITE_1",
                        hour,
                        technology,
                    )
                )
    return rows
