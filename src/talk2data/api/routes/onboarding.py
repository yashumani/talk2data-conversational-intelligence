from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from talk2data.api.dependencies import get_runtime_package_builder
from talk2data.deployment.runtime_package import (
    RuntimePackageBuilder,
    RuntimePackageError,
)
from talk2data.domain.onboarding import (
    RuntimePackageRequest,
    RuntimePackageValidationResponse,
)

router = APIRouter(prefix="/v1/onboarding", tags=["data source onboarding"])


@router.post(
    "/validate",
    response_model=RuntimePackageValidationResponse,
    summary="Validate a tenant data-source runtime package request",
)
async def validate_runtime_package(
    request: RuntimePackageRequest,
    builder: Annotated[RuntimePackageBuilder, Depends(get_runtime_package_builder)],
) -> RuntimePackageValidationResponse:
    _require_admin(request)
    return builder.validate(request)


@router.post(
    "/package",
    response_class=Response,
    summary="Download a reproducible credential-free tenant runtime package",
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "A deterministic Talk2Data tenant runtime ZIP.",
        }
    },
)
async def download_runtime_package(
    request: RuntimePackageRequest,
    builder: Annotated[RuntimePackageBuilder, Depends(get_runtime_package_builder)],
) -> Response:
    _require_admin(request)
    try:
        artifact = builder.build(request)
    except RuntimePackageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return Response(
        content=artifact.content,
        media_type="application/zip",
        headers={
            "Content-Disposition": (f'attachment; filename="{artifact.metadata.filename}"'),
            "X-Talk2Data-Package-SHA256": artifact.metadata.sha256,
            "X-Talk2Data-Mapping-Version": artifact.metadata.mapping_version,
            "X-Talk2Data-Mapping-Hash": artifact.metadata.mapping_hash,
        },
    )


def _require_admin(request: RuntimePackageRequest) -> None:
    if "TALK2DATA_ADMIN" not in request.access_context.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Data source onboarding administration access denied.",
        )
