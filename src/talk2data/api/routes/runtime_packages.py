from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from talk2data.api.dependencies import get_domain_registry, get_physical_mapping_registry
from talk2data.domain.domain_pack import DomainPackNotFoundError, DomainPackRegistry
from talk2data.domain.physical_mapping import (
    PhysicalMappingNotFoundError,
    PhysicalMappingRegistry,
)
from talk2data.domain.runtime_package import (
    RuntimePackagePreview,
    RuntimePackageRequest,
    RuntimePackageTemplate,
    RuntimePackageTemplateRequest,
)
from talk2data.services.runtime_package import (
    RUNTIME_IMAGE,
    RuntimePackageArtifact,
    RuntimePackageBuilder,
    RuntimePackageValidationError,
)

router = APIRouter(prefix="/v1/runtime-packages", tags=["runtime-packages"])
_builder = RuntimePackageBuilder()


@router.post(
    "/template",
    response_model=RuntimePackageTemplate,
    summary="Retrieve the approved tenant packs used by the setup wizard",
)
async def runtime_package_template(
    request: RuntimePackageTemplateRequest,
    domains: Annotated[DomainPackRegistry, Depends(get_domain_registry)],
    mappings: Annotated[PhysicalMappingRegistry, Depends(get_physical_mapping_registry)],
) -> RuntimePackageTemplate:
    _require_admin(request.access_context.roles)
    tenant_id = request.access_context.tenant_id
    try:
        domain_pack = domains.get(tenant_id)
        mapping_pack = mappings.get(tenant_id)
    except (DomainPackNotFoundError, PhysicalMappingNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No approved runtime package template exists for this tenant.",
        ) from exc
    return RuntimePackageTemplate(
        domain_pack=domain_pack,
        physical_mapping_pack=mapping_pack,
        runtime_image=RUNTIME_IMAGE,
    )


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


def _require_admin(roles: set[str]) -> None:
    if "TALK2DATA_ADMIN" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Talk2Data administrator access is required to retrieve a runtime template.",
        )
