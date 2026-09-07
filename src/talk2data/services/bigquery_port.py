"""Small synchronous port implemented by the Google SDK and hermetic contract-test doubles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Event
from typing import Any, Protocol

from talk2data.domain.bigquery_mapping import BigQueryMapping
from talk2data.services.bigquery_sql import BigQueryStatement


@dataclass(frozen=True)
class DryRun:
    estimated_bytes: int | None
    location: str | None
    statement_type: str | None
    references: frozenset[str]


@dataclass(frozen=True)
class CloudResult:
    job_id: str
    location: str
    billing_project: str
    rows: list[dict[str, Any]]
    total_rows: int
    processed_bytes: int | None
    billed_bytes: int | None
    cache_hit: bool
    started_at: datetime | None
    ended_at: datetime | None


class BigQueryTransport(Protocol):
    def validate_view(self, mapping: BigQueryMapping) -> None: ...
    def dry_run(self, statement: BigQueryStatement) -> DryRun: ...
    def execute(self, statement: BigQueryStatement, job_id: str, cancelled: Event) -> CloudResult: ...
    def cancel(self, job_id: str) -> bool: ...
    def close(self) -> None: ...
