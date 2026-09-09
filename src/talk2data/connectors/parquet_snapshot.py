"""Fast governed queries over an operator-created, immutable Parquet snapshot."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

import duckdb

from talk2data.connectors.base import (
    ConnectorCapability,
    ConnectorDescriptor,
    SourceFreshness,
    StructuredQueryPlan,
)
from talk2data.connectors.bigquery import BigQueryConnector
from talk2data.connectors.errors import ConnectorValidationError, SourceNotReadyError
from talk2data.core.parquet_config import ParquetSnapshotSettings
from talk2data.domain.bigquery_mapping import BigQueryMapping
from talk2data.domain.chat import QueryReceipt
from talk2data.domain.models import CLASSIFICATION_RANK, AccessContext, MetricAggregation, SourceStatus
from talk2data.domain.parquet_snapshot import ParquetSnapshotManifest
from talk2data.services.analytical_policy import validate_analytical_plan
from talk2data.services.bigquery_port import CloudResult
from talk2data.services.policy import READ_DATA_ACTION


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ParquetSnapshotConnector:
    def __init__(self, mapping: BigQueryMapping, settings: ParquetSnapshotSettings) -> None:
        self.mapping, self.settings = mapping, settings
        self._metrics = {metric.metric_id: metric for metric in mapping.metrics}
        self._manifest: ParquetSnapshotManifest | None = None
        self._path: Path | None = None
        self._active: dict[str, duckdb.DuckDBPyConnection] = {}
        self._lock = Lock()
        self.descriptor = ConnectorDescriptor(
            connector_id=mapping.connector_id,
            connector_type="PARQUET_SNAPSHOT",
            dialect="DUCKDB",
            capabilities={
                ConnectorCapability.PARAMETERIZED_FILTERS,
                ConnectorCapability.AGGREGATION,
                ConnectorCapability.QUERY_CANCELLATION,
                ConnectorCapability.SECURITY_PUSHDOWN,
            },
            maximum_rows=min(settings.maximum_rows, 1_000),
            query_timeout_seconds=settings.query_timeout_seconds,
            mapping_version=mapping.version,
            mapping_hash=mapping.fingerprint(),
        )

    async def initialize(self) -> None:
        await asyncio.to_thread(self._load_and_verify)

    def _load_and_verify(self) -> None:
        manifest_path = self.settings.directory / ParquetSnapshotManifest.filename(self.mapping.fingerprint())
        manifest = ParquetSnapshotManifest.model_validate_json(manifest_path.read_bytes())
        path = self.settings.directory / manifest.parquet_file
        if (
            manifest.tenant_id != self.mapping.tenant_id
            or manifest.connector_id != self.mapping.connector_id
            or manifest.mapping_hash != self.mapping.fingerprint()
            or manifest.source_view != self.mapping.view
            or path.parent != self.settings.directory
            or not path.is_file()
            or path.is_symlink()
            or _sha256(path) != manifest.parquet_sha256
        ):
            raise ValueError("The Parquet snapshot does not match its approved source mapping.")
        age = (datetime.now(UTC) - manifest.materialized_at.astimezone(UTC)).total_seconds()
        if age < 0 or age > self.settings.maximum_age_seconds:
            raise ValueError("The Parquet snapshot is outside its approved freshness window.")
        connection = duckdb.connect(database=":memory:", read_only=False)
        try:
            count = connection.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()
            if count is None or count[0] != manifest.row_count:
                raise ValueError("The Parquet snapshot row count does not match its manifest.")
        finally:
            connection.close()
        self._manifest, self._path = manifest, path

    async def test_connection(self) -> tuple[bool, str]:
        try:
            await self.initialize()
        except (OSError, ValueError, duckdb.Error):
            return False, "The approved Parquet snapshot is unavailable."
        return True, "The approved Parquet snapshot is ready."

    async def discover_catalog(self, access: AccessContext) -> list[dict[str, Any]]:
        if access.tenant_id != self.mapping.tenant_id or READ_DATA_ACTION not in access.permitted_actions:
            return []
        return [
            {
                "connector_id": self.mapping.connector_id,
                "metric_id": metric.metric_id,
                "dimensions": sorted(
                    dimension
                    for dimension in metric.allowed_dimensions
                    if CLASSIFICATION_RANK[self.mapping.dimension_classifications[dimension]]
                    <= CLASSIFICATION_RANK[access.classification_clearance]
                ),
                "mapping_version": self.mapping.version,
                "source_kind": "parquet_snapshot",
            }
            for metric in self.mapping.metrics
            if CLASSIFICATION_RANK[metric.classification]
            <= CLASSIFICATION_RANK[access.classification_clearance]
        ]

    async def validate_plan(self, plan: StructuredQueryPlan, access: AccessContext) -> list[str]:
        return validate_analytical_plan(self.mapping, self.descriptor.maximum_rows, plan, access)

    async def estimate_cost(self, plan: StructuredQueryPlan) -> dict[str, Any]:
        return {"connector_id": plan.connector_id, "cloud_bytes_billed": 0, "local_snapshot": True}

    async def execute_read_only(self, plan: StructuredQueryPlan, access: AccessContext) -> QueryReceipt:
        failures = await self.validate_plan(plan, access)
        if failures:
            raise ConnectorValidationError(", ".join(failures))
        if self._manifest is None or self._path is None:
            raise SourceNotReadyError("The Parquet snapshot has not been initialized.")
        sql, parameters, statement = self._compile(plan, access)
        execution_id = str(plan.query_id)
        connection = duckdb.connect(database=":memory:", read_only=False)
        with self._lock:
            if execution_id in self._active:
                connection.close()
                raise ConnectorValidationError("QUERY_ALREADY_RUNNING")
            self._active[execution_id] = connection
        try:
            async with asyncio.timeout(self.settings.query_timeout_seconds):
                raw = await asyncio.to_thread(self._execute, connection, sql, parameters)
        except (TimeoutError, asyncio.CancelledError):
            connection.interrupt()
            raise
        except duckdb.Error as exc:
            raise ConnectorValidationError("Parquet execution failed before certification.") from exc
        finally:
            with self._lock:
                self._active.pop(execution_id, None)
            connection.close()
        local_result = CloudResult("local", "local", "local", raw, len(raw), 0, 0, True, None, None)
        rows, _ = BigQueryConnector._validate_rows(plan, statement, local_result)
        serialized = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False)
        manifest = self._manifest
        return QueryReceipt(
            source_kind="parquet_snapshot",
            source_fingerprint=manifest.parquet_sha256,
            source_snapshot=manifest.source_snapshot,
            query_id=plan.query_id,
            decision_id=plan.decision_id,
            plan_hash=plan.plan_hash,
            connector_id=plan.connector_id,
            coverage_start=statement.current.start
            if statement.comparison is None
            else statement.comparison.start,
            coverage_end=statement.current.end,
            resolved_start=statement.current.start,
            resolved_end=statement.current.end,
            comparison_start=None if statement.comparison is None else statement.comparison.start,
            comparison_end=None if statement.comparison is None else statement.comparison.end,
            row_count=len(rows),
            result_rows=rows,
            result_hash=hashlib.sha256(serialized.encode()).hexdigest(),
            sql_hash=hashlib.sha256(sql.encode()).hexdigest(),
            physical_mapping_version=self.mapping.version,
            physical_mapping_hash=self.mapping.fingerprint(),
            data_quality_status="EXECUTED_FROM_MATERIALIZED_SNAPSHOT",
            data_quality_checks=[
                "PARAMETERIZED_SELECT",
                "TENANT_REGION_UNIT_SCOPE",
                "PARQUET_HASH_VERIFIED",
                "SNAPSHOT_FRESHNESS",
                "COMPLETE_DAILY_GROUPS",
                "MAPPING_PINNED",
            ],
            policy_decision_id=str(plan.decision_id),
            warnings=["Results reflect the materialized snapshot, not live BigQuery."],
        )

    def _compile(self, plan: StructuredQueryPlan, access: AccessContext) -> tuple[str, list[Any], Any]:
        from talk2data.services.bigquery_sql import compile_bigquery

        metric = self._metrics[plan.metric_id]
        statement = compile_bigquery(self.mapping, metric, plan, access)
        fact_date = _quote(self.mapping.date_column)
        periods = [("current", statement.current)]
        if statement.comparison is not None:
            periods.append(("comparison", statement.comparison))
        period_sql = (
            "CASE "
            + " ".join(f"WHEN {fact_date} BETWEEN ? AND ? THEN '{label}'" for label, _ in periods)
            + " END"
        )
        parameters: list[Any] = [value for _, period in periods for value in (period.start, period.end)]
        region_parameters = ",".join("?" for _ in access.regions)
        unit_parameters = ",".join("?" for _ in access.business_units)
        where = [
            f"{_quote(self.mapping.tenant_column)} = ?",
            f"{_quote(self.mapping.metric_column)} = ?",
            f"{_quote(self.mapping.dimensions['REGION'])} IN ({region_parameters})",
            f"{_quote(self.mapping.business_unit_column)} IN ({unit_parameters})",
            "(" + " OR ".join(f"{fact_date} BETWEEN ? AND ?" for _ in periods) + ")",
        ]
        parameters.extend(
            [access.tenant_id, metric.source_value, *sorted(access.regions), *sorted(access.business_units)]
        )
        parameters.extend(value for _, period in periods for value in (period.start, period.end))
        for item in plan.filters:
            where.append(
                f"{_quote(self.mapping.dimensions[item.dimension_id])} IN "
                f"({','.join('?' for _ in item.values)})"
            )
            parameters.extend(item.values)
        if metric.aggregation == MetricAggregation.RATIO:
            numerator = _quote(str(metric.numerator_column))
            denominator = _quote(str(metric.denominator_column))
            expression = f"SUM({numerator}) / NULLIF(SUM({denominator}), 0)"
            invalid = f"{numerator} IS NULL OR {denominator} IS NULL"
        else:
            amount = _quote(str(metric.amount_column))
            expression, invalid = f"SUM({amount})", f"{amount} IS NULL"
        dimensions = [_quote(self.mapping.dimensions[item]) for item in plan.dimensions]
        snapshot_column = _quote(self.mapping.snapshot_column)
        invalid_count = f"SUM(CASE WHEN {invalid} OR {snapshot_column} IS NULL THEN 1 ELSE 0 END) AS _invalid"
        selected = [
            f"{period_sql} AS _period",
            *(
                f"{column} AS {_quote(item)}"
                for item, column in zip(plan.dimensions, dimensions, strict=True)
            ),
            f"{expression} AS value",
            f"COUNT(DISTINCT {fact_date}) AS _days",
            f"MIN({fact_date}) AS _start",
            f"MAX({fact_date}) AS _end",
            f"MAX({snapshot_column}) AS _snapshot",
            invalid_count,
        ]
        groups = ", ".join(["_period", *(_quote(item) for item in plan.dimensions)])
        limit = plan.row_limit * len(periods) + 1
        sql = (
            "SELECT "
            + ", ".join(selected)
            + " FROM read_parquet(?) WHERE "
            + " AND ".join(where)
            + f" GROUP BY {groups} ORDER BY {groups} LIMIT {limit}"
        )
        parameters.insert(len(periods) * 2, str(self._path))
        return sql, parameters, statement

    @staticmethod
    def _execute(
        connection: duckdb.DuckDBPyConnection, sql: str, parameters: list[Any]
    ) -> list[dict[str, Any]]:
        cursor = connection.execute(sql, parameters)
        names = [item[0] for item in cursor.description]
        rows = [dict(zip(names, values, strict=True)) for values in cursor.fetchall()]
        for row in rows:
            value = row.get("value")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Non-finite aggregate")
            snapshot = row.get("_snapshot")
            if isinstance(snapshot, str):
                try:
                    snapshot = datetime.fromisoformat(snapshot.replace("Z", "+00:00"))
                except ValueError:
                    pass
            if isinstance(snapshot, datetime) and snapshot.tzinfo is None:
                snapshot = snapshot.replace(tzinfo=UTC)
            row["_snapshot"] = snapshot
        return rows

    async def get_freshness(self) -> SourceFreshness:
        if self._manifest is None:
            return SourceFreshness(status=SourceStatus.NOT_READY, known_delay="Snapshot not initialized.")
        return SourceFreshness(
            status=SourceStatus.AVAILABLE,
            last_refreshed_at=self._manifest.materialized_at,
            coverage_start=self._manifest.coverage_start,
            coverage_end=self._manifest.coverage_end,
            known_delay="Bounded by the operator-controlled materialization schedule.",
        )

    async def cancel_query(self, execution_id: str) -> bool:
        with self._lock:
            connection = self._active.get(execution_id)
        if connection is None:
            return False
        connection.interrupt()
        return True
