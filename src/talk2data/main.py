from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from talk2data.api.routes import health, questions, sessions
from talk2data.core.config import Settings, get_settings
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.services.admissibility import QuestionAdmissibilityEngine
from talk2data.services.hermes import HermesConfiguration, HermesGatewayClient
from talk2data.services.interpreter import (
    CompositeQuestionInterpreter,
    HeuristicQuestionInterpreter,
    OllamaConfiguration,
    OllamaQuestionInterpreter,
)
from talk2data.services.policy import PolicyEngine
from talk2data.services.session_store import SQLiteSessionStore


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    domain_registry = DomainPackRegistry(resolved_settings.domain_pack_directory)
    domain_registry.load()

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
    admissibility_engine = QuestionAdmissibilityEngine(interpreter, PolicyEngine())
    session_store = SQLiteSessionStore(resolved_settings.database_path)

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
        yield

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        description=("Governed question-admissibility and conversational-intelligence control plane."),
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.domain_registry = domain_registry
    app.state.ollama_client = ollama_client
    app.state.hermes_client = hermes_client
    app.state.admissibility_engine = admissibility_engine
    app.state.session_store = session_store

    app.include_router(health.router)
    app.include_router(questions.router)
    app.include_router(sessions.router)
    return app


app = create_app()
