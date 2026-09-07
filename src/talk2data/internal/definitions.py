"""Definition governance bound to verified internal identities, with separate author/reviewer grants."""

from typing import Any, Literal

from fastapi import APIRouter, Response

from talk2data.domain.governance import DefinitionDraft, DefinitionEdit, DraftAction
from talk2data.internal.routes import Identity, Runtime

router = APIRouter(prefix="/v1/internal/definitions", tags=["internal-business-definitions"])


@router.get("")
async def definitions(service: Runtime, access: Identity) -> dict[str, Any]:
    return service.definitions[access.tenant_id].view(access)


@router.post("/drafts", status_code=201)
async def draft(payload: DefinitionEdit, service: Runtime, access: Identity) -> DefinitionDraft:
    return service.definitions[access.tenant_id].create_draft(access, payload)


@router.post("/drafts/{draft_id}/{action}")
async def transition(
    draft_id: str,
    action: Literal["submit", "approve", "reject", "publish"],
    payload: DraftAction,
    service: Runtime,
    access: Identity,
) -> DefinitionDraft:
    return service.definitions[access.tenant_id].transition(
        access, draft_id, action, payload.expected_revision, payload.note
    )


@router.post("/snapshots/{snapshot_id}/revoke", status_code=204)
async def revoke(snapshot_id: str, payload: DraftAction, service: Runtime, access: Identity) -> Response:
    service.definitions[access.tenant_id].revoke(access, snapshot_id, payload.expected_revision, payload.note)
    return Response(status_code=204)
