"""Demonstration review uses only its server-owned session; it cannot publish internal definitions."""

from typing import Literal

from fastapi import APIRouter, Response

from talk2data.api.routes.csv_demo import Token, Workspace
from talk2data.domain.chat import DemoChatResponse
from talk2data.domain.governance import DefinitionDraft, DefinitionEdit, DraftAction

router = APIRouter(prefix="/v1/demo/csv", tags=["demo-business-definitions"])


@router.post("/definitions/drafts", status_code=201)
async def draft(payload: DefinitionEdit, service: Workspace, token: Token) -> DefinitionDraft:
    async with service.lease(token) as item:
        return item.definitions.create_draft(service._access(item), payload)


@router.post("/definitions/drafts/{draft_id}/{action}")
async def transition(
    draft_id: str,
    action: Literal["submit", "approve", "reject", "publish"],
    payload: DraftAction,
    service: Workspace,
    token: Token,
) -> DefinitionDraft:
    async with service.lease(token) as item:
        return item.definitions.transition(
            service._access(item), draft_id, action, payload.expected_revision, payload.note
        )


@router.post("/definitions/snapshots/{snapshot_id}/revoke", status_code=204)
async def revoke(snapshot_id: str, payload: DraftAction, service: Workspace, token: Token) -> Response:
    async with service.lease(token) as item:
        item.definitions.revoke(service._access(item), snapshot_id, payload.expected_revision, payload.note)
    return Response(status_code=204)


@router.post("/history/{run_id}/rerun", response_model=DemoChatResponse)
async def rerun(run_id: str, service: Workspace, token: Token) -> DemoChatResponse:
    async with service.lease(token) as item:
        return await service.rerun(item, run_id)
