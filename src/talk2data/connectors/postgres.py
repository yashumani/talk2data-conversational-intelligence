from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any, cast

import psycopg
from psycopg import Connection, Error, sql
from psycopg.rows import dict_row

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
from talk2data.domain.chat import QueryReceipt
from talk2data.domain.models import AccessContext, FilterOperator, MetricAggregation, SourceStatus
from talk2data.domain.physical_mapping import (
    PhysicalConnectorMapping,
    PhysicalMappingError,
    PhysicalMetricMapping,
)
from talk2data.services.policy import READ_DATA_ACTION

logger = logging.getLogger(__name__)
SQLStatement = sql.SQL | sql.Composed


class PostgreSQLConnectorError(RuntimeError):
    """Base error for the governed PostgreSQL connector."""


class PostgreSQLConnectorValidationError(PostgreSQLConnectorError):
    """Raised when a governed plan violates the connector contract."""


class PostgreSQLSourceNotReadyError(PostgreSQLConnectorError):
    """Raised when PostgreSQL does not cover the requested reporting period."""


class PostgreSQLConnectorUnavailableError(PostgreSQLConnectorError):
    """Raised when the configured source cannot be reached or validated."""


class PostgreSQLConnector:
    """Read-only PostgreSQL adapter driven by a versioned physical mapping."""

    def __init__(
        self,
        *,
        mapping: PhysicalConnectorMapping,
        mapping_version: str,
        mapping_hash: str,
        dsn: str,
        maximum_rows: int | None = None,
        query_timeout_seconds: int | None = None,
        connect_timeout_seconds: int = 10,
    ) -> None:
        self._mapping = PhysicalConnectorMapping.model_validate(mapping.model_dump(mode="python"))
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN cannot be blank")
        if not mapping_version.strip():
            raise ValueError("physical mapping version cannot be blank")
        if len(mapping_hash) != 64:
            raise ValueError("physical mapping hash must be a SHA-256 hex digest")

        configured_maximum_rows = maximum_rows or self._mapping.maximum_rows
        configured_timeout = query_timeout_seconds or self._mapping.query_timeout_seconds
        effective_maximum_rows = min(configured_maximum_rows, self._mapping.maximum_rows)
        effective_timeout = min(configured_timeout, self._mapping.query_timeout_seconds)

        self.descriptor = ConnectorDescriptor(
            connector_id=self._mapping.connector_id,
            connector_type="POSTGRESQL_MAPPED",
            dialect="PostgreSQL",
            capabilities={
                ConnectorCapability.CATALOG_DISCOVERY,
                ConnectorCapability.SCHEMA_INTROSPECTION,
                ConnectorCapability.PARAMETERIZED_FILTERS,
                ConnectorCapability.AGGREGATION,
                ConnectorCapability.WINDOW_FUNCTIONS,
                ConnectorCapability.QUERY_CANCELLATION,
                ConnectorCapability.SECURITY_PUSHDOWN,
            },
            read_only=True,
            maximum_rows=effective_maximum_rows,
            query_timeout_seconds=effective_timeout,
            mapping_version=mapping_version,
            mapping_hash=mapping_hash,
        )
        self._dsn = dsn
        self._mapping_version = mapping_version
        self._mapping_hash = mapping_hash
        self._metric_mappings = {metric.metric_id: metric for metric in self._mapping.metrics}
        self._source_values = frozenset(metric.source_value for metric in self._mapping.metrics)
        self._required_columns = self._mapping.required_columns()
        self._connect_timeout_seconds = connect_timeout_seconds
        self._active_connections: dict[str, Connection[Any]] = {}
        self._active_lock = threading.Lock()

    async def initialize(self) -> None:
        try:
            await asyncio.to_thread(self._validate_reference_schema_sync)
        except (Error, OSError, ValueError) as exc:
            logger.exception(
                "PostgreSQL connector initialization failed for %s",
                self.descriptor.connector_id,
            )
            raise PostgreSQLConnectorUnavailableError(
                f"PostgreSQL connector {self.descriptor.connector_id!r} failed validation."
            ) from exc

    async def test_connection(self) -> tuple[bool, str]:
        try:
            value = await asyncio.to_thread(self._select_one_sync)
        except (Error, OSError):
            logger.warning(
                "PostgreSQL connector health check failed for %s",
                self.descriptor.connector_id,
                exc_info=True,
            )
            return False, "PostgreSQL connector is unavailable."
        if value != 1:
            return False, "PostgreSQL health query returned an unexpected value."
        return True, f"PostgreSQL connector {self.descriptor.connector_id} is ready."

    async def discover_catalog(self, access: AccessContext) -> list[dict[str, Any]]:
        if not _can_read_data(access):
            return []
        return [
            {
                "connector_id": self.descriptor.connector_id,
                "metric_id": metric.metric_id,
                "dimensions": sorted(metric.allowed_dimensions),
                "physical_object": f"{self._mapping.schema_name}.{self._mapping.table_name}",
                "mapping_version": self._mapping_version,
                "mapping_hash": self._mapping_hash,
                "synthetic": False,
            }
            for metric in sorted(self._mapping.metrics, key=lambda item: item.metric_id)
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
        if not _can_read_data(access):
            errors.append("DATA_ACTION_NOT_ALLOWED")

        metric_mapping = self._metric_mappings.get(plan.metric_id)
        if metric_mapping is None:
            errors.append("METRIC_NOT_AVAILABLE_ON_CONNECTOR")
            return errors

        if plan.aggregation != metric_mapping.aggregation:
            errors.append("AGGREGATION_CONTRACT_MISMATCH")
        if set(plan.dimensions) - metric_mapping.allowed_dimensions:
            errors.append("DIMENSION_NOT_ALLOWED")
        if plan.row_limit > self.descriptor.maximum_rows:
            errors.append("ROW_LIMIT_EXCEEDED")

        try:
            scoped_regions = self._mapping.resolve_scope_values("REGION", access.regions)
        except PhysicalMappingError:
            scoped_regions = set()
            errors.append("REGION_SCOPE_UNMAPPED")
        for query_filter in plan.filters:
            if query_filter.dimension_id not in metric_mapping.allowed_dimensions:
                errors.append("FILTER_DIMENSION_NOT_ALLOWED")
            if query_filter.operator not in {FilterOperator.IN, FilterOperator.EQUALS}:
                errors.append("FILTER_OPERATOR_NOT_SUPPORTED")
            if query_filter.dimension_id == "REGION" and access.regions:
                if set(query_filter.values) - scoped_regions:
                    errors.append("REGION_SCOPE_VIOLATION")

        try:
            resolve_time_window(plan.time_window)
        except ValueError:
            errors.append("INVALID_TIME_WINDOW")
        return list(dict.fromkeys(errors))

    async def estimate_cost(self, plan: StructuredQueryPlan) -> dict[str, Any]:
        return {
            "connector_id": self.descriptor.connector_id,
            "estimated_rows": min(plan.row_limit, self.descriptor.maximum_rows),
            "estimated_cost": None,
            "unit": "source-managed",
            "mapping_hash": self._mapping_hash,
            "note": "The mapped adapter does not run an unrestricted source EXPLAIN.",
        }

    async def execute_read_only(
        self,
        plan: StructuredQueryPlan,
        access: AccessContext,
    ) -> QueryReceipt:
        errors = await self.validate_plan(plan, access)
        if errors:
            raise PostgreSQLConnectorValidationError(", ".join(errors))
        try:
            return await asyncio.to_thread(self._execute_sync, plan, access)
        except PostgreSQLConnectorError:
            raise
        except (Error, OSError, ValueError) as exc:
            logger.exception(
                "PostgreSQL execution failed for connector %s",
                self.descriptor.connector_id,
            )
            raise PostgreSQLConnectorUnavailableError(
                "PostgreSQL execution failed before a result could be certified."
            ) from exc

    async def get_freshness(self) -> SourceFreshness:
        try:
            state = await asyncio.to_thread(self._source_state_sync, self._source_values)
        except (Error, OSError, ValueError):
            logger.warning(
                "PostgreSQL freshness check failed for %s",
                self.descriptor.connector_id,
                exc_info=True,
            )
            return SourceFreshness(
                status=SourceStatus.UNAVAILABLE,
                expected_refresh=self._mapping.expected_refresh,
                known_delay="Source freshness check failed.",
            )
        if state is None:
            return SourceFreshness(
                status=SourceStatus.NOT_READY,
                expected_refresh=self._mapping.expected_refresh,
                known_delay="No governed metric rows are available.",
            )
        snapshot, coverage_start, coverage_end = state
        return SourceFreshness(
            status=SourceStatus.AVAILABLE,
            last_refreshed_at=snapshot,
            coverage_start=datetime.combine(
                coverage_start,
                datetime.min.time(),
                tzinfo=UTC,
            ),
            coverage_end=datetime.combine(
                coverage_end,
                datetime.max.time(),
                tzinfo=UTC,
            ),
            expected_refresh=self._mapping.expected_refresh,
        )

    async def cancel_query(self, execution_id: str) -> bool:
        with self._active_lock:
            connection = self._active_connections.get(execution_id)
        if connection is None:
            return False
        try:
            await asyncio.to_thread(connection.cancel)
        except Error:
            return False
        return True

    @contextmanager
    def _connection(self) -> Iterator[Connection[Any]]:
        connection: Connection[Any] = psycopg.connect(
            self._dsn,
            autocommit=False,
            connect_timeout=self._connect_timeout_seconds,
            row_factory=dict_row,
            application_name="talk2data",
        )
        try:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (f"{self.descriptor.query_timeout_seconds * 1000}ms",),
            )
            connection.execute(
                "SELECT set_config('lock_timeout', %s, true)",
                ("5000ms",),
            )
            yield connection
        finally:
            try:
                connection.rollback()
            finally:
                connection.close()

    def _select_one_sync(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT 1 AS value").fetchone()
        if row is None:
            return 0
        return int(cast(dict[str, Any], row)["value"])

    def _validate_reference_schema_sync(self) -> None:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                """,
                (self._mapping.schema_name, self._mapping.table_name),
            ).fetchall()
        columns = {str(cast(dict[str, Any], row)["column_name"]) for row in rows}
        missing = self._required_columns - columns
        if missing:
            raise ValueError("mapped metric-fact table is missing columns: " + ", ".join(sorted(missing)))

    def _source_state_sync(
        self,
        source_values: frozenset[str],
    ) -> tuple[datetime, date, date] | None:
        with self._connection() as connection:
            return self._source_state(connection, source_values)

    def _source_state(
        self,
        connection: Connection[Any],
        source_values: frozenset[str],
    ) -> tuple[datetime, date, date] | None:
        query = sql.SQL(
            """
            SELECT
                CURRENT_TIMESTAMP AS source_snapshot,
                MIN({fact_date})::date AS coverage_start,
                MAX({period_end})::date AS coverage_end
            FROM {table}
            WHERE {metric_id} = ANY(%s)
            """
        ).format(
            fact_date=sql.Identifier(self._mapping.fact_date_column),
            period_end=sql.Identifier(self._mapping.period_end_column),
            table=self._qualified_table(),
            metric_id=sql.Identifier(self._mapping.metric_id_column),
        )
        row = connection.execute(query, (sorted(source_values),)).fetchone()
        if row is None:
            return None
        item = cast(dict[str, Any], row)
        if item["coverage_start"] is None or item["coverage_end"] is None:
            return None
        snapshot = cast(datetime, item["source_snapshot"])
        if snapshot.tzinfo is None:
            snapshot = snapshot.replace(tzinfo=UTC)
        return (
            snapshot.astimezone(UTC),
            cast(date, item["coverage_start"]),
            cast(date, item["coverage_end"]),
        )

    def _execute_sync(
        self,
        plan: StructuredQueryPlan,
        access: AccessContext,
    ) -> QueryReceipt:
        metric_mapping = self._metric_mappings[plan.metric_id]
        current_range = resolve_time_window(plan.time_window)
        comparison_range = resolve_comparison_range(
            current_range,
            plan.comparison.comparison_type,
        )
        execution_id = str(plan.query_id)
        with self._connection() as connection:
            state = self._source_state(
                connection,
                frozenset({metric_mapping.source_value}),
            )
            if state is None:
                raise PostgreSQLSourceNotReadyError(
                    f"No certified rows are available for metric {plan.metric_id}."
                )
            source_snapshot, coverage_start, coverage_end = state
            requested_ranges = [current_range]
            if comparison_range is not None:
                requested_ranges.append(comparison_range)
            if any(item.start < coverage_start or item.end > coverage_end for item in requested_ranges):
                raise PostgreSQLSourceNotReadyError(
                    "The requested period is outside the source coverage "
                    f"{coverage_start.isoformat()} through {coverage_end.isoformat()}."
                )

            with self._active_lock:
                self._active_connections[execution_id] = connection
            try:
                current_query, current_parameters = self._build_query(
                    plan,
                    access,
                    current_range,
                    metric_mapping,
                )
                current_rows = self._query(
                    connection,
                    current_query,
                    current_parameters,
                )

                comparison_rows: list[dict[str, Any]] = []
                comparison_query: SQLStatement | None = None
                if comparison_range is not None:
                    comparison_query, comparison_parameters = self._build_query(
                        plan,
                        access,
                        comparison_range,
                        metric_mapping,
                    )
                    comparison_rows = self._query(
                        connection,
                        comparison_query,
                        comparison_parameters,
                    )
            finally:
                with self._active_lock:
                    self._active_connections.pop(execution_id, None)

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
            sql_payload = current_query.as_string(connection)
            if comparison_query is not None:
                sql_payload += "\n-- comparison\n" + comparison_query.as_string(connection)

        return QueryReceipt(
            query_id=plan.query_id,
            decision_id=plan.decision_id,
            plan_hash=plan.plan_hash,
            connector_id=plan.connector_id,
            source_snapshot=source_snapshot,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            resolved_start=current_range.start,
            resolved_end=current_range.end,
            comparison_start=None if comparison_range is None else comparison_range.start,
            comparison_end=None if comparison_range is None else comparison_range.end,
            row_count=len(result_rows),
            result_rows=result_rows,
            result_hash=hashlib.sha256(canonical_results.encode("utf-8")).hexdigest(),
            sql_hash=hashlib.sha256(sql_payload.encode("utf-8")).hexdigest(),
            physical_mapping_version=self._mapping_version,
            physical_mapping_hash=self._mapping_hash,
            data_quality_status="EXECUTED",
            data_quality_checks=[
                "PARAMETERIZED_SQL",
                "IDENTIFIER_ALLOWLIST",
                "PHYSICAL_MAPPING_PINNED",
                "POSTGRESQL_READ_ONLY_TRANSACTION",
                "REPEATABLE_READ_SNAPSHOT",
                "SOURCE_COVERAGE_CONFIRMED",
                "GOVERNED_SCOPE_MAPPING_APPLIED",
            ],
            policy_decision_id=str(plan.decision_id),
            warnings=[],
        )

    def _query(
        self,
        connection: Connection[Any],
        query: SQLStatement,
        parameters: tuple[Any, ...],
    ) -> list[dict[str, Any]]:
        rows = connection.execute(query, parameters).fetchall()
        normalized: list[dict[str, Any]] = []
        for row in rows:
            item = dict(cast(dict[str, Any], row))
            value = item.get("value")
            if value is not None:
                numeric = float(value)
                if not math.isfinite(numeric):
                    continue
                item["value"] = numeric
            normalized.append(item)
        return normalized

    def _build_query(
        self,
        plan: StructuredQueryPlan,
        access: AccessContext,
        resolved_range: ResolvedRange,
        metric_mapping: PhysicalMetricMapping,
    ) -> tuple[SQLStatement, tuple[Any, ...]]:
        dimension_columns = [self._mapping.dimensions[dimension] for dimension in plan.dimensions]
        select_parts: list[sql.Composable] = [
            sql.SQL("{} AS {}").format(
                sql.Identifier(column),
                sql.Identifier(dimension),
            )
            for column, dimension in zip(
                dimension_columns,
                plan.dimensions,
                strict=True,
            )
        ]
        if metric_mapping.aggregation == MetricAggregation.RATIO:
            if metric_mapping.numerator_column is None or metric_mapping.denominator_column is None:
                raise PostgreSQLConnectorValidationError("ratio physical mapping is incomplete")
            value_expression = sql.SQL(
                "CASE WHEN SUM({denominator}) = 0 THEN NULL "
                "ELSE SUM({numerator})::double precision / SUM({denominator}) END"
            ).format(
                numerator=sql.Identifier(metric_mapping.numerator_column),
                denominator=sql.Identifier(metric_mapping.denominator_column),
            )
        else:
            if metric_mapping.amount_column is None:
                raise PostgreSQLConnectorValidationError("additive physical mapping is incomplete")
            value_expression = sql.SQL("SUM({})::double precision").format(
                sql.Identifier(metric_mapping.amount_column)
            )
        select_parts.append(
            sql.SQL("{} AS {}").format(
                value_expression,
                sql.Identifier("value"),
            )
        )

        where: list[sql.Composable] = [
            sql.SQL("{} = %s").format(sql.Identifier(self._mapping.metric_id_column)),
            sql.SQL("{} >= %s").format(sql.Identifier(self._mapping.fact_date_column)),
            sql.SQL("{} <= %s").format(sql.Identifier(self._mapping.period_end_column)),
        ]
        parameters: list[Any] = [
            metric_mapping.source_value,
            resolved_range.start,
            resolved_range.end,
        ]
        for query_filter in plan.filters:
            column = self._mapping.dimensions[query_filter.dimension_id]
            where.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier(column)))
            parameters.append(list(query_filter.values))

        try:
            scoped_regions = sorted(self._mapping.resolve_scope_values("REGION", access.regions))
        except PhysicalMappingError as exc:
            raise PostgreSQLConnectorValidationError("REGION_SCOPE_UNMAPPED") from exc
        if scoped_regions and "REGION" in metric_mapping.allowed_dimensions:
            where.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier(self._mapping.dimensions["REGION"])))
            parameters.append(scoped_regions)

        query: SQLStatement = sql.SQL("SELECT {select} FROM {table} WHERE {where}").format(
            select=sql.SQL(", ").join(select_parts),
            table=self._qualified_table(),
            where=sql.SQL(" AND ").join(where),
        )
        if dimension_columns:
            group_by = sql.SQL(", ").join(sql.Identifier(column) for column in dimension_columns)
            query = query + sql.SQL(" GROUP BY {group_by} ORDER BY {group_by}").format(group_by=group_by)
        query = query + sql.SQL(" LIMIT %s")
        parameters.append(plan.row_limit)
        return query, tuple(parameters)

    def _qualified_table(self) -> sql.Composed:
        return sql.SQL(".").join(
            [
                sql.Identifier(self._mapping.schema_name),
                sql.Identifier(self._mapping.table_name),
            ]
        )


def _can_read_data(access: AccessContext) -> bool:
    return READ_DATA_ACTION in access.permitted_actions or "TALK2DATA_ADMIN" in access.roles
