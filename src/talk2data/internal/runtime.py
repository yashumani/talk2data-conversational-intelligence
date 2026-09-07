"""Bounded in-process internal requests; durable conversation execution belongs to cycle 5."""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID

from talk2data.connectors.registry import ConnectorRegistry
from talk2data.domain.chat import DemoChatRequest, DemoChatResponse
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import AccessContext
from talk2data.services.admissibility import QuestionAdmissibilityEngine
from talk2data.services.definition_governance import DefinitionGovernance
from talk2data.services.definition_store import DefinitionStore
from talk2data.services.demo_chat import DemoChatService
from talk2data.services.ephemeral_run import EphemeralRunStore
from talk2data.services.interpreter import CompositeQuestionInterpreter, HeuristicQuestionInterpreter
from talk2data.services.policy import PolicyEngine
from talk2data.services.query_compiler import BusinessQueryCompiler
from talk2data.services.semantic import SemanticRegistry
from talk2data.services.semantic_context import cite_definitions


class InternalQueryBusy(RuntimeError):
    pass


class InternalQueryRuntime:
    def __init__(
        self,
        domains: DomainPackRegistry,
        registries: dict[str, ConnectorRegistry],
        maximum_active: int,
        definition_store: DefinitionStore | None = None,
    ) -> None:
        self.domains, self.registries, self.maximum_active = domains, registries, maximum_active
        self.definition_store = definition_store or DefinitionStore()
        self.definitions = {
            tenant: DefinitionGovernance(self.definition_store, f"internal:{tenant}", domains.get(tenant))
            for tenant in domains.list_tenants()
        }
        policy = PolicyEngine()
        self.semantics = SemanticRegistry(domains, policy)
        self.compiler = BusinessQueryCompiler(self.semantics)
        self.admissibility = QuestionAdmissibilityEngine(
            CompositeQuestionInterpreter(HeuristicQuestionInterpreter(), None),
            policy,
        )
        self.active: dict[tuple[str, str, UUID], asyncio.Task[DemoChatResponse]] = {}

    async def answer(
        self,
        *,
        request_id: UUID,
        question: str,
        as_of: datetime,
        access: AccessContext,
        definition_snapshot_id: str | None = None,
    ) -> DemoChatResponse:
        key = (access.tenant_id, access.user_id, request_id)
        if key in self.active:
            raise InternalQueryBusy("This request is already running.")
        if len(self.active) >= self.maximum_active:
            raise InternalQueryBusy("Internal query capacity is currently occupied.")
        definitions = self.definitions[access.tenant_id]
        snapshot = definitions.resolve(access, definition_snapshot_id, require_current=True)
        domains = DomainPackRegistry.from_snapshot(snapshot.pack)
        compiler = BusinessQueryCompiler(SemanticRegistry(domains, PolicyEngine()))
        service = DemoChatService(
            domain_registry=domains,
            admissibility_engine=self.admissibility,
            query_compiler=compiler,
            session_store=EphemeralRunStore(),
            connector_registry=self.registries[access.tenant_id],
            ai_model=None,
            synthetic_data=False,
        )
        task = asyncio.create_task(
            service.answer(
                DemoChatRequest(
                    question=question,
                    access_context=access,
                    as_of=as_of,
                    use_llm=False,
                    include_debug=True,
                )
            )
        )
        self.active[key] = task
        try:
            response = await task
            definitions.resolve(access, snapshot.snapshot_id)
            return cite_definitions(response, snapshot)
        finally:
            self.active.pop(key, None)

    def cancel(self, request_id: UUID, access: AccessContext) -> bool:
        task = self.active.get((access.tenant_id, access.user_id, request_id))
        if task is None:
            return False
        return task.cancel()

    async def close(self) -> None:
        tasks = list(self.active.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.definition_store.close()
