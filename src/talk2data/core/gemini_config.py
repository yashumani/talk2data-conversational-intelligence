"""Gemini Developer API settings; no ADC, BigQuery or browser-key configuration."""

from typing import Literal, Self

from pydantic import Field, model_validator

from talk2data.core.language_config import LanguageConfiguration


class GeminiConfiguration(LanguageConfiguration):
    provider: Literal["gemini"] = "gemini"
    model: str | None = Field(default=None, pattern=r"^gemini-[a-z0-9][a-z0-9.-]{2,99}$")
    secret_ref: str = Field(default="env://T2D_GEMINI_API_KEY", pattern=r"^env://[A-Z][A-Z0-9_]{1,100}$")
    allow_preview: bool = False
    data_policy: Literal["synthetic_demo", "approved_enterprise"] = "synthetic_demo"
    maximum_output_tokens: int = Field(default=2048, ge=128, le=4096)
    thinking_level: Literal["minimal", "low", "medium", "high"] | None = "minimal"
    maximum_concurrent_requests: int = Field(default=1, ge=1, le=8)

    @model_validator(mode="after")
    def gemini_contract(self) -> Self:
        if self.enabled and self.model and "preview" in self.model and not self.allow_preview:
            raise ValueError("Gemini preview models require explicit preview opt-in.")
        if (
            self.enabled
            and self.data_policy == "synthetic_demo"
            and (
                self.allowed_tenants != {"demo-telecom"} or self.allowed_metric_ids != {"MOBILE_ACTIVATIONS"}
            )
        ):
            raise ValueError(
                "Gemini synthetic demo scope is limited to the packaged Mobile Activations catalog."
            )
        return self
