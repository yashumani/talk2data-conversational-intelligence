"""Versioned business-definition lifecycle; physical calculations are separate contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from talk2data.domain.models import BusinessEntity, MetricDefinition, TenantDomainPack

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
SnapshotId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


def pack_hash(pack: TenantDomainPack) -> str:
    return hashlib.sha256(
        json.dumps(pack.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class DefinitionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_snapshot_id: SnapshotId
    kind: Literal["METRIC", "DIMENSION"]
    definition_id: Name
    name: Name
    definition: Text
    owner: Name
    aliases: list[Name] = Field(default_factory=list, max_length=20)
    reason: Text
    effective_from: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("aliases")
    @classmethod
    def unique_aliases(cls, value: list[str]) -> list[str]:
        if len({alias.casefold() for alias in value}) != len(value):
            raise ValueError("Aliases must be unique.")
        return value


class DraftStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"


class DefinitionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: str = Field(default_factory=lambda: str(uuid4()))
    revision: int = 1
    status: DraftStatus = DraftStatus.DRAFT
    edit: DefinitionEdit
    author: str
    reviewer: str | None = None
    review_note: str | None = None
    submission_note: str | None = None
    publication_note: str | None = None
    created_at: AwareDatetime
    published_snapshot_id: str | None = None


class DefinitionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: SnapshotId
    sequence: int
    pack: TenantDomainPack
    published_at: AwareDatetime
    published_by: str

    @field_validator("pack")
    @classmethod
    def approved_pack(cls, value: TenantDomainPack) -> TenantDomainPack:
        if value.status != "APPROVED" or value.effective_from.tzinfo is None:
            raise ValueError("Snapshots require an approved, timezone-aware definition pack.")
        return value


class DefinitionEvent(BaseModel):
    sequence: int
    kind: Literal["PUBLISHED", "REVOKED"]
    snapshot_id: str
    occurred_at: AwareDatetime
    effective_from: AwareDatetime
    actor: str
    reason: str


class GovernanceState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    revision: int = 1
    snapshots: list[DefinitionSnapshot]
    drafts: list[DefinitionDraft] = Field(default_factory=list)
    events: list[DefinitionEvent] = Field(default_factory=list)
    revoked: set[str] = Field(default_factory=set)


class DraftAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    note: Text


class SemanticCitation(BaseModel):
    snapshot_id: str
    snapshot_hash: str
    publication_sequence: int
    effective_from: AwareDatetime
    metric: MetricDefinition
    dimensions: list[BusinessEntity]
