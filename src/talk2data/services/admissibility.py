from __future__ import annotations

import re
from collections.abc import Iterable

from talk2data.domain.models import (
    AuthorizationStatus,
    DataStatus,
    InterpretationResult,
    InterpreterMode,
    QuestionDecision,
    QuestionIntent,
    QuestionRequest,
    QuestionVerdict,
    SourceStatus,
    TenantDomainPack,
)
from talk2data.services.interpreter import CompositeQuestionInterpreter, normalize_text
from talk2data.services.policy import PolicyEngine


class QuestionAdmissibilityEngine:
    """Compiles a natural-language request into a governed question decision."""

    def __init__(self, interpreter: CompositeQuestionInterpreter, policy: PolicyEngine) -> None:
        self._interpreter = interpreter
        self._policy = policy

    async def evaluate(self, request: QuestionRequest, pack: TenantDomainPack) -> QuestionDecision:
        ask_policy = self._policy.can_ask(request.access_context)
        if not ask_policy.allowed:
            return self._decision(
                request=request,
                pack=pack,
                verdict=QuestionVerdict.DENY,
                intent=QuestionIntent.UNKNOWN,
                authorization_status=AuthorizationStatus.DENIED,
                data_status=DataStatus.NOT_REQUIRED,
                reason_codes=ask_policy.reason_codes,
                user_message="You are not authorized to use this Talk2Data capability.",
                next_action="STOP",
            )

        interpretation = await self._interpreter.interpret(
            request.question,
            pack,
            use_llm=request.use_llm,
        )
        proposal = interpretation.proposal

        invalid_reason = self._invalid_analytic_reason(request.question, proposal.requested_operation)
        if invalid_reason is not None:
            return self._decision_from_interpretation(
                request=request,
                pack=pack,
                interpretation=interpretation,
                verdict=QuestionVerdict.INVALID_ANALYTIC_REQUEST,
                authorization_status=AuthorizationStatus.ALLOWED,
                data_status=DataStatus.NOT_REQUIRED,
                reason_codes=[invalid_reason],
                user_message=(
                    "The requested calculation is not analytically valid under the governed metric "
                    "rules. Reformulate the question using an approved aggregation or comparison."
                ),
                next_action="CLARIFY_ANALYTIC_OPERATION",
            )

        if proposal.ambiguous_terms:
            return self._decision_from_interpretation(
                request=request,
                pack=pack,
                interpretation=interpretation,
                verdict=QuestionVerdict.CLARIFY,
                authorization_status=AuthorizationStatus.ALLOWED,
                data_status=DataStatus.NOT_REQUIRED,
                reason_codes=["AMBIGUOUS_BUSINESS_TERMS"],
                user_message=(
                    "The question contains business terms with more than one governed meaning: "
                    + ", ".join(proposal.ambiguous_terms)
                    + "."
                ),
                next_action="REQUEST_TARGETED_CLARIFICATION",
            )

        metric_map = {metric.id: metric for metric in pack.metrics}
        entity_map = {entity.id: entity for entity in pack.entities}
        domain_map = {domain.id: domain for domain in pack.domains}
        metrics = [metric_map[value] for value in proposal.candidate_metric_ids]
        entities = [entity_map[value] for value in proposal.candidate_entity_ids]
        domains = [domain_map[value] for value in proposal.candidate_domain_ids]

        anchors = self._anchor_ids(
            proposal.candidate_metric_ids,
            proposal.candidate_entity_ids,
            proposal.candidate_domain_ids,
        )

        if not anchors:
            if interpretation.matched_exclusion_ids:
                exclusions = [
                    exclusion
                    for exclusion in pack.excluded_domains
                    if exclusion.id in interpretation.matched_exclusion_ids
                ]
                explanation = exclusions[0].explanation if exclusions else "No business anchor exists."
                return self._decision_from_interpretation(
                    request=request,
                    pack=pack,
                    interpretation=interpretation,
                    verdict=QuestionVerdict.OUT_OF_DOMAIN,
                    authorization_status=AuthorizationStatus.ALLOWED,
                    data_status=DataStatus.NOT_REQUIRED,
                    reason_codes=["EXPLICIT_DOMAIN_EXCLUSION", "NO_INTERNAL_DOMAIN_ANCHOR"],
                    user_message=explanation,
                    next_action="STOP_OR_REPHRASE_WITH_INTERNAL_BUSINESS_ANCHOR",
                )

            return self._decision_from_interpretation(
                request=request,
                pack=pack,
                interpretation=interpretation,
                verdict=QuestionVerdict.OUT_OF_DOMAIN,
                authorization_status=AuthorizationStatus.ALLOWED,
                data_status=DataStatus.NOT_REQUIRED,
                reason_codes=["NO_INTERNAL_DOMAIN_ANCHOR"],
                user_message=(
                    f"This Talk2Data environment is configured for {pack.industry} and could not "
                    "map the question to an approved business metric, entity, process, or domain."
                ),
                next_action="STOP_OR_REPHRASE_WITH_INTERNAL_BUSINESS_ANCHOR",
            )

        classification_decisions = [
            self._policy.can_access_classification(request.access_context, item.classification)
            for item in [*metrics, *entities, *domains]
        ]
        denied_classifications = [decision for decision in classification_decisions if not decision.allowed]
        if denied_classifications:
            reason_codes = [code for decision in denied_classifications for code in decision.reason_codes]
            return self._decision_from_interpretation(
                request=request,
                pack=pack,
                interpretation=interpretation,
                verdict=QuestionVerdict.DENY,
                authorization_status=AuthorizationStatus.DENIED,
                data_status=DataStatus.NOT_REQUIRED,
                reason_codes=[*reason_codes, "RESOURCE_CLASSIFICATION_DENIED"],
                user_message="You are not authorized to access the requested business scope.",
                next_action="STOP",
            )

        external_ids = self._valid_external_adjacencies(
            pack=pack,
            interpretation=interpretation,
            metric_ids=set(proposal.candidate_metric_ids),
            entity_ids=set(proposal.candidate_entity_ids),
        )
        if external_ids:
            external_policy = self._policy.can_use_external_context(request.access_context)
            if not external_policy.allowed:
                return self._decision_from_interpretation(
                    request=request,
                    pack=pack,
                    interpretation=interpretation,
                    verdict=QuestionVerdict.DENY,
                    authorization_status=AuthorizationStatus.DENIED,
                    data_status=DataStatus.NOT_REQUIRED,
                    reason_codes=external_policy.reason_codes,
                    user_message="You are not authorized to use external context for this analysis.",
                    next_action="STOP",
                )

        if metrics:
            data_policy = self._policy.can_read_data(request.access_context)
            if not data_policy.allowed:
                return self._decision_from_interpretation(
                    request=request,
                    pack=pack,
                    interpretation=interpretation,
                    verdict=QuestionVerdict.DENY,
                    authorization_status=AuthorizationStatus.DENIED,
                    data_status=DataStatus.NOT_REQUIRED,
                    reason_codes=data_policy.reason_codes,
                    user_message="You are not authorized to query the requested data scope.",
                    next_action="STOP",
                )

            statuses = {metric.source.status for metric in metrics}
            if SourceStatus.NOT_READY in statuses:
                return self._decision_from_interpretation(
                    request=request,
                    pack=pack,
                    interpretation=interpretation,
                    verdict=QuestionVerdict.SOURCE_NOT_READY,
                    authorization_status=AuthorizationStatus.ALLOWED,
                    data_status=DataStatus.NOT_READY,
                    reason_codes=["GOVERNED_SOURCE_NOT_READY"],
                    user_message=(
                        "The question is valid, but at least one governed source is not ready for a "
                        "certified answer."
                    ),
                    next_action="WAIT_FOR_SOURCE_OR_SELECT_LAST_CERTIFIED_PERIOD",
                )
            if SourceStatus.UNAVAILABLE in statuses:
                return self._decision_from_interpretation(
                    request=request,
                    pack=pack,
                    interpretation=interpretation,
                    verdict=QuestionVerdict.VALID_NO_SOURCE,
                    authorization_status=AuthorizationStatus.ALLOWED,
                    data_status=DataStatus.NOT_CONNECTED,
                    reason_codes=["VALID_BUSINESS_QUESTION", "NO_CONNECTED_GOVERNED_SOURCE"],
                    user_message=(
                        "The question is valid for this business, but no governed source is currently "
                        "connected for the requested metric."
                    ),
                    next_action="REGISTER_OR_CONNECT_GOVERNED_SOURCE",
                )

        if external_ids:
            return self._decision_from_interpretation(
                request=request,
                pack=pack,
                interpretation=interpretation,
                verdict=QuestionVerdict.ACCEPT_EXTERNAL_AUGMENTED,
                authorization_status=AuthorizationStatus.ALLOWED,
                data_status=DataStatus.AVAILABLE if metrics else DataStatus.PARTIALLY_AVAILABLE,
                reason_codes=[
                    "INTERNAL_DOMAIN_ANCHOR_FOUND",
                    "APPROVED_EXTERNAL_ADJACENCY_FOUND",
                    *[f"EXTERNAL_ADJACENCY_{value}" for value in external_ids],
                ],
                user_message=(
                    "The question has an approved internal business anchor and may use governed "
                    "external context as supporting evidence."
                ),
                next_action="BUILD_INTERNAL_FIRST_INVESTIGATION_PLAN",
            )

        if metrics:
            return self._decision_from_interpretation(
                request=request,
                pack=pack,
                interpretation=interpretation,
                verdict=QuestionVerdict.ACCEPT_INTERNAL,
                authorization_status=AuthorizationStatus.ALLOWED,
                data_status=DataStatus.AVAILABLE,
                reason_codes=["INTERNAL_DOMAIN_ANCHOR_FOUND", "GOVERNED_SOURCE_AVAILABLE"],
                user_message="The question is valid and can proceed to governed internal-data planning.",
                next_action="BUILD_CERTIFIED_DATA_QUERY_PLAN",
            )

        memory_policy = self._policy.can_read_memory(request.access_context)
        if not memory_policy.allowed:
            return self._decision_from_interpretation(
                request=request,
                pack=pack,
                interpretation=interpretation,
                verdict=QuestionVerdict.DENY,
                authorization_status=AuthorizationStatus.DENIED,
                data_status=DataStatus.NOT_REQUIRED,
                reason_codes=memory_policy.reason_codes,
                user_message="You are not authorized to retrieve organizational knowledge.",
                next_action="STOP",
            )

        return self._decision_from_interpretation(
            request=request,
            pack=pack,
            interpretation=interpretation,
            verdict=QuestionVerdict.ACCEPT_KNOWLEDGE,
            authorization_status=AuthorizationStatus.ALLOWED,
            data_status=DataStatus.NOT_REQUIRED,
            reason_codes=["INTERNAL_DOMAIN_ANCHOR_FOUND", "KNOWLEDGE_RETRIEVAL_ALLOWED"],
            user_message="The question is valid and can proceed to governed knowledge retrieval.",
            next_action="BUILD_AUTHORIZED_MEMORY_RETRIEVAL_PLAN",
        )

    @staticmethod
    def _invalid_analytic_reason(question: str, requested_operation: str | None) -> str | None:
        normalized = normalize_text(question)
        invalid_patterns = [
            r"\bsum\s+(?:of\s+)?(?:the\s+)?(?:churn|conversion|rate|percentages?)\b",
            r"\badd\s+(?:the\s+)?(?:churn|conversion|rates?|percentages?)\b",
            r"\baverage\s+(?:of\s+)?percentages?\b",
        ]
        if any(re.search(pattern, normalized) for pattern in invalid_patterns):
            return "INVALID_NON_ADDITIVE_METRIC_AGGREGATION"
        if requested_operation == "SUM" and any(
            term in normalized for term in ("churn", "conversion", "rate", "percentage")
        ):
            return "INVALID_NON_ADDITIVE_METRIC_AGGREGATION"
        return None

    @staticmethod
    def _anchor_ids(*groups: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for group in groups:
            for value in group:
                if value not in seen:
                    seen.add(value)
                    result.append(value)
        return result

    @staticmethod
    def _valid_external_adjacencies(
        *,
        pack: TenantDomainPack,
        interpretation: InterpretationResult,
        metric_ids: set[str],
        entity_ids: set[str],
    ) -> list[str]:
        valid: list[str] = []
        matched = set(interpretation.matched_external_adjacency_ids)
        for adjacency in pack.external_adjacencies:
            if adjacency.id not in matched:
                continue
            metric_anchor = bool(metric_ids.intersection(adjacency.anchor_metric_ids))
            entity_anchor = bool(entity_ids.intersection(adjacency.anchor_entity_ids))
            if metric_anchor or entity_anchor:
                valid.append(adjacency.id)
        return valid

    def _decision_from_interpretation(
        self,
        *,
        request: QuestionRequest,
        pack: TenantDomainPack,
        interpretation: InterpretationResult,
        verdict: QuestionVerdict,
        authorization_status: AuthorizationStatus,
        data_status: DataStatus,
        reason_codes: list[str],
        user_message: str,
        next_action: str,
    ) -> QuestionDecision:
        return self._decision(
            request=request,
            pack=pack,
            verdict=verdict,
            intent=interpretation.proposal.intent,
            authorization_status=authorization_status,
            data_status=data_status,
            reason_codes=reason_codes,
            user_message=user_message,
            next_action=next_action,
            interpretation=interpretation,
        )

    @staticmethod
    def _decision(
        *,
        request: QuestionRequest,
        pack: TenantDomainPack,
        verdict: QuestionVerdict,
        intent: QuestionIntent,
        authorization_status: AuthorizationStatus,
        data_status: DataStatus,
        reason_codes: list[str],
        user_message: str,
        next_action: str,
        interpretation: InterpretationResult | None = None,
    ) -> QuestionDecision:
        proposal = interpretation.proposal if interpretation is not None else None
        anchors = (
            QuestionAdmissibilityEngine._anchor_ids(
                proposal.candidate_metric_ids,
                proposal.candidate_entity_ids,
                proposal.candidate_domain_ids,
            )
            if proposal is not None
            else []
        )
        return QuestionDecision(
            tenant_id=request.access_context.tenant_id,
            user_id=request.access_context.user_id,
            verdict=verdict,
            recognized_intent=intent,
            domain_anchor_ids=anchors,
            candidate_metric_ids=proposal.candidate_metric_ids if proposal else [],
            candidate_entity_ids=proposal.candidate_entity_ids if proposal else [],
            candidate_dimension_ids=proposal.candidate_dimensions if proposal else [],
            external_topics=proposal.external_topics if proposal else [],
            unresolved_terms=proposal.ambiguous_terms if proposal else [],
            authorization_status=authorization_status,
            data_status=data_status,
            reason_codes=reason_codes,
            user_message=user_message,
            next_action=next_action,
            domain_pack_version=pack.version,
            interpreter_mode=interpretation.mode if interpretation else InterpreterMode.RULES,
            warnings=interpretation.warnings if interpretation else [],
        )
