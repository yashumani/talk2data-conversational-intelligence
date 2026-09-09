"""Anonymous demo workspace. Deliberately independent of internal runtime bindings."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from talk2data.connectors.csv_demo import CsvDemoConnector
from talk2data.connectors.errors import ConnectorValidationError
from talk2data.connectors.registry import ConnectorRegistry
from talk2data.core.csv_config import CsvDemoSettings
from talk2data.domain.chat import ChatStatus, DemoChatRequest, DemoChatResponse
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.governance import DefinitionSnapshot
from talk2data.domain.models import AccessContext, ClassificationLevel, InterpretationResult
from talk2data.domain.runs import RunError, RunRequest, RunSnapshot, principal
from talk2data.services.admissibility import QuestionAdmissibilityEngine
from talk2data.services.agent_runtime import AgentFailure, AgentRun
from talk2data.services.csv_checkpoint import CsvCheckpoint, SavedInterpretation
from talk2data.services.csv_import import REGIONS, CsvDataset, parse_csv
from talk2data.services.definition_governance import EDIT, PUBLISH, REVIEW, REVOKE, DefinitionGovernance
from talk2data.services.definition_store import DefinitionStore, DefinitionUnavailable
from talk2data.services.demo_chat import DemoChatService
from talk2data.services.ephemeral_run import EphemeralRunStore
from talk2data.services.language_contract import BoundQuestionInterpreter, LanguageRuntime
from talk2data.services.language_factory import build_language_runtime
from talk2data.services.policy import ASK_ACTION, READ_DATA_ACTION, PolicyEngine
from talk2data.services.query_compiler import BusinessQueryCompiler
from talk2data.services.run_coordinator import Observer, RunCoordinator
from talk2data.services.run_store import RunStore
from talk2data.services.semantic import SemanticRegistry
from talk2data.services.semantic_context import cite_definitions
from talk2data.tools.definitions import ResolveMetricTool


class DemoSessionExpired(RuntimeError):
    pass


class DemoWorkspaceBusy(RuntimeError):
    pass


@dataclass
class SavedCsvRun:
    dataset: CsvDataset
    question: str
    as_of: datetime
    snapshot_id: str
    interpretation: InterpretationResult | None = None
    model: str | None = None


@dataclass
class DemoWorkspaceSession:
    user_id: str
    expires_at: float
    definitions: DefinitionGovernance
    dataset: CsvDataset | None = None
    last_response: DemoChatResponse | None = None
    busy: bool = False
    history: dict[str, SavedCsvRun] = field(default_factory=dict)
    language_questions: int = 0
    expires_wall: float = 0
    conversation_id: UUID = field(default_factory=uuid4)


class CsvDemoWorkspace:
    def __init__(self, settings: CsvDemoSettings, language: LanguageRuntime | None = None) -> None:
        self.settings = settings
        self.language = language or build_language_runtime()
        self._sessions: dict[str, DemoWorkspaceSession] = {}
        self.run_store = RunStore(settings.state_database_path)
        self.runs = RunCoordinator(self.run_store)
        self._definition_store = DefinitionStore(settings.state_database_path)
        # Always use packaged, public demo semantics. Never the internal tenant registry.
        self._domains = DomainPackRegistry()
        self._domains.load()
        self._pack = self._domains.get("demo-telecom")
        # CSV dates are explicit Gregorian UTC observation days, independent of internal calendars.
        self._pack = self._pack.model_copy(
            update={"default_calendar": "GREGORIAN", "default_timezone": "UTC"}, deep=True
        )
        self._policy = PolicyEngine()

    def _prune(self) -> None:
        now = time.monotonic()
        for token, item in self._sessions.items():
            if item.expires_at <= now and not item.busy:
                self._definition_store.delete(item.definitions.namespace)
                self.run_store.delete(*principal("csv", self._access(item)), item.conversation_id)
                self.run_store.checkpoint(token, None)
        for user_id in self.run_store.prune_checkpoints(time.time()):
            self._definition_store.delete(f"csv:{user_id}")
        self._sessions = {
            token: item for token, item in self._sessions.items() if item.expires_at > now or item.busy
        }

    def create_session(self) -> str:
        self._prune()
        if self.run_store.checkpoint_count() >= self.settings.maximum_sessions:
            raise DemoWorkspaceBusy("Demo capacity reached; retry after an existing session expires.")
        token = secrets.token_urlsafe(32)
        user_id = str(uuid4())
        self._sessions[token] = DemoWorkspaceSession(
            user_id=user_id,
            expires_at=time.monotonic() + self.settings.session_ttl_seconds,
            expires_wall=time.time() + self.settings.session_ttl_seconds,
            definitions=DefinitionGovernance(
                self._definition_store, f"csv:{user_id}", self._pack, separate_reviewer=False
            ),
        )
        item = self._sessions[token]
        self.run_store.create_conversation(*principal("csv", self._access(item)), item.conversation_id)
        self.persist(token, item)
        return token

    def get(self, token: str) -> DemoWorkspaceSession:
        self._prune()
        item = self._sessions.get(token)
        if item is None:
            raw = self.run_store.restore(token)
            if raw is not None:
                saved = CsvCheckpoint.model_validate(raw)
                if saved.version != 1:
                    raise DemoSessionExpired("The saved workspace version is unsupported.")
                item = DemoWorkspaceSession(
                    user_id=saved.user_id,
                    expires_at=time.monotonic() + saved.expires_wall - time.time(),
                    expires_wall=saved.expires_wall,
                    conversation_id=saved.conversation_id,
                    definitions=DefinitionGovernance(
                        self._definition_store, f"csv:{saved.user_id}", self._pack, separate_reviewer=False
                    ),
                    dataset=saved.dataset,
                    last_response=saved.last_response,
                    history={
                        key: SavedCsvRun(
                            value.dataset,
                            value.question,
                            value.as_of,
                            value.snapshot_id,
                            value.interpretation,
                            value.model,
                        )
                        for key, value in saved.history.items()
                    },
                    language_questions=saved.language_questions,
                )
                self._sessions[token] = item
        if item is None or item.expires_at <= time.monotonic():
            raise DemoSessionExpired("Demo session expired or is unknown. Start a new demo session.")
        return item

    @asynccontextmanager
    async def lease(self, token: str) -> AsyncIterator[DemoWorkspaceSession]:
        item = self.get(token)
        if item.busy:
            raise DemoWorkspaceBusy("This demo session already has an operation in progress.")
        item.busy = True
        try:
            yield item
        finally:
            item.busy = False
            self.persist(token, item)

    def clear(self, token: str) -> None:
        item = self.get(token)
        if item.busy:
            raise DemoWorkspaceBusy("Wait for the current operation before clearing the session.")
        self.run_store.delete(*principal("csv", self._access(item)), item.conversation_id)
        self.run_store.checkpoint(token, None)
        del self._sessions[token]
        self._definition_store.delete(item.definitions.namespace)

    def persist(self, token: str, item: DemoWorkspaceSession) -> None:
        self.run_store.checkpoint(
            token,
            CsvCheckpoint(
                user_id=item.user_id,
                expires_wall=item.expires_wall,
                conversation_id=item.conversation_id,
                dataset=item.dataset,
                last_response=item.last_response,
                language_questions=item.language_questions,
                history={
                    key: SavedInterpretation.model_validate(value, from_attributes=True)
                    for key, value in item.history.items()
                },
            ).payload(),
        )

    async def upload(self, item: DemoWorkspaceSession, raw: bytes) -> dict[str, object]:
        # Validate before replacing: an invalid upload leaves the previous source untouched.
        dataset = await asyncio.to_thread(
            parse_csv,
            raw,
            maximum_bytes=self.settings.maximum_bytes,
            maximum_rows=self.settings.maximum_rows,
        )
        item.dataset = dataset
        item.last_response = None
        return dataset.describe()

    def _access(self, item: DemoWorkspaceSession) -> AccessContext:
        return AccessContext(
            tenant_id=self._pack.tenant_id,
            user_id=item.user_id,
            roles={"BI_MANAGER"},
            departments={"SALES"},
            regions=set(REGIONS),
            business_units={"CONSUMER"},
            classification_clearance=ClassificationLevel.RESTRICTED,
            permitted_actions={ASK_ACTION, READ_DATA_ACTION, EDIT, REVIEW, PUBLISH, REVOKE},
        )

    def definition(self, item: DemoWorkspaceSession) -> dict[str, object]:
        # The view remains inspectable after revocation; execution resolves usable snapshots separately.
        pack = item.definitions.inspect_current(self._access(item)).pack
        semantics = SemanticRegistry(DomainPackRegistry.from_snapshot(pack), self._policy)
        return (
            ResolveMetricTool(semantics).run(self._access(item), "MOBILE_ACTIVATIONS").model_dump(mode="json")
        )

    def state(self, item: DemoWorkspaceSession) -> dict[str, object]:
        if item.last_response and item.last_response.semantic_context:
            try:
                item.definitions.resolve(self._access(item), item.last_response.semantic_context.snapshot_id)
            except DefinitionUnavailable:
                item.last_response = None
        return {
            "sync": {
                "enabled": True,
                "durable": self.settings.state_database_path is not None,
                "conversation": self.run_store.conversation(
                    *principal("csv", self._access(item)), item.conversation_id
                ).model_dump(mode="json"),
                "runs": [
                    {"run_id": str(run.run_id), "status": run.status, "question": run.request.question}
                    for run in self.run_store.runs(
                        *principal("csv", self._access(item)), item.conversation_id
                    )
                ],
            },
            "source": None if item.dataset is None else item.dataset.describe(),
            "definition": self.definition(item),
            "definitions": item.definitions.view(self._access(item)),
            "last_response": None
            if item.last_response is None
            else item.last_response.model_dump(mode="json"),
            "history": [
                {
                    "run_id": run_id,
                    "question": run.question,
                    "snapshot_id": run.snapshot_id,
                    "source_fingerprint": run.dataset.fingerprint,
                }
                for run_id, run in reversed(item.history.items())
            ],
            "interpreter": self.language.provider if self.language.config.enabled else "rules",
            "language": self.language.describe(),
            "internal_connections_available": False,
            "connections": [
                {"id": "csv", "status": "AVAILABLE"},
                {"id": "bigquery", "status": "NOT_CONFIGURED"},
            ],
        }

    async def answer(
        self,
        item: DemoWorkspaceSession,
        *,
        question: str,
        as_of: datetime,
        source_fingerprint: str,
        definition_snapshot_id: str | None = None,
    ) -> DemoChatResponse:
        dataset = item.dataset
        if dataset is None:
            raise ConnectorValidationError("Upload a CSV before asking a question.")
        if source_fingerprint != dataset.fingerprint:
            raise DemoWorkspaceBusy("The CSV changed. Refresh the source before asking again.")
        snapshot = item.definitions.resolve(self._access(item), definition_snapshot_id, require_current=True)
        item.last_response = None
        return await self._execute(item, dataset, question, as_of, snapshot)

    async def rerun(self, item: DemoWorkspaceSession, run_id: str) -> DemoChatResponse:
        saved = item.history.get(run_id)
        if saved is None:
            raise DefinitionUnavailable("The saved run is not available in this demo session.")
        snapshot = item.definitions.resolve(self._access(item), saved.snapshot_id)
        return await self._execute(
            item, saved.dataset, saved.question, saved.as_of, snapshot, saved.interpretation, saved.model
        )

    async def _execute(
        self,
        item: DemoWorkspaceSession,
        dataset: CsvDataset,
        question: str,
        as_of: datetime,
        snapshot: DefinitionSnapshot,
        replay: InterpretationResult | None = None,
        replay_model: str | None = None,
        observer: Observer | None = None,
        save_result: bool = True,
    ) -> DemoChatResponse:
        access = self._access(item)
        if self.language.config.enabled and replay is None:
            if item.language_questions >= self.settings.maximum_language_questions:
                raise AgentFailure(
                    "SESSION_LANGUAGE_BUDGET",
                    "This demo session has reached its language question limit.",
                    429,
                )
            item.language_questions += 1
        run = AgentRun(self.language.config.limits, observer)
        interpreter = BoundQuestionInterpreter(self.language, access, run, replay, replay_model)
        domains = DomainPackRegistry.from_snapshot(snapshot.pack)
        semantics = SemanticRegistry(domains, self._policy)
        registry = ConnectorRegistry()
        # A fresh per-run registry is the routing boundary: no internal connector can be reached.
        for connector_id in {metric.source.connector_id for metric in snapshot.pack.metrics}:
            registry.register(
                CsvDemoConnector(
                    dataset=dataset,
                    connector_id=connector_id,
                    tenant_id=access.tenant_id,
                    user_id=access.user_id,
                )
            )
        service = DemoChatService(
            domain_registry=domains,
            admissibility_engine=QuestionAdmissibilityEngine(interpreter, self._policy),
            query_compiler=BusinessQueryCompiler(semantics),
            session_store=EphemeralRunStore(),
            connector_registry=registry,
            ai_model=replay_model if replay is not None else self.language.config.model,
            synthetic_data=False,
            agent_run=run,
        )
        response = await service.answer(
            DemoChatRequest(
                question=question,
                access_context=access,
                as_of=as_of,
                use_llm=self.language.config.enabled,
                include_debug=True,
            )
        )
        # Publication can coexist with a pinned run; revocation cannot release its result.
        item.definitions.resolve(access, snapshot.snapshot_id)
        cite_definitions(response, snapshot)
        if response.status == ChatStatus.ANSWERED and response.receipt:
            item.history[str(response.receipt.query_id)] = SavedCsvRun(
                dataset, question, as_of, snapshot.snapshot_id, run.interpretation, response.ai_model
            )
            while len(item.history) > 4:
                item.history.pop(next(iter(item.history)))
        # Historical reruns retain their source and never select an older upload silently.
        if save_result and item.dataset and item.dataset.fingerprint == dataset.fingerprint:
            item.last_response = response
        return response

    def submit_run(self, token: str, request: RunRequest) -> RunSnapshot:
        item = self.get(token)
        owner, scope = principal("csv", self._access(item))
        if request.conversation_id != item.conversation_id:
            raise RunError("The conversation does not belong to this workspace.", 404)
        existing = self.run_store.existing(owner, scope, request)
        if existing is not None:
            self.check_run(token, existing.run_id)
            return existing
        if item.busy:
            raise DemoWorkspaceBusy("This demo session already has an operation in progress.")
        dataset = item.dataset
        if dataset is None or request.source_fingerprint != dataset.fingerprint:
            raise RunError("The selected CSV changed. Refresh before submitting.")
        snapshot = item.definitions.resolve(
            self._access(item), request.definition_snapshot_id, require_current=True
        )
        history_before = dict(item.history)

        async def authorized() -> None:
            current = self.get(token)
            current.definitions.resolve(self._access(current), snapshot.snapshot_id)
            if current.dataset is None or current.dataset.fingerprint != dataset.fingerprint:
                raise RunError("The selected CSV changed during execution.")

        async def operation(observer: Observer) -> DemoChatResponse:
            return await self._execute(
                item, dataset, request.question, request.as_of, snapshot, observer=observer, save_result=False
            )

        def accepted() -> None:
            item.busy, item.last_response = True, None
            self.persist(token, item)

        def released() -> None:
            item.busy = False
            finished = self.run_store.existing(owner, scope, request)
            if finished is not None and finished.status == "COMPLETED":
                item.last_response = finished.result
            else:
                item.history = history_before
            self.persist(token, item)

        return self.runs.submit(
            owner, scope, request, dataset.fingerprint, operation, authorized, accepted, released
        )

    def check_run(self, token: str, identifier: UUID) -> RunSnapshot:
        item = self.get(token)
        run = self.run_store.read(*principal("csv", self._access(item)), identifier)
        if run.request.conversation_id != item.conversation_id:
            raise RunError("The run does not belong to this workspace.", 404)
        item.definitions.resolve(self._access(item), run.request.definition_snapshot_id)
        return run

    def close(self) -> None:
        self._sessions.clear()
        self._definition_store.close()
        self.run_store.close()
