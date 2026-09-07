"""Governed BigQuery connector; selected only by the separate internal application."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from datetime import UTC, datetime
from threading import Event, Lock
from typing import Any

from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import GoogleAuthError

from talk2data.connectors.base import (
    ConnectorCapability,
    ConnectorDescriptor,
    SourceFreshness,
    StructuredQueryPlan,
)
from talk2data.connectors.demo_sqlite import merge_comparison_rows, resolve_time_window
from talk2data.connectors.errors import ConnectorValidationError, SourceNotReadyError
from talk2data.core.bigquery_config import BigQuerySettings
from talk2data.domain.bigquery_mapping import BigQueryMapping
from talk2data.domain.chat import CloudQueryExecution, QueryReceipt
from talk2data.domain.models import (
    CLASSIFICATION_RANK,
    AccessContext,
    FilterOperator,
    MetricValueType,
    SourceStatus,
    TimeGrain,
)
from talk2data.services.bigquery_port import BigQueryTransport, CloudResult
from talk2data.services.bigquery_sql import BigQueryStatement, compile_bigquery
from talk2data.services.policy import READ_DATA_ACTION


class BigQueryConnector:
    def __init__(
        self, mapping: BigQueryMapping, settings: BigQuerySettings, transport: BigQueryTransport
    ) -> None:
        self.mapping, self.settings, self.transport = mapping, settings, transport
        self._metrics = {metric.metric_id: metric for metric in mapping.metrics}
        self._active: dict[str, tuple[str, Event]] = {}
        self._lock = Lock()
        self.descriptor = ConnectorDescriptor(
            connector_id=mapping.connector_id,
            connector_type="BIGQUERY",
            dialect="GOOGLESQL",
            capabilities={
                ConnectorCapability.PARAMETERIZED_FILTERS,
                ConnectorCapability.AGGREGATION,
                ConnectorCapability.QUERY_CANCELLATION,
                ConnectorCapability.SECURITY_PUSHDOWN,
            },
            maximum_rows=settings.maximum_rows,
            query_timeout_seconds=settings.query_timeout_seconds,
            mapping_version=mapping.version,
            mapping_hash=mapping.fingerprint(),
        )

    async def initialize(self) -> None:
        await asyncio.to_thread(self.transport.validate_view, self.mapping)

    async def test_connection(self) -> tuple[bool, str]:
        try:
            await self.initialize()
        except (GoogleAPICallError, GoogleAuthError, OSError, ValueError):
            return False, "The approved BigQuery view is unavailable."
        return True, "The approved BigQuery view contract is ready."

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
            }
            for metric in self.mapping.metrics
            if CLASSIFICATION_RANK[metric.classification]
            <= CLASSIFICATION_RANK[access.classification_clearance]
        ]

    async def validate_plan(self, plan: StructuredQueryPlan, access: AccessContext) -> list[str]:
        errors = []
        if plan.connector_id != self.mapping.connector_id:
            errors.append("CONNECTOR_ID_MISMATCH")
        if plan.tenant_id != access.tenant_id or access.tenant_id != self.mapping.tenant_id:
            errors.append("TENANT_SCOPE_MISMATCH")
        if (
            READ_DATA_ACTION not in access.permitted_actions
            or not access.regions
            or not access.business_units
        ):
            errors.append("EXPLICIT_DATA_SCOPE_REQUIRED")
        metric = self._metrics.get(plan.metric_id)
        if metric is None:
            return [*errors, "METRIC_NOT_AVAILABLE"]
        clearance = CLASSIFICATION_RANK[access.classification_clearance]
        if CLASSIFICATION_RANK[metric.classification] > clearance:
            errors.append("METRIC_CLASSIFICATION_DENIED")
        referenced_dimensions = set(plan.dimensions) | {item.dimension_id for item in plan.filters}
        if any(
            CLASSIFICATION_RANK[self.mapping.dimension_classifications[dimension]] > clearance
            for dimension in referenced_dimensions & self.mapping.dimensions.keys()
        ):
            errors.append("DIMENSION_CLASSIFICATION_DENIED")
        if any(
            getattr(plan, field) != getattr(metric, field)
            for field in ("semantic_version", "aggregation", "value_type", "unit", "currency")
        ):
            errors.append("SEMANTIC_CONTRACT_MISMATCH")
        if (
            len(plan.dimensions) != len(set(plan.dimensions))
            or set(plan.dimensions) - metric.allowed_dimensions
        ):
            errors.append("DIMENSION_NOT_ALLOWED")
        if plan.row_limit > self.settings.maximum_rows:
            errors.append("ROW_LIMIT_EXCEEDED")
        for item in plan.filters:
            if item.dimension_id not in metric.allowed_dimensions or item.operator not in {
                FilterOperator.IN,
                FilterOperator.EQUALS,
            }:
                errors.append("FILTER_NOT_ALLOWED")
            if item.dimension_id == "REGION" and set(item.values) - access.regions:
                errors.append("REGION_SCOPE_VIOLATION")
        try:
            period = resolve_time_window(plan.time_window)
            if (
                plan.time_window.calendar != "GREGORIAN"
                or plan.time_window.timezone != "UTC"
                or plan.time_window.grain == TimeGrain.HOUR
                or plan.time_window.grain not in metric.supported_time_grains
                or (period.end - period.start).days > 730
            ):
                errors.append("TIME_CONTRACT_NOT_SUPPORTED")
        except ValueError:
            errors.append("INVALID_TIME_WINDOW")
        return sorted(set(errors))

    async def estimate_cost(self, plan: StructuredQueryPlan) -> dict[str, Any]:
        # The generic port has no identity parameter; never issue an unscoped estimate.
        return {
            "connector_id": self.mapping.connector_id,
            "requires_authorized_execution": True,
            "maximum_bytes_billed": self.settings.maximum_bytes_billed,
        }

    async def execute_read_only(self, plan: StructuredQueryPlan, access: AccessContext) -> QueryReceipt:
        failures = await self.validate_plan(plan, access)
        if failures:
            raise ConnectorValidationError(", ".join(failures))
        statement = compile_bigquery(self.mapping, self._metrics[plan.metric_id], plan, access)
        job_id = "t2d_" + hashlib.sha256((str(plan.query_id) + statement.scope_hash).encode()).hexdigest()
        cancelled = Event()
        execution_id = str(plan.query_id)
        with self._lock:
            if execution_id in self._active:
                raise ConnectorValidationError("QUERY_ALREADY_RUNNING")
            self._active[execution_id] = (job_id, cancelled)
        try:
            async with asyncio.timeout(
                self.settings.query_timeout_seconds + self.settings.api_timeout_seconds * 2
            ):
                return await asyncio.to_thread(self._execute, plan, statement, job_id, cancelled)
        except (asyncio.CancelledError, TimeoutError):
            cancelled.set()
            await asyncio.to_thread(self.transport.cancel, job_id)
            raise
        except (GoogleAPICallError, GoogleAuthError, OSError, ValueError) as exc:
            cancelled.set()
            await asyncio.to_thread(self.transport.cancel, job_id)
            raise ConnectorValidationError(
                "BigQuery execution failed before a result could be certified."
            ) from exc
        finally:
            with self._lock:
                self._active.pop(execution_id, None)

    def _execute(
        self, plan: StructuredQueryPlan, statement: BigQueryStatement, job_id: str, cancelled: Event
    ) -> QueryReceipt:
        estimate = self.transport.dry_run(statement)
        if estimate.location != self.settings.location or estimate.statement_type != "SELECT":
            raise ConnectorValidationError("DRY_RUN_EXECUTION_CONTRACT_REJECTED")
        if not estimate.references or estimate.references - self.mapping.allowed_references:
            raise ConnectorValidationError("DRY_RUN_REFERENCES_NOT_APPROVED")
        estimated = estimate.estimated_bytes
        if estimated is None or estimated < 0 or estimated > self.settings.maximum_bytes_billed:
            raise ConnectorValidationError("SCAN_BUDGET_EXCEEDED_OR_UNKNOWN")
        if cancelled.is_set():
            raise TimeoutError("Query cancelled before execution.")
        result = self.transport.execute(statement, job_id, cancelled)
        if cancelled.is_set():
            raise TimeoutError("Query cancelled before result release.")
        if (
            result.job_id != job_id
            or result.billing_project != self.settings.billing_project
            or result.location != self.settings.location
        ):
            raise ConnectorValidationError("CLOUD_JOB_IDENTITY_MISMATCH")
        rows, snapshot = self._validate_rows(plan, statement, result)
        serialized = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False)
        periods = [statement.current] + ([] if statement.comparison is None else [statement.comparison])
        return QueryReceipt(
            source_kind="bigquery",
            source_snapshot=snapshot,
            query_id=plan.query_id,
            decision_id=plan.decision_id,
            plan_hash=plan.plan_hash,
            connector_id=plan.connector_id,
            coverage_start=min(p.start for p in periods),
            coverage_end=max(p.end for p in periods),
            resolved_start=statement.current.start,
            resolved_end=statement.current.end,
            comparison_start=None if statement.comparison is None else statement.comparison.start,
            comparison_end=None if statement.comparison is None else statement.comparison.end,
            row_count=len(rows),
            result_rows=rows,
            result_hash=hashlib.sha256(serialized.encode()).hexdigest(),
            sql_hash=hashlib.sha256(statement.sql.encode()).hexdigest(),
            physical_mapping_version=self.mapping.version,
            physical_mapping_hash=self.mapping.fingerprint(),
            data_quality_status="EXECUTED",
            policy_decision_id=str(plan.decision_id),
            data_quality_checks=[
                "PARAMETERIZED_SELECT",
                "TENANT_REGION_UNIT_SCOPE",
                "APPROVED_VIEW",
                "DRY_RUN_VALIDATED",
                "SCAN_BUDGET",
                "COMPLETE_DAILY_GROUPS",
                "MAPPING_PINNED",
            ],
            cloud_job=CloudQueryExecution(
                job_id=job_id,
                billing_project=result.billing_project,
                location=result.location,
                estimated_bytes=estimated,
                maximum_bytes_billed=self.settings.maximum_bytes_billed,
                processed_bytes=result.processed_bytes,
                billed_bytes=result.billed_bytes,
                cache_hit=result.cache_hit,
                started_at=result.started_at,
                ended_at=result.ended_at,
                scope_hash=statement.scope_hash,
                semantic_version=plan.semantic_version,
            ),
        )

    @staticmethod
    def _validate_rows(
        plan: StructuredQueryPlan, statement: BigQueryStatement, result: CloudResult
    ) -> tuple[list[dict[str, Any]], datetime]:
        if result.total_rows != len(result.rows) or len(result.rows) >= statement.maximum_result_rows:
            raise ConnectorValidationError("RESULT_TRUNCATED")
        groups: dict[str, dict[tuple[str, ...], dict[str, Any]]] = {"current": {}, "comparison": {}}
        snapshots = []
        for row in result.rows:
            label = row.get("_period")
            if label not in groups or (label == "comparison" and statement.comparison is None):
                raise ConnectorValidationError("UNEXPECTED_RESULT_PERIOD")
            period = statement.current if label == "current" else statement.comparison
            if (
                period is None
                or row.get("_start") != period.start
                or row.get("_end") != period.end
                or row.get("_days") != (period.end - period.start).days + 1
                or row.get("_invalid") != 0
            ):
                raise SourceNotReadyError(
                    "The source does not cover every requested day with valid observations."
                )
            key_values = [row.get(dimension) for dimension in plan.dimensions]
            if any(not isinstance(value, str) or not value for value in key_values):
                raise ConnectorValidationError("INVALID_DIMENSION_VALUE")
            key = tuple(str(value) for value in key_values)
            value = row.get("value")
            if isinstance(value, bool) or value is None:
                raise SourceNotReadyError("The requested metric is undefined for this source period.")
            numeric = float(value)
            if not math.isfinite(numeric) or key in groups[label]:
                raise ConnectorValidationError("NON_FINITE_OR_DUPLICATE_RESULT")
            if plan.value_type == MetricValueType.INTEGER and (
                not numeric.is_integer() or abs(numeric) > 2**53 - 1
            ):
                raise ConnectorValidationError("INTEGER_RESULT_NOT_EXACTLY_REPRESENTABLE")
            snapshot = row.get("_snapshot")
            if not isinstance(snapshot, datetime) or snapshot.tzinfo is None or snapshot > datetime.now(UTC):
                raise SourceNotReadyError("Source update timestamps are missing or invalid.")
            snapshots.append(snapshot)
            groups[label][key] = {**dict(zip(plan.dimensions, key, strict=True)), "value": numeric}
        if not groups["current"] or (
            statement.comparison is not None and groups["current"].keys() != groups["comparison"].keys()
        ):
            raise SourceNotReadyError("Current and comparison periods require matching complete groups.")
        if len(groups["current"]) > plan.row_limit:
            raise ConnectorValidationError("RESULT_TRUNCATED")
        rows = merge_comparison_rows(
            current_rows=list(groups["current"].values()),
            comparison_rows=list(groups["comparison"].values()),
            dimensions=plan.dimensions,
        )
        return rows, max(snapshots)

    async def get_freshness(self) -> SourceFreshness:
        return SourceFreshness(
            status=SourceStatus.NOT_READY,
            known_delay="Freshness is evaluated within each authorized query; no unscoped scan is performed.",
        )

    async def cancel_query(self, execution_id: str) -> bool:
        with self._lock:
            active = self._active.get(execution_id)
        if active is None:
            return False
        job_id, cancelled = active
        cancelled.set()
        await asyncio.to_thread(self.transport.cancel, job_id)
        return True  # Cancellation requested; BigQuery may still charge for work already performed.
