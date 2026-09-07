"""Google SDK boundary: ADC credentials, exact view metadata, bounded jobs and cancellation."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event
from typing import Any, cast

from google.api_core.exceptions import GoogleAPICallError
from google.api_core.retry import Retry
from google.auth.exceptions import GoogleAuthError
from google.cloud import bigquery

from talk2data.core.bigquery_config import BigQuerySettings
from talk2data.domain.bigquery_mapping import BigQueryMapping
from talk2data.services.bigquery_port import CloudResult, DryRun
from talk2data.services.bigquery_sql import BigQueryStatement


class GoogleBigQueryTransport:
    def __init__(self, settings: BigQuerySettings) -> None:
        self.settings = settings
        self.no_retry = Retry(predicate=lambda _: False)
        self.client = bigquery.Client(project=settings.billing_project, location=settings.location)

    def validate_view(self, mapping: BigQueryMapping) -> None:
        table = self.client.get_table(
            mapping.view, retry=self.no_retry, timeout=self.settings.api_timeout_seconds
        )
        if table.table_type not in {"VIEW", "MATERIALIZED_VIEW"} or table.location != self.settings.location:
            raise ValueError("The approved source must be a view in the configured location.")
        schema = {field.name: (field.field_type, field.mode) for field in table.schema}
        required = {
            mapping.tenant_column: {"STRING"},
            mapping.business_unit_column: {"STRING"},
            mapping.metric_column: {"STRING"},
            mapping.date_column: {"DATE"},
            mapping.snapshot_column: {"TIMESTAMP"},
            **{column: {"STRING"} for column in mapping.dimensions.values()},
        }
        for metric in mapping.metrics:
            for column in metric.measure_columns():
                required[column] = {"INTEGER", "INT64", "FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC"}
        if any(
            name not in schema or schema[name][0] not in kinds or schema[name][1] == "REPEATED"
            for name, kinds in required.items()
        ):
            raise ValueError("The approved view does not satisfy the canonical daily-fact schema.")

    def _config(self, statement: BigQueryStatement, *, dry_run: bool) -> Any:
        parameters: list[bigquery.ArrayQueryParameter | bigquery.ScalarQueryParameter] = []
        for parameter in statement.parameters:
            if isinstance(parameter.value, tuple):
                parameters.append(bigquery.ArrayQueryParameter(parameter.name, "STRING", parameter.value))
            else:
                parameters.append(
                    bigquery.ScalarQueryParameter(parameter.name, parameter.kind, parameter.value)
                )
        return bigquery.QueryJobConfig(
            dry_run=dry_run,
            use_legacy_sql=False,
            use_query_cache=False,
            maximum_bytes_billed=self.settings.maximum_bytes_billed,
            job_timeout_ms=self.settings.query_timeout_seconds * 1000,
            query_parameters=parameters,
            labels={"application": "talk2data", "scope": statement.scope_hash[:32]},
        )

    def dry_run(self, statement: BigQueryStatement) -> DryRun:
        job = self.client.query(
            statement.sql,
            job_config=self._config(statement, dry_run=True),
            location=self.settings.location,
            retry=self.no_retry,
            job_retry=None,
            timeout=self.settings.api_timeout_seconds,
        )
        references = frozenset(
            f"{table.project}.{table.dataset_id}.{table.table_id}" for table in job.referenced_tables or []
        )
        return DryRun(job.total_bytes_processed, job.location, job.statement_type, references)

    def execute(self, statement: BigQueryStatement, job_id: str, cancelled: Event) -> CloudResult:
        if cancelled.is_set():
            raise TimeoutError("Query cancelled before submission.")
        try:
            job = self.client.query(
                statement.sql,
                job_config=self._config(statement, dry_run=False),
                job_id=job_id,
                location=self.settings.location,
                retry=self.no_retry,
                job_retry=None,
                timeout=self.settings.api_timeout_seconds,
            )
            if cancelled.is_set():
                raise TimeoutError("Query cancellation requested during submission.")
            iterator = job.result(
                timeout=self.settings.query_timeout_seconds,
                retry=None,
                job_retry=None,
                max_results=statement.maximum_result_rows,
            )
            rows = [dict(row) for row in iterator]
            if cancelled.is_set():
                raise TimeoutError("Query cancelled before result release.")
            if job.state != "DONE" or job.error_result or job.statement_type != "SELECT":
                raise ValueError("Only a completed SELECT job can release results.")
            if iterator.total_rows is None:
                raise ValueError("BigQuery did not return the complete result count.")
            return CloudResult(
                job.job_id,
                job.location,
                job.project,
                rows,
                iterator.total_rows,
                job.total_bytes_processed,
                job.total_bytes_billed,
                bool(job.cache_hit),
                job.started,
                job.ended,
            )
        except (GoogleAPICallError, GoogleAuthError, OSError, ValueError):
            cancelled.set()
            self.cancel(job_id)
            raise

    def cancel(self, job_id: str) -> bool:
        try:
            return bool(
                self.client.cancel_job(
                    job_id,
                    project=self.settings.billing_project,
                    location=self.settings.location,
                    retry=self.no_retry,
                    timeout=self.settings.api_timeout_seconds,
                )
            )
        except (GoogleAPICallError, GoogleAuthError, OSError):
            return False

    def close(self) -> None:
        cast(Callable[[], None], self.client.close)()
