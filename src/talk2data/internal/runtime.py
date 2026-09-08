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
from talk2data.services.agent_runtime import AgentRun
from talk2data.services.claude_interpreter import BoundQuestionInterpreter, ClaudeRuntime
from talk2data.services.definition_governance import DefinitionGovernance
from talk2data.services.definition_store import DefinitionStore
from talk2data.services.demo_chat import DemoChatService
from talk2data.services.distributed_runs import DistributedCoordinator
from talk2data.services.ephemeral_run import EphemeralRunStore
from talk2data.services.policy import PolicyEngine
from talk2data.services.postgres_runs import PostgresRunStore
from talk2data.services.query_compiler import BusinessQueryCompiler
from talk2data.services.run_coordinator import Observer, RunCoordinator
from talk2data.services.run_store import RunStore
from talk2data.services.semantic import SemanticRegistry
from talk2data.services.semantic_context import cite_definitions
from talk2data.services.state_ports import DefinitionJournal


class InternalQueryBusy(RuntimeError):
    pass


class InternalQueryRuntime:
    def __init__(
        self,
        domains: DomainPackRegistry,
        registries: dict[str, ConnectorRegistry],
        maximum_active: int,
        definition_store: DefinitionJournal | None = None,
        language: ClaudeRuntime | None = None,
        run_store: RunStore | PostgresRunStore | None = None,
        source_binding: str = "unconfigured",
    ) -> None:
        self.domains, self.registries, self.maximum_active = domains, registries, maximum_active
        self.language = language or ClaudeRuntime()
        self.run_store = run_store or RunStore()
        self.runs = (
            DistributedCoordinator(self.run_store)
            if isinstance(self.run_store, PostgresRunStore)
            else RunCoordinator(self.run_store, maximum_active)
        )
        self.source_binding = source_binding
        self.definition_store = definition_store or DefinitionStore()
        self.definitions = {
            tenant: DefinitionGovernance(self.definition_store, f"internal:{tenant}", domains.get(tenant))
            for tenant in domains.list_tenants()
        }
        self.active: dict[tuple[str, str, UUID], asyncio.Task[DemoChatResponse]] = {}

    async def answer(
        self,
        *,
        request_id: UUID,
        question: str,
        as_of: datetime,
        access: AccessContext,
        definition_snapshot_id: str | None = None,
        observer: Observer | None = None,
        require_current: bool = True,
    ) -> DemoChatResponse:
        key = (access.tenant_id, access.user_id, request_id)
        if key in self.active:
            raise InternalQueryBusy("This request is already running.")
        if len(self.active) >= self.maximum_active:
            raise InternalQueryBusy("Internal query capacity is currently occupied.")
        definitions = self.definitions[access.tenant_id]
        snapshot = definitions.resolve(access, definition_snapshot_id, require_current=require_current)
        domains = DomainPackRegistry.from_snapshot(snapshot.pack)
        compiler = BusinessQueryCompiler(SemanticRegistry(domains, PolicyEngine()))
        run = AgentRun(self.language.config.limits, observer)
        interpreter = BoundQuestionInterpreter(self.language, access, run)
        service = DemoChatService(
            domain_registry=domains,
            admissibility_engine=QuestionAdmissibilityEngine(interpreter, PolicyEngine()),
            query_compiler=compiler,
            session_store=EphemeralRunStore(),
            connector_registry=self.registries[access.tenant_id],
            ai_model=self.language.config.model,
            synthetic_data=False,
            agent_run=run,
        )
        task = asyncio.create_task(
            service.answer(
                DemoChatRequest(
                    question=question,
                    access_context=access,
                    as_of=as_of,
                    use_llm=self.language.config.enabled,
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
        await self.runs.close()
        tasks = list(self.active.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.definition_store.close()
        self.run_store.close()
