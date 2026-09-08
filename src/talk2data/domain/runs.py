"""Durable orchestration contracts; authority and credentials are never client inputs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from talk2data.domain.agents import AgentRunReport
from talk2data.domain.chat import DemoChatResponse
from talk2data.domain.models import AccessContext

RunStatus = Literal[
    "QUEUED", "RUNNING", "CANCELLATION_REQUESTED", "COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"
]
TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"})


def now() -> datetime:
    return datetime.now(UTC)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def principal(profile: str, access: AccessContext) -> tuple[str, str]:
    owner = digest([profile, access.tenant_id, access.user_id])
    scope = access.model_dump(mode="json")
    for key, value in scope.items():
        if isinstance(value, list):
            scope[key] = sorted(value)
    return owner, digest(scope)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    conversation_id: UUID
    expected_revision: int = Field(ge=0)
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]
    as_of: AwareDatetime
    source_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    definition_snapshot_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class Conversation(BaseModel):
    conversation_id: UUID = Field(default_factory=uuid4)
    revision: int = 0
    title: str = "New conversation"
    latest_run_id: UUID | None = None
    created_at: datetime = Field(default_factory=now)


class RunSnapshot(BaseModel):
    run_id: UUID = Field(default_factory=uuid4)
    request: RunRequest
    source_binding: str
    status: RunStatus = "QUEUED"
    sequence: int = 0
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    progress: AgentRunReport | None = None
    result: DemoChatResponse | None = None
    error_code: str | None = None
    message: str = "Question accepted."


class RunEvent(BaseModel):
    run_id: UUID
    sequence: int
    type: str
    status: RunStatus
    created_at: datetime = Field(default_factory=now)
    progress: AgentRunReport | None = None


class RunError(RuntimeError):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code
