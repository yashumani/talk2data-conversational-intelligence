"""Required private configuration for the internal application; no demo defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from talk2data.core.bigquery_config import BigQuerySettings
from talk2data.core.claude_config import ClaudeConfiguration
from talk2data.core.state_config import SharedStateSettings
from talk2data.operations.http import HttpOperations


class IdentitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str
    audience: str = Field(min_length=1, max_length=512)
    jwks_url: str
    algorithm: Literal["RS256", "ES256"] = "RS256"
    token_header: Literal["authorization", "x-goog-iap-jwt-assertion"] = "authorization"
    maximum_token_lifetime_seconds: int = Field(default=3600, ge=60, le=3600)
    leeway_seconds: int = Field(default=30, ge=0, le=30)
    key_cache_seconds: int = Field(default=60, ge=1, le=300)

    @field_validator("issuer", "jwks_url")
    @classmethod
    def trusted_https(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Identity URLs must be explicitly configured HTTPS endpoints without credentials."
            )
        return value

    @model_validator(mode="after")
    def signed_iap_contract(self) -> Self:
        if self.token_header == "x-goog-iap-jwt-assertion" and (
            self.algorithm != "ES256"
            or self.issuer != "https://cloud.google.com/iap"
            or self.jwks_url != "https://www.gstatic.com/iap/verify/public_key-jwk"
            or self.maximum_token_lifetime_seconds > 600 + 2 * self.leeway_seconds
        ):
            raise ValueError("Signed IAP requires Google's ES256 trust root and bounded IAP token lifetime.")
        return self


class InternalRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    identity: IdentitySettings
    bigquery: BigQuerySettings
    entitlements_path: Path
    domain_pack_directory: Path
    bigquery_catalog_path: Path
    maximum_active_queries: int = Field(default=8, ge=1, le=32)
    governance_database_path: Path | None = None
    state_database_path: Path | None = None
    claude: ClaudeConfiguration = Field(default_factory=ClaudeConfiguration)
    http_operations: HttpOperations = Field(default_factory=HttpOperations)
    shared_state: SharedStateSettings | None = None
    process_role: Literal["api", "worker"] = "api"
    web_directory: Path | None = None

    @model_validator(mode="after")
    def isolated_state(self) -> Self:
        if self.shared_state is not None and (
            self.state_database_path is not None or self.governance_database_path is not None
        ):
            raise ValueError("Shared state cannot be combined with reference SQLite paths.")
        if self.process_role == "worker" and (self.shared_state is None or self.web_directory is not None):
            raise ValueError("The worker requires shared state and cannot serve a workspace.")
        if self.web_directory is not None and (
            not self.web_directory.is_absolute() or self.identity.token_header != "x-goog-iap-jwt-assertion"
        ):
            raise ValueError("The internal browser workspace requires signed IAP and an absolute asset path.")
        return self

    @field_validator("governance_database_path", "state_database_path")
    @classmethod
    def private_definition_database(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("The definition database requires an absolute private path.")
        return value

    @field_validator("entitlements_path", "domain_pack_directory", "bigquery_catalog_path")
    @classmethod
    def absolute_private_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("Internal configuration paths must be absolute private mount paths.")
        return value

    @classmethod
    def load(cls, path: Path) -> InternalRuntimeConfig:
        return cls.model_validate_json(path.read_bytes())


class InternalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="T2D_INTERNAL_", extra="forbid")
    config_file: Path
