from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from talk2data.api.dependencies import (
    get_connector_registry,
    get_domain_registry,
    get_hermes_client,
    get_ollama_client,
    get_physical_mapping_registry,
    get_session_store,
)
from talk2data.connectors.registry import ConnectorRegistry
from talk2data.core.config import RuntimeProfile
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import ComponentHealth, ReadinessResponse
from talk2data.domain.physical_mapping import PhysicalMappingRegistry
from talk2data.services.hermes import HermesGatewayClient
from talk2data.services.interpreter import OllamaQuestionInterpreter
from talk2data.services.session_store import SQLiteSessionStore

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(
    request: Request,
    response: Response,
    registry: Annotated[DomainPackRegistry, Depends(get_domain_registry)],
    mappings: Annotated[
        PhysicalMappingRegistry,
        Depends(get_physical_mapping_registry),
    ],
    sessions: Annotated[SQLiteSessionStore, Depends(get_session_store)],
    connectors: Annotated[ConnectorRegistry, Depends(get_connector_registry)],
    ollama: Annotated[OllamaQuestionInterpreter | None, Depends(get_ollama_client)],
    hermes: Annotated[HermesGatewayClient | None, Depends(get_hermes_client)],
) -> ReadinessResponse:
    components: dict[str, ComponentHealth] = {
        "domain_packs": ComponentHealth(
            status="ready" if registry.loaded else "failed",
            detail=f"Loaded tenants: {', '.join(registry.list_tenants())}",
        ),
        "physical_mappings": ComponentHealth(
            status="ready" if mappings.loaded else "failed",
            detail=f"Loaded tenants: {', '.join(mappings.list_tenants())}",
        ),
    }

    session_ok, session_detail = await sessions.health()
    components["session_store"] = ComponentHealth(
        status="ready" if session_ok else "failed",
        detail=session_detail,
    )

    for connector in connectors.connectors():
        connector_ok, connector_detail = await connector.test_connection()
        components[f"connector:{connector.descriptor.connector_id}"] = ComponentHealth(
            status="ready" if connector_ok else "failed",
            detail=connector_detail,
            metadata={
                "connector_type": connector.descriptor.connector_type,
                "read_only": connector.descriptor.read_only,
                "mapping_version": connector.descriptor.mapping_version,
                "mapping_hash": connector.descriptor.mapping_hash,
            },
        )

    if ollama is None:
        components["ollama"] = ComponentHealth(status="disabled")
    else:
        ollama_ok, ollama_detail = await ollama.health()
        required = request.app.state.settings.ollama_required
        components["ollama"] = ComponentHealth(
            status="ready" if ollama_ok else ("failed" if required else "degraded"),
            detail=ollama_detail,
        )

    if hermes is None:
        components["hermes"] = ComponentHealth(status="disabled")
    else:
        hermes_ok, hermes_detail = await hermes.health()
        components["hermes"] = ComponentHealth(
            status="ready" if hermes_ok else "degraded",
            detail=hermes_detail,
        )

    if request.app.state.settings.runtime_profile == RuntimeProfile.PUBLIC_SYNTHETIC:
        connector_ready = all(
            component.status == "ready"
            for name, component in components.items()
            if name.startswith("connector:")
        )
        components = {
            "domain_packs": ComponentHealth(status=components["domain_packs"].status),
            "physical_mappings": ComponentHealth(status=components["physical_mappings"].status),
            "session_store": ComponentHealth(status=components["session_store"].status),
            "synthetic_connector": ComponentHealth(status="ready" if connector_ready else "failed"),
            "external_models": ComponentHealth(status="disabled"),
        }

    hard_failure = any(
        component.status == "failed"
        for name, component in components.items()
        if name in {"domain_packs", "physical_mappings", "session_store", "synthetic_connector", "ollama"}
        or name.startswith("connector:")
    )
    overall = "failed" if hard_failure else "ready"
    if hard_failure:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status=overall, components=components)
