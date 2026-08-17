from __future__ import annotations

from dataclasses import dataclass

from talk2data.domain.models import (
    CLASSIFICATION_RANK,
    AccessContext,
    AuthorizationStatus,
    ClassificationLevel,
)

ASK_ACTION = "ASK_BUSINESS_QUESTIONS"
READ_DATA_ACTION = "READ_AGGREGATED_DATA"
READ_MEMORY_ACTION = "READ_APPROVED_MEMORY"
USE_EXTERNAL_ACTION = "USE_EXTERNAL_CONTEXT"
ADMIN_ROLE = "TALK2DATA_ADMIN"


@dataclass(frozen=True)
class PolicyDecision:
    status: AuthorizationStatus
    reason_codes: list[str]

    @property
    def allowed(self) -> bool:
        return self.status == AuthorizationStatus.ALLOWED


class PolicyEngine:
    """Deterministic authorization checks. Prompts and model output are never policy controls."""

    def can_ask(self, context: AccessContext) -> PolicyDecision:
        if ADMIN_ROLE in context.roles or ASK_ACTION in context.permitted_actions:
            return PolicyDecision(AuthorizationStatus.ALLOWED, ["QUESTION_ACTION_ALLOWED"])
        return PolicyDecision(AuthorizationStatus.DENIED, ["QUESTION_ACTION_NOT_ALLOWED"])

    def can_read_data(self, context: AccessContext) -> PolicyDecision:
        if ADMIN_ROLE in context.roles or READ_DATA_ACTION in context.permitted_actions:
            return PolicyDecision(AuthorizationStatus.ALLOWED, ["DATA_ACTION_ALLOWED"])
        return PolicyDecision(AuthorizationStatus.DENIED, ["DATA_ACTION_NOT_ALLOWED"])

    def can_read_memory(self, context: AccessContext) -> PolicyDecision:
        if ADMIN_ROLE in context.roles or READ_MEMORY_ACTION in context.permitted_actions:
            return PolicyDecision(AuthorizationStatus.ALLOWED, ["MEMORY_ACTION_ALLOWED"])
        return PolicyDecision(AuthorizationStatus.DENIED, ["MEMORY_ACTION_NOT_ALLOWED"])

    def can_use_external_context(self, context: AccessContext) -> PolicyDecision:
        if ADMIN_ROLE in context.roles or USE_EXTERNAL_ACTION in context.permitted_actions:
            return PolicyDecision(AuthorizationStatus.ALLOWED, ["EXTERNAL_ACTION_ALLOWED"])
        return PolicyDecision(AuthorizationStatus.DENIED, ["EXTERNAL_ACTION_NOT_ALLOWED"])

    def can_access_classification(
        self,
        context: AccessContext,
        required: ClassificationLevel,
    ) -> PolicyDecision:
        if CLASSIFICATION_RANK[context.classification_clearance] >= CLASSIFICATION_RANK[required]:
            return PolicyDecision(
                AuthorizationStatus.ALLOWED,
                [f"CLASSIFICATION_{required.value}_ALLOWED"],
            )
        return PolicyDecision(
            AuthorizationStatus.DENIED,
            [f"CLASSIFICATION_{required.value}_NOT_ALLOWED"],
        )
