from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from talk2data.api.dependencies import get_connector_registry
from talk2data.connectors.base import DataConnector
from talk2data.connectors.registry import ConnectorRegistry, ConnectorRegistryError
from talk2data.domain.connectors import (
    ConnectorAccessRequest,
    ConnectorCatalogResponse,
    ConnectorFreshnessResponse,
    ConnectorHealthResponse,
    ConnectorListRequest,
    ConnectorListResponse,
)
from talk2data.domain.models import AccessContext
from talk2data.services.policy import READ_DATA_ACTION

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])


@router.post(
    "/list",
    response_model=ConnectorListResponse,
    summary="List authorized governed connector contracts",
)
async def list_connectors(
    request: ConnectorListRequest,
    registry: Annotated[ConnectorRegistry, Depends(get_connector_registry)],
) -> ConnectorListResponse:
    _require_data_access(request.access_context)
    return ConnectorListResponse(
        connectors=[connector.descriptor for connector in registry.connectors()]
    )


@router.post(
    "/catalog",
    response_model=ConnectorCatalogResponse,
    summary="Retrieve the authorized semantic catalog for a connector",
)
async def connector_catalog(
    request: ConnectorAccessRequest,
    registry: Annotated[ConnectorRegistry, Depends(get_connector_registry)],
) -> ConnectorCatalogResponse:
    _require_data_access(request.access_context)
    connector = _get_connector(registry, request.connector_id)
    items = await connector.discover_catalog(request.access_context)
    return ConnectorCatalogResponse(connector_id=request.connector_id, items=items)


@router.post(
    "/freshness",
    response_model=ConnectorFreshnessResponse,
    summary="Read the governed source coverage and freshness state",
)
async def connector_freshness(
    request: ConnectorAccessRequest,
    registry: Annotated[ConnectorRegistry, Depends(get_connector_registry)],
) -> ConnectorFreshnessResponse:
    _require_data_access(request.access_context)
    connector = _get_connector(registry, request.connector_id)
    freshness = await connector.get_freshness()
    return ConnectorFreshnessResponse(
        connector_id=request.connector_id,
        freshness=freshness,
    )


@router.post(
    "/test",
    response_model=ConnectorHealthResponse,
    summary="Test a connector without exposing credentials or source metadata",
)
async def test_connector(
    request: ConnectorAccessRequest,
    registry: Annotated[ConnectorRegistry, Depends(get_connector_registry)],
) -> ConnectorHealthResponse:
    if "TALK2DATA_ADMIN" not in request.access_context.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Connector administration access denied.",
        )
    connector = _get_connector(registry, request.connector_id)
    ready, detail = await connector.test_connection()
    return ConnectorHealthResponse(
        connector_id=request.connector_id,
        ready=ready,
        detail=detail,
    )


def _get_connector(registry: ConnectorRegistry, connector_id: str) -> DataConnector:
    try:
        return registry.get(connector_id)
    except ConnectorRegistryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _require_data_access(access: AccessContext) -> None:
    if READ_DATA_ACTION not in access.permitted_actions and "TALK2DATA_ADMIN" not in access.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Connector data access denied.",
        )
