from __future__ import annotations

from fastapi import Request

from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.services.admissibility import QuestionAdmissibilityEngine
from talk2data.services.hermes import HermesGatewayClient
from talk2data.services.interpreter import OllamaQuestionInterpreter
from talk2data.services.session_store import SQLiteSessionStore


def get_domain_registry(request: Request) -> DomainPackRegistry:
    return request.app.state.domain_registry


def get_admissibility_engine(request: Request) -> QuestionAdmissibilityEngine:
    return request.app.state.admissibility_engine


def get_session_store(request: Request) -> SQLiteSessionStore:
    return request.app.state.session_store


def get_ollama_client(request: Request) -> OllamaQuestionInterpreter | None:
    return request.app.state.ollama_client


def get_hermes_client(request: Request) -> HermesGatewayClient | None:
    return request.app.state.hermes_client
