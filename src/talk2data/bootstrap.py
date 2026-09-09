from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from talk2data.api.agent_errors import install_agent_errors
from talk2data.api.definition_errors import install_definition_errors
from talk2data.api.demo_errors import install_demo_errors
from talk2data.api.routes import (
    chat,
    connectors,
    csv_definitions,
    csv_demo,
    csv_runs,
    health,
    physical_mappings,
    query_plans,
    questions,
    runtime_packages,
    semantics,
    sessions,
)
from talk2data.api.run_routes import install_run_errors
from talk2data.api.web_assets import install_web_assets
from talk2data.connectors.factory import build_connectors
from talk2data.connectors.registry import ConnectorRegistry
from talk2data.core.config import DataBackend, Settings, get_settings
from talk2data.core.csv_config import CsvDemoSettings
from talk2data.core.language_config import CsvLanguageSettings
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.physical_mapping import PhysicalMappingRegistry
from talk2data.services.admissibility import QuestionAdmissibilityEngine
from talk2data.services.csv_workspace import CsvDemoWorkspace
from talk2data.services.demo_chat import DemoChatService
from talk2data.services.hermes import HermesConfiguration, HermesGatewayClient
from talk2data.services.interpreter import (
    CompositeQuestionInterpreter,
    HeuristicQuestionInterpreter,
    OllamaConfiguration,
    OllamaQuestionInterpreter,
)
from talk2data.services.language_factory import (
    ProviderConfiguration,
    ProviderTransport,
    build_language_runtime,
    load_language_configuration,
)
from talk2data.services.policy import PolicyEngine
from talk2data.services.query_compiler import BusinessQueryCompiler
from talk2data.services.secrets import EnvironmentSecretResolver
from talk2data.services.semantic import SemanticRegistry
from talk2data.services.session_store import SQLiteSessionStore

_SENSITIVE_VALIDATION_FIELDS = frozenset(
    {
        "api_key",
        "credential",
        "dsn",
        "password",
        "secret",
        "secret_ref",
        "token",
    }
)


def create_app(
    settings: Settings | None = None,
    *,
    csv_settings: CsvDemoSettings | None = None,
    csv_language_config: ProviderConfiguration | None = None,
    csv_language_transport: ProviderTransport | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_csv_settings = csv_settings or CsvDemoSettings()
    language_config = csv_language_config
    if resolved_csv_settings.enabled and language_config is None:
        language_path = CsvLanguageSettings().config_file
        language_config = None if language_path is None else load_language_configuration(language_path)

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

    runtime_connectors = build_connectors(
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
        try:
            yield
        finally:
            if app.state.csv_workspace is not None:
                await app.state.csv_workspace.runs.close()
                app.state.csv_workspace.close()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.6.0",
        description=(
            "Governed question interpretation, deterministic query planning, receipt-backed "
            "answers, and installable tenant runtime package generation."
        ),
        lifespan=lifespan,
    )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        sanitized: list[dict[str, Any]] = []
        for raw_error in exc.errors():
            error: dict[str, Any] = dict(raw_error)
            if _is_sensitive_validation_location(error.get("loc")):
                error["input"] = "[REDACTED]"
            context = error.get("ctx")
            if isinstance(context, dict):
                error["ctx"] = {str(key): str(value) for key, value in context.items()}
            sanitized.append(error)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": sanitized},
        )

    if resolved_settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_settings.cors_allowed_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Accept", "Content-Type", "X-Demo-Session", "Last-Event-ID"],
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
    app.state.csv_workspace = (
        CsvDemoWorkspace(
            resolved_csv_settings, build_language_runtime(language_config, csv_language_transport)
        )
        if resolved_csv_settings.enabled
        else None
    )

    install_demo_errors(app)
    install_definition_errors(app)
    install_agent_errors(app)
    install_run_errors(app)
    install_web_assets(app, resolved_settings.web_directory)
    app.include_router(csv_demo.router)
    app.include_router(csv_runs.router)
    app.include_router(csv_definitions.router)
    app.include_router(chat.router)
    app.include_router(connectors.router)
    app.include_router(physical_mappings.router)
    app.include_router(runtime_packages.router)
    app.include_router(health.router)
    app.include_router(questions.router)
    app.include_router(query_plans.router)
    app.include_router(semantics.router)
    app.include_router(sessions.router)
    return app


def _is_sensitive_validation_location(location: Any) -> bool:
    if not isinstance(location, (list, tuple)):
        return False
    return any(
        any(sensitive in str(segment).lower() for sensitive in _SENSITIVE_VALIDATION_FIELDS)
        for segment in location
    )
