from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from talk2data.connectors.base import ConnectorDescriptor, SourceFreshness
from talk2data.domain.models import AccessContext


class ConnectorAccessRequest(BaseModel):
    connector_id: str = Field(min_length=1, max_length=128)
    access_context: AccessContext


class ConnectorListRequest(BaseModel):
    access_context: AccessContext


class ConnectorListResponse(BaseModel):
    connectors: list[ConnectorDescriptor]


class ConnectorCatalogResponse(BaseModel):
    connector_id: str
    items: list[dict[str, Any]]


class ConnectorFreshnessResponse(BaseModel):
    connector_id: str
    freshness: SourceFreshness


class ConnectorHealthResponse(BaseModel):
    connector_id: str
    ready: bool
    detail: str
