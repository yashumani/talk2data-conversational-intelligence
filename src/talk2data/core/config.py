from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    ollama_enabled: bool = True
    ollama_required: bool = False
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_timeout_seconds: float = Field(default=90.0, gt=0, le=1800)

    hermes_enabled: bool = False
    hermes_base_url: str = "http://127.0.0.1:8642"
    hermes_api_key: str | None = None
    hermes_timeout_seconds: float = Field(default=180.0, gt=0, le=3600)

    @field_validator("ollama_base_url", "hermes_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("database_path", mode="after")
    @classmethod
    def normalize_database_path(cls, value: Path) -> Path:
        return value.expanduser()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
