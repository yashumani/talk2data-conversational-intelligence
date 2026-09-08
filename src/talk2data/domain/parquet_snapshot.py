"""Signed-off metadata for a locally materialized BigQuery snapshot."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ParquetSnapshotManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    connector_id: str
    mapping_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_view: str
    source_snapshot: datetime
    materialized_at: datetime
    coverage_start: datetime
    coverage_end: datetime
    row_count: int = Field(ge=1)
    parquet_file: str
    parquet_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_job_id: str
    processed_bytes: int | None = Field(default=None, ge=0)
    billed_bytes: int | None = Field(default=None, ge=0)

    @field_validator("source_snapshot", "materialized_at", "coverage_start", "coverage_end")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Snapshot timestamps must include a timezone.")
        return value

    @field_validator("parquet_file")
    @classmethod
    def local_filename_only(cls, value: str) -> str:
        if Path(value).name != value or value in {"", ".", ".."} or not value.endswith(".parquet"):
            raise ValueError("The manifest must reference one local Parquet filename.")
        return value

    @classmethod
    def filename(cls, mapping_hash: str) -> str:
        return f"{mapping_hash}.manifest.json"
