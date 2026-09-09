"""Opt-in language-provider configuration, independent of every data connection."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from talk2data.domain.models import ClassificationLevel


class AgentLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    deadline_seconds: float = Field(default=90, ge=1, le=180)
    maximum_steps: int = Field(default=6, ge=1, le=6)
    maximum_model_calls: int = Field(default=1, ge=1, le=2)
    maximum_total_tokens: int = Field(default=12000, ge=512, le=40000)


class LanguageConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = False
    provider: Literal["claude", "gemini"]
    model: str | None = None
    secret_ref: str = Field(pattern=r"^env://[A-Z][A-Z0-9_]{1,100}$")
    egress_approved: bool = False
    allowed_tenants: set[str] = Field(default_factory=set, max_length=64)
    allowed_metric_ids: set[str] = Field(default_factory=set, max_length=100)
    maximum_classification: ClassificationLevel = ClassificationLevel.INTERNAL
    maximum_input_tokens: int = Field(default=8000, ge=128, le=16000)
    maximum_output_tokens: int = Field(default=512, ge=128, le=2048)
    maximum_prompt_bytes: int = Field(default=40000, ge=512, le=80000)
    request_timeout_seconds: float = Field(default=25, ge=1, le=60)
    maximum_concurrent_requests: int = Field(default=4, ge=1, le=8)
    limits: AgentLimits = Field(default_factory=AgentLimits)

    @model_validator(mode="after")
    def activation_contract(self) -> Self:
        if self.enabled and (
            not self.model
            or not self.egress_approved
            or not self.allowed_tenants
            or not self.allowed_metric_ids
        ):
            raise ValueError(
                f"{self.provider.title()} activation requires an explicit model, "
                "approved egress, tenants and metrics."
            )
        if self.maximum_output_tokens > self.limits.maximum_total_tokens:
            raise ValueError("The output cap exceeds the run token budget.")
        return self

    @classmethod
    def load(cls, path: Path) -> Self:
        if not path.is_absolute():
            raise ValueError("Language configuration requires an absolute private file path.")
        return cls.model_validate_json(path.read_bytes())


class CsvLanguageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="T2D_CSV_LANGUAGE_", extra="forbid")
    config_file: Path | None = None
