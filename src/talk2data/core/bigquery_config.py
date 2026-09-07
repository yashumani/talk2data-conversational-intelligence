"""BigQuery runtime limits; never loaded by the public demonstration bootstrap."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError("Expected a simple, explicitly approved identifier.")
    return value


def qualified_object(value: str) -> str:
    parts = value.split(".")
    if len(parts) != 3 or not PROJECT.fullmatch(parts[0]):
        raise ValueError("Expected an exact project.dataset.object reference.")
    identifier(parts[1])
    identifier(parts[2])
    return value


class BigQuerySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    billing_project: str
    location: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    maximum_bytes_billed: int = Field(gt=0, le=1_000_000_000_000)
    maximum_rows: int = Field(default=100, ge=1, le=1_000)
    query_timeout_seconds: int = Field(default=60, ge=1, le=300)
    api_timeout_seconds: int = Field(default=10, ge=1, le=30)

    @field_validator("billing_project")
    @classmethod
    def validate_project(cls, value: str) -> str:
        if not PROJECT.fullmatch(value):
            raise ValueError("Invalid billing project identifier.")
        return value
