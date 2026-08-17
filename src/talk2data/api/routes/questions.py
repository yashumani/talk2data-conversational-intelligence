from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from talk2data.api.dependencies import (
    get_admissibility_engine,
    get_domain_registry,
    get_session_store,
)
from talk2data.domain.domain_pack import DomainPackNotFoundError, DomainPackRegistry
from talk2data.domain.models import QuestionDecisionEnvelope, QuestionRequest
from talk2data.services.admissibility import QuestionAdmissibilityEngine
from talk2data.services.interpreter import InterpretationError
from talk2data.services.session_store import (
    SessionAccessDeniedError,
    SessionNotFoundError,
    SQLiteSessionStore,
)

router = APIRouter(prefix="/v1/questions", tags=["questions"])


@router.post(
    "/evaluate",
    response_model=QuestionDecisionEnvelope,
    summary="Evaluate whether a business question is admissible",
)
async def evaluate_question(
    request: QuestionRequest,
    registry: Annotated[DomainPackRegistry, Depends(get_domain_registry)],
    engine: Annotated[QuestionAdmissibilityEngine, Depends(get_admissibility_engine)],
    sessions: Annotated[SQLiteSessionStore, Depends(get_session_store)],
) -> QuestionDecisionEnvelope:
    try:
        pack = registry.get(request.access_context.tenant_id)
    except DomainPackNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if request.session_id is None:
        session_id = await sessions.create_session(request.access_context)
    else:
        session_id = request.session_id
        try:
            await sessions.ensure_access(session_id, request.access_context)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except SessionAccessDeniedError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session access denied.",
            ) from exc

    try:
        decision = await engine.evaluate(request, pack)
    except InterpretationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The required local Ollama interpretation service is unavailable.",
        ) from exc

    await sessions.record_evaluation(
        session_id=session_id,
        question=request.question,
        decision=decision,
    )
    return QuestionDecisionEnvelope(session_id=session_id, decision=decision)
