from __future__ import annotations

from typing import cast

from fastapi import Request

from talk2data.connectors.registry import ConnectorRegistry
from talk2data.deployment.runtime_package import RuntimePackageBuilder
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.physical_mapping import PhysicalMappingRegistry
from talk2data.services.admissibility import QuestionAdmissibilityEngine
from talk2data.services.hermes import HermesGatewayClient
from talk2data.services.interpreter import OllamaQuestionInterpreter
from talk2data.services.query_compiler import BusinessQueryCompiler
from talk2data.services.semantic import SemanticRegistry
from talk2data.services.session_store import SQLiteSessionStore


def get_domain_registry(request: Request) -> DomainPackRegistry:
    return cast(DomainPackRegistry, request.app.state.domain_registry)


def get_physical_mapping_registry(request: Request) -> PhysicalMappingRegistry:
    return cast(PhysicalMappingRegistry, request.app.state.physical_mapping_registry)


def get_runtime_package_builder(request: Request) -> RuntimePackageBuilder:
    return cast(RuntimePackageBuilder, request.app.state.runtime_package_builder)


def get_admissibility_engine(request: Request) -> QuestionAdmissibilityEngine:
    return cast(QuestionAdmissibilityEngine, request.app.state.admissibility_engine)


def get_session_store(request: Request) -> SQLiteSessionStore:
    return cast(SQLiteSessionStore, request.app.state.session_store)


def get_semantic_registry(request: Request) -> SemanticRegistry:
    return cast(SemanticRegistry, request.app.state.semantic_registry)


def get_query_compiler(request: Request) -> BusinessQueryCompiler:
    return cast(BusinessQueryCompiler, request.app.state.query_compiler)


def get_connector_registry(request: Request) -> ConnectorRegistry:
    return cast(ConnectorRegistry, request.app.state.connector_registry)


def get_ollama_client(request: Request) -> OllamaQuestionInterpreter | None:
    return cast(OllamaQuestionInterpreter | None, request.app.state.ollama_client)


def get_hermes_client(request: Request) -> HermesGatewayClient | None:
    return cast(HermesGatewayClient | None, request.app.state.hermes_client)
