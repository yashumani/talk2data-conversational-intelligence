from __future__ import annotations

from typing import Protocol
from uuid import UUID

from talk2data.domain.models import AccessContext, BusinessQueryIR, QuestionDecision


class ChatSessionStore(Protocol):
    async def create_session(self, context: AccessContext, *, session_id: UUID | None = None) -> UUID: ...

    async def ensure_access(self, session_id: UUID, context: AccessContext) -> None: ...

    async def record_evaluation(
        self,
        *,
        session_id: UUID,
        question: str,
        decision: QuestionDecision,
    ) -> None: ...

    async def record_query_plan(self, *, session_id: UUID, query_ir: BusinessQueryIR) -> None: ...
