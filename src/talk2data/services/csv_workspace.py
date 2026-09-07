"""Anonymous demo workspace. Deliberately independent of internal runtime bindings."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from talk2data.connectors.csv_demo import CsvDemoConnector
from talk2data.connectors.errors import ConnectorValidationError
from talk2data.connectors.registry import ConnectorRegistry
from talk2data.core.csv_config import CsvDemoSettings
from talk2data.domain.chat import DemoChatRequest, DemoChatResponse
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import AccessContext, ClassificationLevel
from talk2data.services.admissibility import QuestionAdmissibilityEngine
from talk2data.services.csv_import import REGIONS, CsvDataset, parse_csv
from talk2data.services.demo_chat import DemoChatService
from talk2data.services.ephemeral_run import EphemeralRunStore
from talk2data.services.interpreter import CompositeQuestionInterpreter, HeuristicQuestionInterpreter
from talk2data.services.policy import ASK_ACTION, READ_DATA_ACTION, PolicyEngine
from talk2data.services.query_compiler import BusinessQueryCompiler
from talk2data.services.semantic import SemanticRegistry
from talk2data.tools.definitions import ResolveMetricTool


class DemoSessionExpired(RuntimeError):
    pass


class DemoWorkspaceBusy(RuntimeError):
    pass


@dataclass
class DemoWorkspaceSession:
    user_id: str
    expires_at: float
    dataset: CsvDataset | None = None
    last_response: DemoChatResponse | None = None
    busy: bool = False


class CsvDemoWorkspace:
    def __init__(self, settings: CsvDemoSettings) -> None:
        self.settings = settings
        self._sessions: dict[str, DemoWorkspaceSession] = {}
        # Always use packaged, public demo semantics. Never the internal tenant registry.
        self._domains = DomainPackRegistry()
        self._domains.load()
        self._pack = self._domains.get("demo-telecom")
        self._policy = PolicyEngine()
        self._semantics = SemanticRegistry(self._domains, self._policy)
        self._compiler = BusinessQueryCompiler(self._semantics)
        self._admissibility = QuestionAdmissibilityEngine(
            CompositeQuestionInterpreter(HeuristicQuestionInterpreter(), None),
            self._policy,
        )

    def _prune(self) -> None:
        now = time.monotonic()
        self._sessions = {
            token: item for token, item in self._sessions.items() if item.expires_at > now or item.busy
        }

    def create_session(self) -> str:
        self._prune()
        if len(self._sessions) >= self.settings.maximum_sessions:
            raise DemoWorkspaceBusy("Demo capacity reached; retry after an existing session expires.")
        token = secrets.token_urlsafe(32)
        self._sessions[token] = DemoWorkspaceSession(
            user_id=str(uuid4()),
            expires_at=time.monotonic() + self.settings.session_ttl_seconds,
        )
        return token

    def get(self, token: str) -> DemoWorkspaceSession:
        self._prune()
        item = self._sessions.get(token)
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

    def clear(self, token: str) -> None:
        item = self.get(token)
        if item.busy:
            raise DemoWorkspaceBusy("Wait for the current operation before clearing the session.")
        del self._sessions[token]

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
            classification_clearance=ClassificationLevel.CONFIDENTIAL,
            permitted_actions={ASK_ACTION, READ_DATA_ACTION},
        )

    def definition(self, item: DemoWorkspaceSession) -> dict[str, object]:
        result = ResolveMetricTool(self._semantics).run(self._access(item), "MOBILE_ACTIVATIONS")
        return result.model_dump(mode="json")

    async def answer(
        self,
        item: DemoWorkspaceSession,
        *,
        question: str,
        as_of: datetime,
        source_fingerprint: str,
    ) -> DemoChatResponse:
        dataset = item.dataset
        if dataset is None:
            raise ConnectorValidationError("Upload a CSV before asking a question.")
        if source_fingerprint != dataset.fingerprint:
            raise DemoWorkspaceBusy("The CSV changed. Refresh the source before asking again.")
        access = self._access(item)
        registry = ConnectorRegistry()
        # A fresh per-run registry is the routing boundary: no internal connector can be reached.
        for connector_id in {metric.source.connector_id for metric in self._pack.metrics}:
            registry.register(
                CsvDemoConnector(
                    dataset=dataset,
                    connector_id=connector_id,
                    tenant_id=access.tenant_id,
                    user_id=access.user_id,
                )
            )
        service = DemoChatService(
            domain_registry=self._domains,
            admissibility_engine=self._admissibility,
            query_compiler=self._compiler,
            session_store=EphemeralRunStore(),
            connector_registry=registry,
            ai_model=None,
            synthetic_data=False,
        )
        response = await service.answer(
            DemoChatRequest(
                question=question,
                access_context=access,
                as_of=as_of,
                use_llm=False,
                include_debug=True,
            )
        )
        item.last_response = response
        return response
