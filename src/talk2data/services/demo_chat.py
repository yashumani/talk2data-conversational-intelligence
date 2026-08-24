from __future__ import annotations

from uuid import UUID

from talk2data.connectors.base import StructuredQueryPlan
from talk2data.connectors.demo_sqlite import (
    DemoConnectorValidationError,
    DemoSourceNotReadyError,
)
from talk2data.connectors.postgres import (
    PostgreSQLConnectorError,
    PostgreSQLSourceNotReadyError,
)
from talk2data.connectors.registry import ConnectorRegistry, ConnectorRegistryError
from talk2data.domain.chat import (
    ChatStatus,
    DemoChatRequest,
    DemoChatResponse,
    VerificationStatus,
)
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import (
    BusinessQueryIR,
    InterpreterMode,
    QueryCompilationStatus,
    QuestionDecision,
    QuestionRequest,
    QuestionVerdict,
)
from talk2data.services.admissibility import QuestionAdmissibilityEngine
from talk2data.services.certification import CertifiedAnswerComposer, ResultSenseValidator
from talk2data.services.query_compiler import BusinessQueryCompiler
from talk2data.services.session_store import SQLiteSessionStore


class DemoChatService:
    """Runs the governed chat path from question to verified, receipt-backed answer."""

    def __init__(
        self,
        *,
        domain_registry: DomainPackRegistry,
        admissibility_engine: QuestionAdmissibilityEngine,
        query_compiler: BusinessQueryCompiler,
        session_store: SQLiteSessionStore,
        connector_registry: ConnectorRegistry,
        ai_model: str | None,
        synthetic_data: bool,
    ) -> None:
        self._domain_registry = domain_registry
        self._admissibility_engine = admissibility_engine
        self._query_compiler = query_compiler
        self._session_store = session_store
        self._connector_registry = connector_registry
        self._ai_model = ai_model
        self._synthetic_data = synthetic_data
        self._validator = ResultSenseValidator()
        self._composer = CertifiedAnswerComposer()

    async def answer(self, request: DemoChatRequest) -> DemoChatResponse:
        pack = self._domain_registry.get(request.access_context.tenant_id)
        session_id = await self._resolve_session(request)
        question_request = QuestionRequest.model_validate(
            request.model_dump(exclude={"as_of", "include_debug"})
        )
        decision = await self._admissibility_engine.evaluate(question_request, pack)
        await self._session_store.record_evaluation(
            session_id=session_id,
            question=request.question,
            decision=decision,
        )

        early_status = status_for_verdict(decision.verdict)
        if early_status is not None:
            return self._non_answer_response(
                session_id=session_id,
                decision=decision,
                status=early_status,
                message=decision.user_message,
            )

        compilation = self._query_compiler.compile(
            request=request,
            decision=decision,
            session_id=session_id,
        )
        if compilation.query_ir is None:
            status = (
                ChatStatus.CLARIFICATION_REQUIRED
                if compilation.status == QueryCompilationStatus.CLARIFICATION_REQUIRED
                else ChatStatus.INVALID
            )
            issue_message = (
                compilation.issues[0].message
                if compilation.issues
                else "The question could not be compiled into a governed data request."
            )
            return self._non_answer_response(
                session_id=session_id,
                decision=decision,
                status=status,
                message=issue_message,
                compilation_status=compilation.status,
                warnings=compilation.warnings,
            )

        query_ir = compilation.query_ir
        await self._session_store.record_query_plan(session_id=session_id, query_ir=query_ir)
        if query_ir.requires_external_context:
            return self._non_answer_response(
                session_id=session_id,
                decision=decision,
                status=ChatStatus.CONTEXT_NOT_CONNECTED,
                message=(
                    "The internal metric is recognized, but this question asks for external or "
                    "organizational context. That evidence service is not connected yet."
                ),
                compilation_status=compilation.status,
                query_ir=query_ir if request.include_debug else None,
                warnings=compilation.warnings,
            )

        plan = StructuredQueryPlan(
            query_id=query_ir.query_id,
            decision_id=query_ir.decision_id,
            plan_hash=query_ir.plan_hash,
            tenant_id=query_ir.tenant_id,
            connector_id=query_ir.source_connector_id,
            metric_id=query_ir.metric_id,
            semantic_version=query_ir.semantic_version,
            value_type=query_ir.value_type,
            aggregation=query_ir.aggregation,
            unit=query_ir.unit,
            currency=query_ir.currency,
            dimensions=query_ir.dimensions,
            filters=query_ir.filters,
            time_window=query_ir.time_window,
            comparison=query_ir.comparison,
            row_limit=100,
        )
        try:
            connector = self._connector_registry.get(plan.connector_id)
            receipt = await connector.execute_read_only(plan, request.access_context)
        except (DemoSourceNotReadyError, PostgreSQLSourceNotReadyError) as exc:
            return self._non_answer_response(
                session_id=session_id,
                decision=decision,
                status=ChatStatus.SOURCE_NOT_READY,
                message=str(exc),
                compilation_status=compilation.status,
                query_ir=query_ir if request.include_debug else None,
                warnings=compilation.warnings,
            )
        except (
            ConnectorRegistryError,
            DemoConnectorValidationError,
            PostgreSQLConnectorError,
        ) as exc:
            return self._non_answer_response(
                session_id=session_id,
                decision=decision,
                status=ChatStatus.INVALID,
                message=f"The governed connector rejected this request: {exc}",
                compilation_status=compilation.status,
                query_ir=query_ir if request.include_debug else None,
                warnings=compilation.warnings,
            )

        metric = next(item for item in pack.metrics if item.id == query_ir.metric_id)
        receipt, verification = self._validator.validate(
            metric=metric,
            query_ir=query_ir,
            receipt=receipt,
        )
        if verification.status != VerificationStatus.VERIFIED:
            return DemoChatResponse(
                status=ChatStatus.VERIFICATION_FAILED,
                session_id=session_id,
                message="The result failed certification and no numeric answer was released.",
                decision=decision,
                compilation_status=compilation.status,
                query_ir=query_ir if request.include_debug else None,
                receipt=receipt if request.include_debug else None,
                verification=verification,
                ai_model=self._resolved_ai_model(decision.interpreter_mode),
                synthetic_data=self._synthetic_data,
                warnings=[*compilation.warnings, *receipt.warnings],
            )

        answer = self._composer.compose(
            pack=pack,
            metric=metric,
            query_ir=query_ir,
            receipt=receipt,
        )
        return DemoChatResponse(
            status=ChatStatus.ANSWERED,
            session_id=session_id,
            message=answer.text,
            decision=decision,
            compilation_status=compilation.status,
            query_ir=query_ir if request.include_debug else None,
            receipt=receipt if request.include_debug else None,
            verification=verification,
            answer=answer,
            ai_model=self._resolved_ai_model(decision.interpreter_mode),
            synthetic_data=self._synthetic_data,
            warnings=[*compilation.warnings, *receipt.warnings],
        )

    async def _resolve_session(self, request: DemoChatRequest) -> UUID:
        if request.session_id is None:
            return await self._session_store.create_session(request.access_context)
        await self._session_store.ensure_access(request.session_id, request.access_context)
        return request.session_id

    def _non_answer_response(
        self,
        *,
        session_id: UUID,
        decision: QuestionDecision,
        status: ChatStatus,
        message: str,
        compilation_status: QueryCompilationStatus | None = None,
        query_ir: BusinessQueryIR | None = None,
        warnings: list[str] | None = None,
    ) -> DemoChatResponse:
        return DemoChatResponse(
            status=status,
            session_id=session_id,
            message=message,
            decision=decision,
            compilation_status=compilation_status,
            query_ir=query_ir,
            ai_model=self._resolved_ai_model(decision.interpreter_mode),
            synthetic_data=self._synthetic_data,
            warnings=warnings or [],
        )

    def _resolved_ai_model(self, mode: InterpreterMode) -> str | None:
        return None if mode == InterpreterMode.RULES else self._ai_model


def status_for_verdict(verdict: QuestionVerdict) -> ChatStatus | None:
    mapping: dict[QuestionVerdict, ChatStatus | None] = {
        QuestionVerdict.ACCEPT_KNOWLEDGE: ChatStatus.CONTEXT_NOT_CONNECTED,
        QuestionVerdict.ACCEPT_EXTERNAL_AUGMENTED: None,
        QuestionVerdict.CLARIFY: ChatStatus.CLARIFICATION_REQUIRED,
        QuestionVerdict.VALID_NO_SOURCE: ChatStatus.NO_SOURCE,
        QuestionVerdict.OUT_OF_DOMAIN: ChatStatus.OUT_OF_DOMAIN,
        QuestionVerdict.INVALID_ANALYTIC_REQUEST: ChatStatus.INVALID,
        QuestionVerdict.DENY: ChatStatus.DENIED,
        QuestionVerdict.CONFLICTING_DEFINITIONS: ChatStatus.CLARIFICATION_REQUIRED,
        QuestionVerdict.SOURCE_NOT_READY: ChatStatus.SOURCE_NOT_READY,
        QuestionVerdict.ACCEPT_INTERNAL: None,
    }
    return mapping[verdict]
