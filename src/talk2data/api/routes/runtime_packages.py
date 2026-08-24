from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from talk2data.domain.runtime_package import RuntimePackagePreview, RuntimePackageRequest
from talk2data.services.runtime_package import (
    RuntimePackageArtifact,
    RuntimePackageBuilder,
    RuntimePackageValidationError,
)

router = APIRouter(prefix="/v1/runtime-packages", tags=["runtime-packages"])
_builder = RuntimePackageBuilder()


@router.post(
    "/preview",
    response_model=RuntimePackagePreview,
    summary="Validate and preview an installable Talk2Data tenant package",
)
async def preview_runtime_package(request: RuntimePackageRequest) -> RuntimePackagePreview:
    return _build(request).preview


@router.post(
    "/download",
    response_class=Response,
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "Deterministic Talk2Data tenant runtime package.",
        }
    },
    summary="Download an installable Talk2Data tenant package",
)
async def download_runtime_package(request: RuntimePackageRequest) -> Response:
    artifact = _build(request)
    return Response(
        content=artifact.archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Talk2Data-Package-Id": artifact.preview.package_id,
        },
    )


def _build(request: RuntimePackageRequest) -> RuntimePackageArtifact:
    try:
        return _builder.build(request)
    except RuntimePackageValidationError as exc:
        status_code = (
            status.HTTP_403_FORBIDDEN
            if "administrator access" in str(exc).lower()
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
