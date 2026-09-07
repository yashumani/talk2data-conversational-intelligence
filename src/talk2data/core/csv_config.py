from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CsvDemoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="T2D_CSV_DEMO_", env_file=".env", extra="ignore")

    enabled: bool = False
    maximum_bytes: int = Field(default=2_000_000, ge=1, le=5_000_000)
    maximum_rows: int = Field(default=20_000, ge=1, le=50_000)
    maximum_sessions: int = Field(default=16, ge=1, le=64)
    session_ttl_seconds: int = Field(default=1800, ge=1, le=3600)
