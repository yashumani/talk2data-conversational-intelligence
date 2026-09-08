"""Compose the private API without importing or mounting the demonstration application."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from talk2data.api.agent_errors import install_agent_errors
from talk2data.api.definition_errors import install_definition_errors
from talk2data.api.run_routes import install_run_errors
from talk2data.api.web_assets import install_web_assets
from talk2data.connectors.bigquery import BigQueryConnector
from talk2data.connectors.registry import ConnectorRegistry
from talk2data.core.bigquery_config import BigQuerySettings
from talk2data.core.internal_config import InternalRuntimeConfig, InternalSettings
from talk2data.domain.bigquery_mapping import BigQueryCatalog
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.runs import digest
from talk2data.internal.definitions import router as definitions_router
from talk2data.internal.routes import router
from talk2data.internal.runs import router as runs_router
from talk2data.internal.runtime import InternalQueryRuntime
from talk2data.internal.worker import create_worker
from talk2data.operations.http import OperationalHttp
from talk2data.services.bigquery_port import BigQueryTransport
from talk2data.services.bigquery_sdk import GoogleBigQueryTransport
from talk2data.services.claude_interpreter import ClaudeRuntime
from talk2data.services.claude_transport import ClaudeTransport
from talk2data.services.definition_store import DefinitionStore
from talk2data.services.identity import (
    Entitlements,
    EntitlementStore,
    IdentityRejected,
    IdentityUnavailable,
    IdentityVerifier,
)
from talk2data.services.postgres_database import PostgresDatabase
from talk2data.services.postgres_governance import PostgresDefinitionStore, PostgresEntitlementStore
from talk2data.services.postgres_runs import PostgresRunStore
from talk2data.services.run_store import RunStore
from talk2data.services.state_ports import DefinitionJournal


def create_internal_app(
    config: InternalRuntimeConfig | None = None,
    *,
    transport_factory: Callable[[BigQuerySettings], BigQueryTransport] = GoogleBigQueryTransport,
    language_transport: ClaudeTransport | None = None,
) -> FastAPI:
    resolved = config or InternalRuntimeConfig.load(InternalSettings().config_file)
    language = ClaudeRuntime(resolved.claude, language_transport)
    domains = DomainPackRegistry(resolved.domain_pack_directory)
    domains.load()
    catalog = BigQueryCatalog.load(resolved.bigquery_catalog_path)
    database = PostgresDatabase(resolved.shared_state) if resolved.shared_state is not None else None
    if database is not None:
        database.check()
    run_store = PostgresRunStore(database) if database is not None else RunStore(resolved.state_database_path)
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
    entitlements: Entitlements = (
        PostgresEntitlementStore(database, resolved.identity.issuer)
        if database is not None
        else EntitlementStore(resolved.entitlements_path, resolved.identity.issuer)
    )
    verifier = IdentityVerifier(resolved.identity, entitlements)
    definitions: DefinitionJournal = (
        PostgresDefinitionStore(database)
        if database is not None
        else DefinitionStore(resolved.governance_database_path or resolved.state_database_path)
    )
    runtime = InternalQueryRuntime(
        domains,
        registries,
        resolved.maximum_active_queries,
        definitions,
        language,
        run_store,
        digest(
            {
                "catalog": catalog.model_dump(mode="json"),
                "bigquery": resolved.bigquery.model_dump(mode="json"),
                "language": resolved.claude.model_dump(mode="json"),
                "identity": resolved.identity.model_dump(mode="json"),
                "shared_state": resolved.shared_state.model_dump(mode="json")
                if resolved.shared_state
                else None,
            }
        ),
    )
    worker = create_worker(runtime, entitlements) if resolved.process_role == "worker" else None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            for connector in connectors:
                await connector.initialize()
            if worker is not None:
                worker.start()
            yield
        finally:
            if worker is not None:
                await worker.close()
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
    app.state.worker, app.state.database = worker, database

    @app.middleware("http")
    async def trusted_identity(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path == "/health/live":
            return await call_next(request)
        if worker is not None:
            if request.url.path == "/health/ready":
                return await call_next(request)
            return JSONResponse(
                {"detail": "This process does not serve application requests."}, status_code=404
            )
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
            if database is not None:
                grant = await verifier.grant(token)
                access = grant.access
                request.state.execution_grant = grant
            else:
                access = await verifier.verify(token)
            if access.tenant_id not in registries:
                return JSONResponse(
                    {"detail": "No internal source is available to this identity."}, status_code=403
                )
            request.state.identity, request.state.identity_token = access, token
            if resolved.identity.token_header == "x-goog-iap-jwt-assertion" and request.method in {
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
            }:
                if request.headers.get("X-T2D-Request") != "1":
                    return JSONResponse(
                        {"detail": "A same-origin workspace request is required."}, status_code=403
                    )
            response = await call_next(request)
        except IdentityRejected:
            response = JSONResponse({"detail": "Identity or authorization was rejected."}, status_code=401)
        except IdentityUnavailable:
            response = JSONResponse(
                {"detail": "Identity verification is temporarily unavailable."}, status_code=503
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
        )
        response.headers["X-Frame-Options"] = "DENY"
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
    async def ready() -> JSONResponse:
        if database is not None:
            database.check()
        healthy = worker is None or worker.healthy
        return JSONResponse(
            {
                "status": "ready" if healthy else "unavailable",
                "profile": "internal",
                "role": resolved.process_role,
            },
            status_code=200 if healthy else 503,
        )

    app.include_router(router)
    app.include_router(runs_router)
    app.include_router(definitions_router)
    install_web_assets(app, resolved.web_directory)
    install_definition_errors(app)
    install_agent_errors(app)
    install_run_errors(app)
    app.add_middleware(OperationalHttp, settings=resolved.http_operations)
    return app
