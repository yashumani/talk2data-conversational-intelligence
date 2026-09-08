"""Configuration for an optional, locally materialized analytical snapshot."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ParquetSnapshotSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    directory: Path
    maximum_rows: int = Field(default=5_000_000, ge=1, le=50_000_000)
    maximum_age_seconds: int = Field(default=86_400, ge=60, le=2_592_000)
    query_timeout_seconds: int = Field(default=30, ge=1, le=300)

    @field_validator("directory")
    @classmethod
    def absolute_private_directory(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("The Parquet snapshot directory must be an absolute private path.")
        return value
