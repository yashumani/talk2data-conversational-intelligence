"""Compose the private API without importing or mounting the demonstration application."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from talk2data.connectors.bigquery import BigQueryConnector
from talk2data.connectors.registry import ConnectorRegistry
from talk2data.core.bigquery_config import BigQuerySettings
from talk2data.core.internal_config import InternalRuntimeConfig, InternalSettings
from talk2data.domain.bigquery_mapping import BigQueryCatalog
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.internal.routes import router
from talk2data.internal.runtime import InternalQueryRuntime
from talk2data.services.bigquery_port import BigQueryTransport
from talk2data.services.bigquery_sdk import GoogleBigQueryTransport
from talk2data.services.identity import (
    EntitlementStore,
    IdentityRejected,
    IdentityUnavailable,
    IdentityVerifier,
)


def create_internal_app(
    config: InternalRuntimeConfig | None = None,
    *,
    transport_factory: Callable[[BigQuerySettings], BigQueryTransport] = GoogleBigQueryTransport,
) -> FastAPI:
    resolved = config or InternalRuntimeConfig.load(InternalSettings().config_file)
    domains = DomainPackRegistry(resolved.domain_pack_directory)
    domains.load()
    catalog = BigQueryCatalog.load(resolved.bigquery_catalog_path)
    registries: dict[str, ConnectorRegistry] = {}
    connectors = []
    transports = []
    # Validate every configuration binding before creating any ADC-backed cloud clients.
    for mapping in catalog.mappings:
        mapping.validate_domain(domains.get(mapping.tenant_id))
    for tenant in domains.list_tenants():
        pack = domains.get(tenant)
        available = {metric.id for metric in pack.metrics if metric.source.status.value == "AVAILABLE"}
        mapped = {
            metric.metric_id
            for mapping in catalog.mappings
            if mapping.tenant_id == tenant
            for metric in mapping.metrics
        }
        if available != mapped:
            raise ValueError("Every available internal metric requires an exact approved BigQuery binding.")
    for mapping in catalog.mappings:
        transport = transport_factory(resolved.bigquery)
        transports.append(transport)
        connector = BigQueryConnector(mapping, resolved.bigquery, transport)
        connectors.append(connector)
        registries.setdefault(mapping.tenant_id, ConnectorRegistry()).register(connector)
    verifier = IdentityVerifier(
        resolved.identity, EntitlementStore(resolved.entitlements_path, resolved.identity.issuer)
    )
    runtime = InternalQueryRuntime(domains, registries, resolved.maximum_active_queries)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            for connector in connectors:
                await connector.initialize()
            yield
        finally:
            await runtime.close()
            for transport in transports:
                await asyncio.to_thread(transport.close)

    app = FastAPI(
        title="Talk2Data Internal API",
        version="0.6.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.runtime, app.state.verifier = runtime, verifier

    @app.middleware("http")
    async def trusted_identity(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path == "/health/live":
            return await call_next(request)
        headers = request.headers.getlist(resolved.identity.token_header)
        if len(headers) != 1:
            return JSONResponse({"detail": "One signed identity token is required."}, status_code=401)
        token = headers[0]
        if resolved.identity.token_header == "authorization":
            scheme, separator, value = token.partition(" ")
            if scheme.lower() != "bearer" or not separator or not value:
                return JSONResponse({"detail": "A bearer identity token is required."}, status_code=401)
            token = value
        try:
            access = await verifier.verify(token)
            if access.tenant_id not in registries:
                return JSONResponse(
                    {"detail": "No internal source is available to this identity."}, status_code=403
                )
            request.state.identity, request.state.identity_token = access, token
            response = await call_next(request)
        except IdentityRejected:
            response = JSONResponse({"detail": "Identity or authorization was rejected."}, status_code=401)
        except IdentityUnavailable:
            response = JSONResponse(
                {"detail": "Identity verification is temporarily unavailable."}, status_code=503
            )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def sanitized_input_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"detail": [{"loc": error["loc"], "type": error["type"]} for error in exc.errors()]},
            status_code=422,
        )

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready", "profile": "internal"}

    app.include_router(router)
    return app
