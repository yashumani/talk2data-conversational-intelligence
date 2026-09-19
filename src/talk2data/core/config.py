from __future__ import annotations

import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DataBackend(StrEnum):
    DEMO_SQLITE = "demo_sqlite"
    POSTGRESQL = "postgresql"


class RuntimeProfile(StrEnum):
    DISABLED = "disabled"
    TRUSTED_LOCAL = "trusted_local"
    PUBLIC_SYNTHETIC = "public_synthetic"


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
    runtime_profile: RuntimeProfile = RuntimeProfile.DISABLED
    database_path: Path = Path(".talk2data/talk2data.db")
    web_directory: Path | None = None
    default_tenant_id: str = "demo-telecom"
    domain_pack_directory: Path | None = None
    physical_mapping_directory: Path | None = None
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "https://yashumani.github.io",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ]
    )

    data_backend: DataBackend = DataBackend.DEMO_SQLITE
    postgres_dsn: SecretStr | None = None
    postgres_schema: str | None = None
    postgres_table: str | None = None
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

    public_maximum_request_bytes: int = Field(default=32_768, ge=1, le=1_048_576)
    public_maximum_response_bytes: int = Field(default=262_144, ge=1, le=4_194_304)
    public_response_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    public_requests_per_minute: int = Field(default=60, ge=1, le=600)
    public_maximum_in_flight: int = Field(default=4, ge=1, le=32)

    @field_validator("data_backend", mode="before")
    @classmethod
    def normalize_data_backend(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("postgres_schema", "postgres_table")
    @classmethod
    def validate_postgres_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
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

    @field_validator(
        "database_path",
        "domain_pack_directory",
        "physical_mapping_directory",
        mode="after",
    )
    @classmethod
    def normalize_paths(cls, value: Path | None) -> Path | None:
        return None if value is None else value.expanduser()

    @model_validator(mode="after")
    def validate_public_profile(self) -> Settings:
        if self.runtime_profile != RuntimeProfile.PUBLIC_SYNTHETIC:
            return self
        if not self.cors_allowed_origins:
            raise ValueError("public_synthetic requires at least one exact allowed browser origin")
        for origin in self.cors_allowed_origins:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
                raise ValueError("public_synthetic origins must be exact http(s) origins without paths")
            if "*" in origin or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError(
                    "public_synthetic origins cannot contain wildcards, credentials, queries, or fragments"
                )
        if self.data_backend != DataBackend.DEMO_SQLITE or self.postgres_dsn is not None:
            raise ValueError("public_synthetic permits only the packaged synthetic SQLite connector")
        if self.ollama_enabled or self.ollama_required or self.hermes_enabled or self.hermes_api_key:
            raise ValueError("public_synthetic cannot enable or configure external model providers")
        if self.default_tenant_id != "demo-telecom":
            raise ValueError("public_synthetic tenant must remain demo-telecom")
        if self.domain_pack_directory is not None or self.physical_mapping_directory is not None:
            raise ValueError("public_synthetic must use packaged synthetic domain and mapping authority")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
