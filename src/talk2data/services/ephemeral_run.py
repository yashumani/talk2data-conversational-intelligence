"""A single demo run's evidence. Never writes uploaded data or questions to disk."""

from __future__ import annotations

from uuid import UUID, uuid4

from talk2data.domain.models import AccessContext, BusinessQueryIR, QuestionDecision
from talk2data.services.session_store import SessionAccessDeniedError


class EphemeralRunStore:
    def __init__(self) -> None:
        self.session_id = uuid4()
        self.owner: tuple[str, str] | None = None
        self.question: str | None = None
        self.decision: QuestionDecision | None = None
        self.query_ir: BusinessQueryIR | None = None

    async def create_session(self, context: AccessContext, *, session_id: UUID | None = None) -> UUID:
        self.owner = (context.tenant_id, context.user_id)
        self.session_id = session_id or self.session_id
        return self.session_id

    async def ensure_access(self, session_id: UUID, context: AccessContext) -> None:
        if session_id != self.session_id or self.owner != (context.tenant_id, context.user_id):
            raise SessionAccessDeniedError("Run access denied.")

    async def record_evaluation(
        self,
        *,
        session_id: UUID,
        question: str,
        decision: QuestionDecision,
    ) -> None:
        if session_id != self.session_id:
            raise SessionAccessDeniedError("Run access denied.")
        self.question = question
        self.decision = decision

    async def record_query_plan(self, *, session_id: UUID, query_ir: BusinessQueryIR) -> None:
        if session_id != self.session_id:
            raise SessionAccessDeniedError("Run access denied.")
        self.query_ir = query_ir
