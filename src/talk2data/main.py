from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from talk2data.api.routes import (
    chat,
    connectors,
    health,
    physical_mappings,
    query_plans,
    questions,
    semantics,
    sessions,
)
from talk2data.connectors.base import DataConnector
from talk2data.connectors.demo_sqlite import DemoSQLiteConnector
from talk2data.connectors.postgres import PostgreSQLConnector
from talk2data.connectors.registry import ConnectorRegistry
from talk2data.core.config import DataBackend, Settings, get_settings
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import TenantDomainPack
from talk2data.domain.physical_mapping import (
    PhysicalConnectorMapping,
    PhysicalMappingRegistry,
    physical_connector_hash,
)
from talk2data.services.admissibility import QuestionAdmissibilityEngine
from talk2data.services.demo_chat import DemoChatService
from talk2data.services.hermes import HermesConfiguration, HermesGatewayClient
from talk2data.services.interpreter import (
    CompositeQuestionInterpreter,
    HeuristicQuestionInterpreter,
    OllamaConfiguration,
    OllamaQuestionInterpreter,
)
from talk2data.services.policy import PolicyEngine
from talk2data.services.query_compiler import BusinessQueryCompiler
from talk2data.services.secrets import EnvironmentSecretResolver, SecretResolver
from talk2data.services.semantic import SemanticRegistry
from talk2data.services.session_store import SQLiteSessionStore


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    domain_registry = DomainPackRegistry(resolved_settings.domain_pack_directory)
    domain_registry.load()
    domain_pack = domain_registry.get(resolved_settings.default_tenant_id)

    physical_mapping_registry = PhysicalMappingRegistry(resolved_settings.physical_mapping_directory)
    physical_mapping_registry.load()
    mapping_failures = physical_mapping_registry.validate_domain_pack(domain_pack)
    if mapping_failures:
        raise ValueError("physical mapping validation failed: " + ", ".join(mapping_failures))

    ollama_client = (
        OllamaQuestionInterpreter(
            OllamaConfiguration(
                base_url=resolved_settings.ollama_base_url,
                model=resolved_settings.ollama_model,
                timeout_seconds=resolved_settings.ollama_timeout_seconds,
            )
        )
        if resolved_settings.ollama_enabled
        else None
    )
    interpreter = CompositeQuestionInterpreter(
        HeuristicQuestionInterpreter(),
        ollama_client,
        ollama_required=resolved_settings.ollama_required,
    )
    policy_engine = PolicyEngine()
    admissibility_engine = QuestionAdmissibilityEngine(interpreter, policy_engine)
    semantic_registry = SemanticRegistry(domain_registry, policy_engine)
    query_compiler = BusinessQueryCompiler(semantic_registry)
    session_store = SQLiteSessionStore(resolved_settings.database_path)

    runtime_connectors = _build_connectors(
        settings=resolved_settings,
        domain_pack=domain_pack,
        physical_mappings=physical_mapping_registry,
        secret_resolver=EnvironmentSecretResolver(),
    )
    connector_registry = ConnectorRegistry()
    for connector in runtime_connectors:
        connector_registry.register(connector)

    demo_chat_service = DemoChatService(
        domain_registry=domain_registry,
        admissibility_engine=admissibility_engine,
        query_compiler=query_compiler,
        session_store=session_store,
        connector_registry=connector_registry,
        ai_model=(resolved_settings.ollama_model if resolved_settings.ollama_enabled else None),
        synthetic_data=resolved_settings.data_backend == DataBackend.DEMO_SQLITE,
    )

    hermes_client = None
    if resolved_settings.hermes_enabled:
        if not resolved_settings.hermes_api_key:
            raise ValueError("T2D_HERMES_API_KEY is required when Hermes integration is enabled")
        hermes_client = HermesGatewayClient(
            HermesConfiguration(
                base_url=resolved_settings.hermes_base_url,
                api_key=resolved_settings.hermes_api_key,
                timeout_seconds=resolved_settings.hermes_timeout_seconds,
            )
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await session_store.initialize()
        for connector in runtime_connectors:
            await connector.initialize()
        yield

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.5.0",
        description=(
            "Governed question interpretation, deterministic query planning, and receipt-backed "
            "answers through versioned semantic-to-physical connector mappings."
        ),
        lifespan=lifespan,
    )
    if resolved_settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_settings.cors_allowed_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Accept", "Content-Type"],
        )

    app.state.settings = resolved_settings
    app.state.domain_registry = domain_registry
    app.state.physical_mapping_registry = physical_mapping_registry
    app.state.ollama_client = ollama_client
    app.state.hermes_client = hermes_client
    app.state.admissibility_engine = admissibility_engine
    app.state.semantic_registry = semantic_registry
    app.state.query_compiler = query_compiler
    app.state.session_store = session_store
    app.state.connector_registry = connector_registry
    app.state.demo_chat_service = demo_chat_service

    app.include_router(chat.router)
    app.include_router(connectors.router)
    app.include_router(physical_mappings.router)
    app.include_router(health.router)
    app.include_router(questions.router)
    app.include_router(query_plans.router)
    app.include_router(semantics.router)
    app.include_router(sessions.router)
    return app


def _build_connectors(
    *,
    settings: Settings,
    domain_pack: TenantDomainPack,
    physical_mappings: PhysicalMappingRegistry,
    secret_resolver: SecretResolver,
) -> list[DataConnector]:
    metric_groups = _available_metric_groups(domain_pack)
    if settings.data_backend == DataBackend.POSTGRESQL:
        mapping_pack = physical_mappings.get(domain_pack.tenant_id)
        connectors: list[DataConnector] = []
        for connector_id in sorted(metric_groups):
            mapping = mapping_pack.connector(connector_id)
            effective_mapping = _apply_physical_object_overrides(mapping, settings)
            dsn = (
                settings.postgres_dsn.get_secret_value()
                if settings.postgres_dsn is not None
                else secret_resolver.resolve(effective_mapping.secret_ref).get_secret_value()
            )
            connectors.append(
                PostgreSQLConnector(
                    mapping=effective_mapping,
                    mapping_version=mapping_pack.version,
                    mapping_hash=physical_connector_hash(
                        tenant_id=mapping_pack.tenant_id,
                        version=mapping_pack.version,
                        connector=effective_mapping,
                    ),
                    dsn=dsn,
                    maximum_rows=settings.postgres_maximum_rows,
                    query_timeout_seconds=settings.postgres_query_timeout_seconds,
                    connect_timeout_seconds=settings.postgres_connect_timeout_seconds,
                )
            )
        return connectors

    demo_database_path = settings.database_path.with_name("demo-telecom.db")
    return [
        DemoSQLiteConnector(
            connector_id=connector_id,
            database_path=demo_database_path,
            allowed_metric_ids=metric_ids,
        )
        for connector_id, metric_ids in sorted(metric_groups.items())
    ]


def _available_metric_groups(domain_pack: TenantDomainPack) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    for metric in domain_pack.metrics:
        if metric.source.status.value != "AVAILABLE":
            continue
        groups.setdefault(metric.source.connector_id, set()).add(metric.id)
    return groups


def _apply_physical_object_overrides(
    mapping: PhysicalConnectorMapping,
    settings: Settings,
) -> PhysicalConnectorMapping:
    update: dict[str, object] = {}
    if settings.postgres_schema is not None:
        update["schema_name"] = settings.postgres_schema
    if settings.postgres_table is not None:
        update["table_name"] = settings.postgres_table
    if not update:
        return mapping
    payload = mapping.model_dump(mode="python")
    payload.update(update)
    return PhysicalConnectorMapping.model_validate(payload)


app = create_app()
