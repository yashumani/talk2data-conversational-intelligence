from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from talk2data.api.dependencies import get_semantic_registry
from talk2data.domain.domain_pack import DomainPackNotFoundError
from talk2data.domain.models import MetricResolutionRequest, MetricResolutionResponse
from talk2data.services.semantic import (
    MetricNotFoundError,
    SemanticAccessDeniedError,
    SemanticRegistry,
)

router = APIRouter(prefix="/v1/semantics", tags=["semantics"])


@router.post(
    "/metrics/resolve",
    response_model=MetricResolutionResponse,
    summary="Resolve an authorized versioned metric definition",
)
async def resolve_metric(
    request: MetricResolutionRequest,
    semantics: Annotated[SemanticRegistry, Depends(get_semantic_registry)],
) -> MetricResolutionResponse:
    try:
        return semantics.resolve_metric_response(request.access_context, request.metric_id)
    except (DomainPackNotFoundError, MetricNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SemanticAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Metric definition access denied.",
        ) from exc
