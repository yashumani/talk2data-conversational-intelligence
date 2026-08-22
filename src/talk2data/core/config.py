from __future__ import annotations

import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DataBackend(StrEnum):
    DEMO_SQLITE = "demo_sqlite"
    POSTGRESQL = "postgresql"


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="T2D_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Talk2Data Conversational Intelligence"
    environment: str = "development"
    log_level: str = "INFO"
    database_path: Path = Path(".talk2data/talk2data.db")
    default_tenant_id: str = "demo-telecom"
    domain_pack_directory: Path | None = None
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "https://yashumani.github.io",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ]
    )

    data_backend: DataBackend = DataBackend.DEMO_SQLITE
    postgres_dsn: SecretStr | None = None
    postgres_schema: str = "talk2data"
    postgres_table: str = "metric_facts"
    postgres_maximum_rows: int = Field(default=1_000, ge=1, le=10_000)
    postgres_query_timeout_seconds: int = Field(default=60, ge=1, le=1_800)
    postgres_connect_timeout_seconds: int = Field(default=10, ge=1, le=120)

    ollama_enabled: bool = True
    ollama_required: bool = False
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_timeout_seconds: float = Field(default=90.0, gt=0, le=1800)

    hermes_enabled: bool = False
    hermes_base_url: str = "http://127.0.0.1:8642"
    hermes_api_key: str | None = None
    hermes_timeout_seconds: float = Field(default=180.0, gt=0, le=3600)

    @field_validator("data_backend", mode="before")
    @classmethod
    def normalize_data_backend(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("postgres_schema", "postgres_table")
    @classmethod
    def validate_postgres_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if _IDENTIFIER.fullmatch(normalized) is None:
            raise ValueError("PostgreSQL schema and table must be simple identifiers")
        return normalized

    @field_validator("ollama_base_url", "hermes_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("cors_allowed_origins", mode="after")
    @classmethod
    def normalize_cors_origins(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            origin = value.strip().rstrip("/")
            if origin and origin not in normalized:
                normalized.append(origin)
        return normalized

    @field_validator("database_path", mode="after")
    @classmethod
    def normalize_database_path(cls, value: Path) -> Path:
        return value.expanduser()

    @model_validator(mode="after")
    def validate_data_backend(self) -> Self:
        if self.data_backend == DataBackend.POSTGRESQL and self.postgres_dsn is None:
            raise ValueError("T2D_POSTGRES_DSN is required when T2D_DATA_BACKEND=postgresql")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
