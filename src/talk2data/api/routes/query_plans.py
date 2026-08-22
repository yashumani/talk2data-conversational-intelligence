from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from talk2data.api.dependencies import (
    get_admissibility_engine,
    get_domain_registry,
    get_query_compiler,
    get_session_store,
)
from talk2data.domain.domain_pack import DomainPackNotFoundError, DomainPackRegistry
from talk2data.domain.models import (
    QueryCompilationRequest,
    QueryCompilationResult,
    QuestionRequest,
)
from talk2data.services.admissibility import QuestionAdmissibilityEngine
from talk2data.services.interpreter import InterpretationError
from talk2data.services.query_compiler import BusinessQueryCompiler
from talk2data.services.session_store import (
    SessionAccessDeniedError,
    SessionNotFoundError,
    SQLiteSessionStore,
)

router = APIRouter(prefix="/v1/query-plans", tags=["query-plans"])


@router.post(
    "/compile",
    response_model=QueryCompilationResult,
    summary="Compile an admissible business question into deterministic Business Query IR",
)
async def compile_query_plan(
    request: QueryCompilationRequest,
    registry: Annotated[DomainPackRegistry, Depends(get_domain_registry)],
    engine: Annotated[QuestionAdmissibilityEngine, Depends(get_admissibility_engine)],
    compiler: Annotated[BusinessQueryCompiler, Depends(get_query_compiler)],
    sessions: Annotated[SQLiteSessionStore, Depends(get_session_store)],
) -> QueryCompilationResult:
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

    question_request = QuestionRequest.model_validate(request.model_dump(exclude={"as_of"}))
    try:
        decision = await engine.evaluate(question_request, pack)
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
    result = compiler.compile(
        request=request,
        decision=decision,
        session_id=session_id,
    )
    if result.query_ir is not None:
        await sessions.record_query_plan(session_id=session_id, query_ir=result.query_ir)
    return result
