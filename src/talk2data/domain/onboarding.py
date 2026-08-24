from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from talk2data.domain.models import AccessContext
from talk2data.domain.physical_mapping import TenantPhysicalMappingPack

_PROJECT_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class RuntimePackageRequest(BaseModel):
    """Administrator request for a reproducible tenant runtime bundle."""

    model_config = ConfigDict(extra="forbid")

    access_context: AccessContext
    project_slug: str = "talk2data-tenant"
    display_name: str = Field(default="Talk2Data Tenant Runtime", min_length=1, max_length=120)
    ollama_model: str = "qwen3:0.6b"
    api_port: int = Field(default=8000, ge=1024, le=65535)
    selected_connector_ids: list[str] = Field(default_factory=list)
    physical_mapping_pack: TenantPhysicalMappingPack | None = None
    include_codespaces: bool = True

    @field_validator("project_slug")
    @classmethod
    def validate_project_slug(cls, value: str) -> str:
        normalized = value.strip().lower()
        if _PROJECT_SLUG.fullmatch(normalized) is None:
            raise ValueError("project_slug must use lowercase letters, numbers, and single hyphens")
        return normalized

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("display_name cannot be blank")
        return normalized

    @field_validator("ollama_model")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        normalized = value.strip()
        if _MODEL_NAME.fullmatch(normalized) is None:
            raise ValueError("ollama_model contains unsupported characters")
        return normalized

    @field_validator("selected_connector_ids", mode="after")
    @classmethod
    def normalize_connector_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("selected_connector_ids cannot contain duplicates")
        return sorted(normalized)


class RuntimePackageValidationResponse(BaseModel):
    valid: bool
    tenant_id: str
    project_slug: str
    connector_ids: list[str] = Field(default_factory=list)
    mapping_version: str | None = None
    mapping_hash: str | None = None
    runtime_image: str
    package_file_count: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RuntimePackageMetadata(BaseModel):
    filename: str
    sha256: str
    size_bytes: int
    tenant_id: str
    connector_ids: list[str]
    mapping_version: str
    mapping_hash: str
    files: list[str]
