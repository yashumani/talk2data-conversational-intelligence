from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from talk2data.api.dependencies import (
    get_domain_registry,
    get_physical_mapping_registry,
)
from talk2data.domain.domain_pack import DomainPackNotFoundError, DomainPackRegistry
from talk2data.domain.physical_mapping import (
    PhysicalMappingAccessRequest,
    PhysicalMappingConnectorRequest,
    PhysicalMappingConnectorResponse,
    PhysicalMappingNotFoundError,
    PhysicalMappingPackResponse,
    PhysicalMappingRegistry,
)

router = APIRouter(prefix="/v1/physical-mappings", tags=["physical mappings"])


@router.post(
    "/list",
    response_model=PhysicalMappingPackResponse,
    summary="List the approved physical mappings for a tenant",
)
async def list_physical_mappings(
    request: PhysicalMappingAccessRequest,
    mappings: Annotated[
        PhysicalMappingRegistry,
        Depends(get_physical_mapping_registry),
    ],
    domains: Annotated[DomainPackRegistry, Depends(get_domain_registry)],
) -> PhysicalMappingPackResponse:
    _require_mapping_admin(request.access_context.roles)
    try:
        pack = mappings.get(request.access_context.tenant_id)
        domain_pack = domains.get(request.access_context.tenant_id)
    except (PhysicalMappingNotFoundError, DomainPackNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PhysicalMappingPackResponse(
        tenant_id=pack.tenant_id,
        version=pack.version,
        mapping_hash=pack.canonical_hash(),
        connectors=[connector.public_view() for connector in pack.connectors],
        validation_failures=mappings.validate_domain_pack(domain_pack),
    )


@router.post(
    "/connector",
    response_model=PhysicalMappingConnectorResponse,
    summary="Read one approved physical connector mapping",
)
async def get_physical_connector_mapping(
    request: PhysicalMappingConnectorRequest,
    mappings: Annotated[
        PhysicalMappingRegistry,
        Depends(get_physical_mapping_registry),
    ],
) -> PhysicalMappingConnectorResponse:
    _require_mapping_admin(request.access_context.roles)
    try:
        pack = mappings.get(request.access_context.tenant_id)
        connector = pack.connector(request.connector_id)
    except PhysicalMappingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PhysicalMappingConnectorResponse(
        tenant_id=pack.tenant_id,
        version=pack.version,
        mapping_hash=pack.connector_hash(request.connector_id),
        connector=connector.public_view(),
    )


def _require_mapping_admin(roles: set[str]) -> None:
    if "TALK2DATA_ADMIN" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Physical mapping administration access denied.",
        )
