from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CsvDemoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="T2D_CSV_DEMO_", env_file=".env", extra="ignore")

    enabled: bool = False
    maximum_bytes: int = Field(default=2_000_000, ge=1, le=5_000_000)
    maximum_rows: int = Field(default=20_000, ge=1, le=50_000)
    maximum_sessions: int = Field(default=16, ge=1, le=64)
    maximum_language_questions: int = Field(default=8, ge=1, le=20)
    state_database_path: Path | None = None
    session_ttl_seconds: int = Field(default=1800, ge=1, le=3600)

    @field_validator("state_database_path")
    @classmethod
    def private_state_path(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("CSV state requires an absolute private database path.")
        return value
