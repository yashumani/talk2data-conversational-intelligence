"""Google SDK implementation used only by the operator materialization command."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from google.api_core.retry import Retry
from google.cloud import bigquery

from talk2data.core.bigquery_config import BigQuerySettings
from talk2data.domain.bigquery_mapping import BigQueryMapping
from talk2data.services.bigquery_sdk import GoogleBigQueryTransport
from talk2data.services.snapshot_materializer import SnapshotExtract


class GoogleSnapshotTransport:
    def __init__(self, settings: BigQuerySettings) -> None:
        self.settings = settings
        self.no_retry = Retry(predicate=lambda _: False)
        self.client = bigquery.Client(project=settings.billing_project, location=settings.location)

    def validate_view(self, mapping: BigQueryMapping) -> None:
        GoogleBigQueryTransport.validate_view(cast(Any, self), mapping)

    def extract(self, mapping: BigQueryMapping, maximum_rows: int) -> SnapshotExtract:
        columns = [
            mapping.tenant_column,
            mapping.business_unit_column,
            mapping.date_column,
            mapping.snapshot_column,
            mapping.metric_column,
            *mapping.dimensions.values(),
            *(column for metric in mapping.metrics for column in metric.measure_columns()),
        ]
        columns = list(dict.fromkeys(columns))
        selected = ", ".join(f"`{column}`" for column in columns)
        sql = (
            f"SELECT {selected} FROM `{mapping.view}` WHERE `{mapping.tenant_column}` = @tenant LIMIT @limit"
        )
        parameters = [
            bigquery.ScalarQueryParameter("tenant", "STRING", mapping.tenant_id),
            bigquery.ScalarQueryParameter("limit", "INT64", maximum_rows + 1),
        ]
        config = bigquery.QueryJobConfig(
            use_legacy_sql=False,
            use_query_cache=False,
            maximum_bytes_billed=self.settings.maximum_bytes_billed,
            query_parameters=parameters,
            labels={"application": "talk2data", "operation": "snapshot"},
        )
        dry_config = cast(
            bigquery.QueryJobConfig, bigquery.QueryJobConfig.from_api_repr(config.to_api_repr())
        )
        dry_config.dry_run = True
        dry = self.client.query(
            sql,
            job_config=dry_config,
            location=self.settings.location,
            retry=self.no_retry,
            job_retry=None,
            timeout=self.settings.api_timeout_seconds,
        )
        references = {
            f"{table.project}.{table.dataset_id}.{table.table_id}" for table in dry.referenced_tables or []
        }
        if (
            dry.statement_type != "SELECT"
            or dry.location != self.settings.location
            or not references
            or references - mapping.allowed_references
            or dry.total_bytes_processed is None
            or dry.total_bytes_processed > self.settings.maximum_bytes_billed
        ):
            raise ValueError("The materialization dry run did not satisfy the approved source contract.")
        job = self.client.query(
            sql,
            job_config=config,
            location=self.settings.location,
            retry=self.no_retry,
            job_retry=None,
            timeout=self.settings.api_timeout_seconds,
        )
        iterator = job.result(timeout=self.settings.query_timeout_seconds, retry=None, job_retry=None)
        rows = [dict(row) for row in iterator]
        if job.state != "DONE" or job.error_result or job.statement_type != "SELECT":
            raise ValueError("The materialization query did not complete as a read-only SELECT.")
        return SnapshotExtract(
            job_id=job.job_id,
            rows=rows,
            processed_bytes=job.total_bytes_processed,
            billed_bytes=job.total_bytes_billed,
        )

    def close(self) -> None:
        cast(Callable[[], None], self.client.close)()
