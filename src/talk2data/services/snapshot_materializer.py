"""Read-only BigQuery extraction into an atomic, hash-pinned Parquet snapshot."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import duckdb

from talk2data.core.parquet_config import ParquetSnapshotSettings
from talk2data.domain.bigquery_mapping import BigQueryMapping
from talk2data.domain.parquet_snapshot import ParquetSnapshotManifest


@dataclass(frozen=True)
class SnapshotExtract:
    job_id: str
    rows: Iterable[dict[str, Any]]
    processed_bytes: int | None
    billed_bytes: int | None


class SnapshotTransport(Protocol):
    def validate_view(self, mapping: BigQueryMapping) -> None: ...
    def extract(self, mapping: BigQueryMapping, maximum_rows: int) -> SnapshotExtract: ...
    def close(self) -> None: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SnapshotMaterializer:
    def __init__(self, settings: ParquetSnapshotSettings, transport: SnapshotTransport) -> None:
        self.settings, self.transport = settings, transport

    def materialize(self, mapping: BigQueryMapping) -> ParquetSnapshotManifest:
        self.transport.validate_view(mapping)
        extract = self.transport.extract(mapping, self.settings.maximum_rows)
        required = self._columns(mapping)
        root = self.settings.directory
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        mapping_hash = mapping.fingerprint()
        parquet_name = f"{mapping_hash}.parquet"
        final_path = root / parquet_name
        temporary_path = root / f".{mapping_hash}.{uuid4().hex}.tmp.parquet"
        payload = root / f".{mapping_hash}.{uuid4().hex}.tmp.jsonl"
        count = 0
        first_date: date | None = None
        last_date: date | None = None
        source_snapshot: datetime | None = None
        try:
            with payload.open("x", encoding="utf-8") as output:
                for row in extract.rows:
                    count += 1
                    if count > self.settings.maximum_rows:
                        raise ValueError("The extraction exceeds the approved row limit.")
                    if set(row) != set(required):
                        raise ValueError("Extracted rows do not match the approved canonical schema.")
                    fact_date = row[mapping.date_column]
                    snapshot = row[mapping.snapshot_column]
                    if (
                        not isinstance(fact_date, date)
                        or not isinstance(snapshot, datetime)
                        or snapshot.tzinfo is None
                    ):
                        raise ValueError("The extraction has invalid date or snapshot values.")
                    first_date = fact_date if first_date is None else min(first_date, fact_date)
                    last_date = fact_date if last_date is None else max(last_date, fact_date)
                    source_snapshot = snapshot if source_snapshot is None else max(source_snapshot, snapshot)
                    output.write(json.dumps(row, default=str, allow_nan=False, separators=(",", ":")) + "\n")
            if count == 0 or first_date is None or last_date is None or source_snapshot is None:
                raise ValueError("The extraction is empty.")
            self._write_parquet(temporary_path, payload, required)
        finally:
            payload.unlink(missing_ok=True)
        os.chmod(temporary_path, 0o600)
        digest = _sha256(temporary_path)
        observed = datetime.now(UTC)
        manifest = ParquetSnapshotManifest(
            tenant_id=mapping.tenant_id,
            connector_id=mapping.connector_id,
            mapping_hash=mapping_hash,
            source_view=mapping.view,
            source_snapshot=source_snapshot,
            materialized_at=observed,
            coverage_start=datetime.combine(first_date, datetime.min.time(), UTC),
            coverage_end=datetime.combine(last_date, datetime.max.time(), UTC),
            row_count=count,
            parquet_file=parquet_name,
            parquet_sha256=digest,
            source_job_id=extract.job_id,
            processed_bytes=extract.processed_bytes,
            billed_bytes=extract.billed_bytes,
        )
        manifest_path = root / ParquetSnapshotManifest.filename(mapping_hash)
        temporary_manifest = root / f".{mapping_hash}.{uuid4().hex}.tmp.json"
        try:
            temporary_path.replace(final_path)
            temporary_manifest.write_text(manifest.model_dump_json(indent=2) + "\n")
            os.chmod(temporary_manifest, 0o600)
            temporary_manifest.replace(manifest_path)
        finally:
            temporary_path.unlink(missing_ok=True)
            temporary_manifest.unlink(missing_ok=True)
        return manifest

    @staticmethod
    def _columns(mapping: BigQueryMapping) -> list[str]:
        columns = [
            mapping.tenant_column,
            mapping.business_unit_column,
            mapping.date_column,
            mapping.snapshot_column,
            mapping.metric_column,
            *mapping.dimensions.values(),
        ]
        columns.extend(column for metric in mapping.metrics for column in metric.measure_columns())
        return list(dict.fromkeys(columns))

    @staticmethod
    def _write_parquet(path: Path, payload: Path, columns: list[str]) -> None:
        connection = duckdb.connect(database=":memory:", read_only=False)
        try:
            connection.execute("CREATE TABLE snapshot AS SELECT * FROM read_json_auto(?)", [str(payload)])
            projected = ", ".join('"' + column.replace('"', '""') + '"' for column in columns)
            destination = str(path).replace("'", "''")
            connection.execute(
                f"COPY (SELECT {projected} FROM snapshot) TO '{destination}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        finally:
            connection.close()
