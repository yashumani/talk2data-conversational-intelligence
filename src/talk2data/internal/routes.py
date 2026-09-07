"""Internal API contracts intentionally exclude caller-supplied authority and connector settings."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from talk2data.domain.chat import DemoChatResponse
from talk2data.domain.models import AccessContext
from talk2data.internal.runtime import InternalQueryBusy, InternalQueryRuntime
from talk2data.services.identity import IdentityVerifier
from talk2data.services.policy import ASK_ACTION, READ_DATA_ACTION
from talk2data.services.semantic import SemanticAccessDeniedError

router = APIRouter(prefix="/v1/internal", tags=["internal"])


class InternalQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID = Field(default_factory=uuid4)
    question: str = Field(min_length=1, max_length=2000)
    as_of: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class InternalAnswer(BaseModel):
    request_id: UUID
    result: DemoChatResponse


def identity(request: Request) -> AccessContext:
    return cast(AccessContext, request.state.identity)


def runtime(request: Request) -> InternalQueryRuntime:
    return cast(InternalQueryRuntime, request.app.state.runtime)


Identity = Annotated[AccessContext, Depends(identity)]
Runtime = Annotated[InternalQueryRuntime, Depends(runtime)]


@router.get("/me")
async def me(access: Identity) -> dict[str, Any]:
    return {
        "tenant_id": access.tenant_id,
        "user_id": access.user_id,
        "regions": sorted(access.regions),
        "business_units": sorted(access.business_units),
    }


@router.get("/metrics")
async def metrics(service: Runtime, access: Identity) -> list[dict[str, Any]]:
    if READ_DATA_ACTION not in access.permitted_actions:
        raise HTTPException(403, "Data access is not authorized.")
    result = []
    for definition in service.domains.get(access.tenant_id).metrics:
        try:
            _, allowed = service.semantics.resolve_metric(access, definition.id)
        except SemanticAccessDeniedError:
            continue
        result.append(allowed.model_dump(mode="json"))
    return result


@router.post("/chat", response_model=InternalAnswer)
async def chat(
    payload: InternalQuestion, request: Request, service: Runtime, access: Identity
) -> InternalAnswer:
    if not {ASK_ACTION, READ_DATA_ACTION} <= access.permitted_actions:
        raise HTTPException(403, "Question and data access must both be authorized.")
    try:
        answer = await service.answer(
            request_id=payload.request_id, question=payload.question, as_of=payload.as_of, access=access
        )
    except InternalQueryBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except asyncio.CancelledError as exc:
        raise HTTPException(409, "Query cancellation was requested; no answer was released.") from exc
    except TimeoutError as exc:
        raise HTTPException(504, "Query deadline exceeded; cancellation was requested.") from exc
    verifier = cast(IdentityVerifier, request.app.state.verifier)
    current_access = await verifier.verify(cast(str, request.state.identity_token))
    if current_access != access:
        raise HTTPException(403, "Authorization changed during execution; no answer was released.")
    return InternalAnswer(request_id=payload.request_id, result=answer)


@router.post("/queries/{request_id}/cancel", status_code=202)
async def cancel(request_id: UUID, service: Runtime, access: Identity) -> dict[str, str]:
    if not service.cancel(request_id, access):
        raise HTTPException(404, "No active request was found for this identity.")
    return {"status": "cancellation_requested"}
