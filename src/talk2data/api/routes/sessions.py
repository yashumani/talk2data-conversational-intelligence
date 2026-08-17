from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from talk2data.api.dependencies import get_session_store
from talk2data.domain.models import SessionSnapshot
from talk2data.services.session_store import (
    SQLiteSessionStore,
    SessionAccessDeniedError,
    SessionNotFoundError,
)

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@router.get("/{session_id}", response_model=SessionSnapshot)
async def get_session(
    session_id: UUID,
    sessions: Annotated[SQLiteSessionStore, Depends(get_session_store)],
    tenant_id: Annotated[str, Header(alias="X-Tenant-ID")],
    user_id: Annotated[str, Header(alias="X-User-ID")],
) -> SessionSnapshot:
    try:
        return await sessions.get_session(
            session_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SessionAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session access denied.",
        ) from exc
