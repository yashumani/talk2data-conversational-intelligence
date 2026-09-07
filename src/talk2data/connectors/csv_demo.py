"""An isolated, ephemeral demo connector; it never touches another connector."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

from talk2data.connectors.base import (
    ConnectorCapability,
    ConnectorDescriptor,
    SourceFreshness,
    StructuredQueryPlan,
)
from talk2data.connectors.demo_sqlite import (
    ResolvedRange,
    merge_comparison_rows,
    resolve_comparison_range,
    resolve_time_window,
)
from talk2data.connectors.errors import ConnectorValidationError, SourceNotReadyError
from talk2data.domain.chat import QueryReceipt
from talk2data.domain.models import AccessContext, MetricAggregation, SourceStatus
from talk2data.services.csv_import import DIMENSION_COLUMNS, REGIONS, CsvDataset
from talk2data.services.policy import READ_DATA_ACTION


class CsvDemoConnector:
    def __init__(self, *, dataset: CsvDataset, connector_id: str, tenant_id: str, user_id: str) -> None:
        self._dataset = dataset
        self._tenant_id = tenant_id
        self._user_id = user_id
        self.descriptor = ConnectorDescriptor(
            connector_id=connector_id,
            connector_type="CSV_DEMO",
            dialect="sqlite",
            capabilities={ConnectorCapability.AGGREGATION, ConnectorCapability.PARAMETERIZED_FILTERS},
            maximum_rows=100,
            query_timeout_seconds=5,
        )

    async def initialize(self) -> None:
        pass

    async def test_connection(self) -> tuple[bool, str]:
        return True, "Validated CSV is available in this demo session only."

    async def discover_catalog(self, access: AccessContext) -> list[dict[str, Any]]:
        self._check_access(access)
        return [self._dataset.describe()]

    def _check_access(self, access: AccessContext) -> None:
        if (
            access.tenant_id != self._tenant_id
            or access.user_id != self._user_id
            or READ_DATA_ACTION not in access.permitted_actions
        ):
            raise ConnectorValidationError("CSV session access denied.")
        if not access.regions or not access.regions <= REGIONS:
            raise ConnectorValidationError("CSV requires explicit, recognized region scope.")

    async def validate_plan(self, plan: StructuredQueryPlan, access: AccessContext) -> list[str]:
        errors: list[str] = []
        try:
            self._check_access(access)
        except ConnectorValidationError as exc:
            errors.append(str(exc))
        if plan.tenant_id != self._tenant_id or plan.connector_id != self.descriptor.connector_id:
            errors.append("Plan does not belong to this CSV connection.")
        if plan.metric_id != "MOBILE_ACTIVATIONS" or plan.aggregation != MetricAggregation.SUM:
            errors.append("CSV demo currently supports only the governed Mobile Activations sum.")
        if plan.row_limit > self.descriptor.maximum_rows:
            errors.append("Plan exceeds the CSV result limit.")
        if not set(plan.dimensions) <= set(self._dataset.dimensions):
            errors.append("The CSV does not supply the requested dimensions.")
        for item in plan.filters:
            if (
                item.dimension_id not in self._dataset.dimensions
                or item.operator not in {"IN", "EQUALS"}
                or not item.values
            ):
                errors.append("CSV filter is not supported.")
            if item.dimension_id == "REGION" and not set(item.values) <= access.regions:
                errors.append("CSV filter exceeds the user's region scope.")
        return errors

    async def estimate_cost(self, plan: StructuredQueryPlan) -> dict[str, Any]:
        return {"source_kind": "csv_demo", "input_rows": len(self._dataset.rows), "billable_bytes": 0}

    async def execute_read_only(self, plan: StructuredQueryPlan, access: AccessContext) -> QueryReceipt:
        errors = await self.validate_plan(plan, access)
        if errors:
            raise ConnectorValidationError("; ".join(errors))
        try:
            current = resolve_time_window(plan.time_window)
            comparison = resolve_comparison_range(current, plan.comparison.comparison_type)
        except ValueError as exc:
            raise ConnectorValidationError("Unsupported CSV time window.") from exc
        for period in [current, comparison]:
            if period is not None:
                self._check_coverage(period)
        return await asyncio.to_thread(self._execute, plan, access, current, comparison)

    def _check_coverage(self, period: ResolvedRange) -> None:
        present = sum(period.start <= day <= period.end for day in self._dataset.dates)
        if present != (period.end - period.start).days + 1:
            raise SourceNotReadyError(
                "CSV needs at least one row for every requested day, including comparison days; "
                "missing dates are not treated as zero. No other data source was queried."
            )

    def _sql(
        self, plan: StructuredQueryPlan, access: AccessContext, period: ResolvedRange
    ) -> tuple[str, list[Any]]:
        dimensions = [DIMENSION_COLUMNS[item] for item in plan.dimensions]
        projection = [f"{DIMENSION_COLUMNS[item]} AS {item}" for item in plan.dimensions]
        projection.append("SUM(activations) AS value")
        projection.append("COUNT(DISTINCT date) AS observed_days")
        clauses = ["date >= ?", "date <= ?"]
        params: list[Any] = [period.start.isoformat(), period.end.isoformat()]
        for column, values in [
            ("region", sorted(access.regions)),
            *[(DIMENSION_COLUMNS[item.dimension_id], item.values) for item in plan.filters],
        ]:
            clauses.append(f"{column} IN ({', '.join('?' for _ in values)})")
            params.extend(values)
        sql = f"SELECT {', '.join(projection)} FROM facts WHERE {' AND '.join(clauses)}"
        if dimensions:
            sql += f" GROUP BY {', '.join(dimensions)} ORDER BY {', '.join(dimensions)}"
        return sql + " LIMIT ?", [*params, plan.row_limit + 1]

    def _execute(
        self,
        plan: StructuredQueryPlan,
        access: AccessContext,
        current: ResolvedRange,
        comparison: ResolvedRange | None,
    ) -> QueryReceipt:
        statements: list[str] = []
        with closing(sqlite3.connect(":memory:")) as connection:
            try:
                connection.row_factory = sqlite3.Row
                columns = ", ".join(
                    f"{name} {'INTEGER' if name == 'activations' else 'TEXT'} NOT NULL"
                    for name in self._dataset.columns
                )
                connection.execute(f"CREATE TABLE facts ({columns})")
                placeholders = ", ".join("?" for _ in self._dataset.columns)
                connection.executemany(f"INSERT INTO facts VALUES ({placeholders})", self._dataset.rows)
                connection.execute("PRAGMA query_only = ON")

                def query(period: ResolvedRange) -> list[dict[str, Any]]:
                    sql, params = self._sql(plan, access, period)
                    statements.append(sql)
                    rows = [dict(row) for row in connection.execute(sql, params).fetchall()]
                    if len(rows) > plan.row_limit:
                        raise ConnectorValidationError("Result is too large; narrow the question.")
                    for row in rows:
                        observed_days = row.pop("observed_days")
                        if observed_days and observed_days != (period.end - period.start).days + 1:
                            raise SourceNotReadyError(
                                "A CSV result group has missing days; add explicit zeros."
                            )
                    if not rows or any(row["value"] is None for row in rows):
                        raise SourceNotReadyError("No CSV observations match the requested scope.")
                    if any(not math.isfinite(float(row["value"])) for row in rows):
                        raise ConnectorValidationError("CSV aggregation is not finite.")
                    return rows

                current_rows = query(current)
                comparison_rows = [] if comparison is None else query(comparison)
            finally:
                connection.close()
        if comparison is not None:

            def keys(rows: list[dict[str, Any]]) -> set[tuple[Any, ...]]:
                return {tuple(row.get(key) for key in plan.dimensions) for row in rows}

            if keys(current_rows) != keys(comparison_rows):
                raise SourceNotReadyError("CSV comparison groups differ; missing groups are not zero.")
        rows = merge_comparison_rows(
            current_rows=current_rows,
            comparison_rows=comparison_rows,
            dimensions=plan.dimensions,
        )
        return QueryReceipt(
            query_id=plan.query_id,
            decision_id=plan.decision_id,
            plan_hash=plan.plan_hash,
            connector_id=plan.connector_id,
            source_kind="csv_demo",
            source_fingerprint=self._dataset.fingerprint,
            source_snapshot=self._dataset.uploaded_at,
            coverage_start=self._dataset.coverage_start,
            coverage_end=self._dataset.coverage_end,
            resolved_start=current.start,
            resolved_end=current.end,
            comparison_start=None if comparison is None else comparison.start,
            comparison_end=None if comparison is None else comparison.end,
            row_count=len(rows),
            result_rows=rows,
            result_hash=hashlib.sha256(
                json.dumps(
                    rows,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest(),
            sql_hash=hashlib.sha256("\n".join(statements).encode()).hexdigest(),
            data_quality_status="EXECUTED",
            policy_decision_id=str(plan.decision_id),
            data_quality_checks=[
                "PARAMETERIZED_SQL",
                "READ_ONLY_SOURCE",
                "NO_TRUNCATION",
                "DAILY_COVERAGE_CHECKED",
                "EXPLICIT_REGION_SCOPE",
            ],
            warnings=["UPLOADED_DEMO_DATA", "BUSINESS_COMPLETENESS_NOT_INDEPENDENTLY_VERIFIED"],
        )

    async def get_freshness(self) -> SourceFreshness:
        return SourceFreshness(
            status=SourceStatus.AVAILABLE,
            last_refreshed_at=self._dataset.uploaded_at,
            coverage_start=datetime.combine(self._dataset.coverage_start, datetime.min.time(), UTC),
            coverage_end=datetime.combine(self._dataset.coverage_end, datetime.max.time(), UTC),
            expected_refresh="Manual CSV upload; no automatic refresh.",
        )

    async def cancel_query(self, execution_id: str) -> bool:
        return False
