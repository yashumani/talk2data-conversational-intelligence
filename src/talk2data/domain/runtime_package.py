from __future__ import annotations

import re
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from talk2data.domain.models import AccessContext, TenantDomainPack
from talk2data.domain.physical_mapping import TenantPhysicalMappingPack

_PROJECT_SLUG = re.compile(r"^[a-z][a-z0-9-]{2,62}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$")


class RuntimePackageModelProvider(StrEnum):
    OLLAMA = "OLLAMA"


class RuntimePackageModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: RuntimePackageModelProvider = RuntimePackageModelProvider.OLLAMA
    model_id: str = "qwen3:0.6b"
    timeout_seconds: int = Field(default=180, ge=10, le=1_800)

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        normalized = value.strip()
        if _MODEL_ID.fullmatch(normalized) is None:
            raise ValueError("model_id contains unsupported characters")
        return normalized


class RuntimePackageRequest(BaseModel):
    """Admin-authenticated request to generate an installable Talk2Data package."""

    model_config = ConfigDict(extra="forbid")

    project_name: str = Field(min_length=3, max_length=120)
    project_slug: str = Field(min_length=3, max_length=63)
    access_context: AccessContext
    domain_pack: TenantDomainPack
    physical_mapping_pack: TenantPhysicalMappingPack
    model: RuntimePackageModelConfig = Field(default_factory=RuntimePackageModelConfig)
    api_port: int = Field(default=8000, ge=1024, le=65_535)

    @field_validator("project_name")
    @classmethod
    def normalize_project_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("project_slug")
    @classmethod
    def validate_project_slug(cls, value: str) -> str:
        normalized = value.strip().lower()
        if _PROJECT_SLUG.fullmatch(normalized) is None:
            raise ValueError(
                "project_slug must start with a letter and contain only lowercase letters, "
                "numbers, and hyphens"
            )
        return normalized

    @model_validator(mode="after")
    def validate_tenant_alignment(self) -> Self:
        tenant_ids = {
            self.access_context.tenant_id,
            self.domain_pack.tenant_id,
            self.physical_mapping_pack.tenant_id,
        }
        if len(tenant_ids) != 1:
            raise ValueError("access, Domain Pack, and physical mapping tenant IDs must match")
        if self.domain_pack.status != "APPROVED":
            raise ValueError("the Domain Pack must be approved")
        if self.physical_mapping_pack.status != "APPROVED":
            raise ValueError("the physical mapping pack must be approved")
        return self


class RuntimePackageFile(BaseModel):
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)


class RuntimePackagePreview(BaseModel):
    package_id: str
    project_slug: str
    runtime_image: str
    files: list[RuntimePackageFile]
    warnings: list[str] = Field(default_factory=list)
