from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

import httpx

from talk2data.domain.models import (
    InterpretationProposal,
    InterpretationResult,
    InterpreterMode,
    QuestionIntent,
    TenantDomainPack,
)


class InterpretationError(RuntimeError):
    """Raised when a language interpretation provider cannot return a valid proposal."""


def normalize_text(value: str) -> str:
    normalized = value.casefold().replace("–", "-").replace("—", "-")
    normalized = re.sub(r"[^a-z0-9%_-]+", " ", normalized)
    return " ".join(normalized.split())


def phrase_present(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = normalize_text(phrase)
    if not normalized_phrase:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(normalized_phrase).replace(r"\ ", r"\s+")
    pattern += r"(?![a-z0-9])"
    return re.search(pattern, normalized_text) is not None


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


@dataclass(frozen=True)
class OllamaConfiguration:
    base_url: str
    model: str
    timeout_seconds: float


class HeuristicQuestionInterpreter:
    """Deterministic first-pass interpreter driven only by the Tenant Domain Pack."""

    def interpret(self, question: str, pack: TenantDomainPack) -> InterpretationResult:
        normalized = normalize_text(question)
        metric_ids: list[str] = []
        entity_ids: list[str] = []
        domain_ids: list[str] = []
        dimensions: list[str] = []
        matched_terms: list[str] = []

        for metric in pack.metrics:
            phrases = [metric.name, metric.id.replace("_", " "), *metric.aliases]
            matched = next((phrase for phrase in phrases if phrase_present(normalized, phrase)), None)
            if matched is not None:
                metric_ids.append(metric.id)
                domain_ids.append(metric.domain_id)
                matched_terms.append(matched)

        for entity in pack.entities:
            phrases = [entity.name, entity.id.replace("_", " "), *entity.aliases]
            matched = next((phrase for phrase in phrases if phrase_present(normalized, phrase)), None)
            if matched is not None:
                entity_ids.append(entity.id)
                domain_ids.append(entity.domain_id)
                matched_terms.append(matched)
                if phrase_present(normalized, f"by {matched}"):
                    dimensions.append(entity.id)

        for domain in pack.domains:
            phrases = [domain.name, domain.id.replace("_", " "), *domain.aliases]
            matched = next((phrase for phrase in phrases if phrase_present(normalized, phrase)), None)
            if matched is not None:
                domain_ids.append(domain.id)
                matched_terms.append(matched)

        matched_external_ids: list[str] = []
        external_topics: list[str] = []
        for adjacency in pack.external_adjacencies:
            if any(phrase_present(normalized, phrase) for phrase in adjacency.phrases):
                matched_external_ids.append(adjacency.id)
                external_topics.append(adjacency.name)

        matched_exclusion_ids: list[str] = []
        for exclusion in pack.excluded_domains:
            if any(phrase_present(normalized, phrase) for phrase in exclusion.phrases):
                matched_exclusion_ids.append(exclusion.id)

        intent = self._infer_intent(normalized, bool(metric_ids), bool(entity_ids or domain_ids))
        proposal = InterpretationProposal(
            intent=intent,
            candidate_metric_ids=unique_preserving_order(metric_ids),
            candidate_entity_ids=unique_preserving_order(entity_ids),
            candidate_domain_ids=unique_preserving_order(domain_ids),
            candidate_dimensions=unique_preserving_order(dimensions),
            external_topics=unique_preserving_order(external_topics),
            requested_operation=self._infer_operation(normalized),
            summary="Deterministic Domain Pack interpretation.",
            confidence=0.9 if metric_ids or entity_ids or domain_ids else 0.25,
        )
        return InterpretationResult(
            proposal=proposal,
            mode=InterpreterMode.RULES,
            matched_external_adjacency_ids=matched_external_ids,
            matched_exclusion_ids=matched_exclusion_ids,
            matched_terms=unique_preserving_order(matched_terms),
        )

    @staticmethod
    def _infer_intent(normalized: str, has_metric: bool, has_business_anchor: bool) -> QuestionIntent:
        if any(token in normalized for token in ("why ", "what caused", "driver", "contribute")):
            return QuestionIntent.DRIVER_ANALYSIS
        if any(token in normalized for token in ("compare", " versus ", " vs ", "difference")):
            return QuestionIntent.COMPARISON
        if any(token in normalized for token in ("trend", "over time", "changed", "change over")):
            return QuestionIntent.TREND_ANALYSIS
        if has_metric:
            return QuestionIntent.METRIC_LOOKUP
        if has_business_anchor:
            return QuestionIntent.KNOWLEDGE_LOOKUP
        return QuestionIntent.UNKNOWN

    @staticmethod
    def _infer_operation(normalized: str) -> str | None:
        if "sum of" in normalized or normalized.startswith("sum "):
            return "SUM"
        if "average of" in normalized or normalized.startswith("average "):
            return "AVERAGE"
        if "compare" in normalized or " versus " in normalized or " vs " in normalized:
            return "COMPARE"
        if "why " in normalized or "what caused" in normalized or "contribute" in normalized:
            return "EXPLAIN_DRIVERS"
        return None


class OllamaQuestionInterpreter:
    """Local structured-output interpreter. Its proposal is always treated as untrusted."""

    def __init__(self, configuration: OllamaConfiguration) -> None:
        self._configuration = configuration

    async def interpret(self, question: str, pack: TenantDomainPack) -> InterpretationProposal:
        prompt = self._build_prompt(question, pack)
        payload = {
            "model": self._configuration.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a business-question parser. Do not answer the question. "
                        "Return only a structured interpretation matching the supplied JSON schema. "
                        "Use only exact governed IDs supplied in the tenant catalog; otherwise return "
                        "an empty list. Never invent a metric, entity, dimension, or domain ID."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": InterpretationProposal.model_json_schema(),
            "options": {"temperature": 0, "seed": 17},
        }
        try:
            async with httpx.AsyncClient(timeout=self._configuration.timeout_seconds) as client:
                response = await client.post(
                    f"{self._configuration.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise InterpretationError(f"Ollama request failed: {exc}") from exc

        try:
            body = response.json()
            content = body["message"]["content"]
            return InterpretationProposal.model_validate_json(content)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InterpretationError("Ollama returned an invalid structured interpretation") from exc

    async def health(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=min(self._configuration.timeout_seconds, 10.0)) as client:
                response = await client.get(f"{self._configuration.base_url}/api/tags")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return False, f"Ollama is unavailable: {exc}"
        return True, "Ollama is reachable."

    @staticmethod
    def _build_prompt(question: str, pack: TenantDomainPack) -> str:
        catalog = {
            "tenant": {
                "tenant_id": pack.tenant_id,
                "industry": pack.industry,
                "subindustries": pack.subindustries,
            },
            "domains": [
                {"id": domain.id, "name": domain.name, "aliases": domain.aliases}
                for domain in pack.domains
            ],
            "metrics": [
                {
                    "id": metric.id,
                    "name": metric.name,
                    "aliases": metric.aliases,
                    "allowed_dimensions": metric.allowed_dimensions,
                }
                for metric in pack.metrics
            ],
            "entities": [
                {"id": entity.id, "name": entity.name, "aliases": entity.aliases}
                for entity in pack.entities
            ],
            "approved_external_topics": [
                {"id": adjacency.id, "name": adjacency.name, "phrases": adjacency.phrases}
                for adjacency in pack.external_adjacencies
            ],
        }
        schema = InterpretationProposal.model_json_schema()
        return (
            f"Tenant catalog:\n{json.dumps(catalog, sort_keys=True)}\n\n"
            f"Required JSON schema:\n{json.dumps(schema, sort_keys=True)}\n\n"
            f"User question:\n{question}"
        )


class CompositeQuestionInterpreter:
    """Combines local-model interpretation with deterministic Domain Pack matching."""

    def __init__(
        self,
        heuristic: HeuristicQuestionInterpreter,
        ollama: OllamaQuestionInterpreter | None,
        *,
        ollama_required: bool = False,
    ) -> None:
        self._heuristic = heuristic
        self._ollama = ollama
        self._ollama_required = ollama_required

    async def interpret(
        self,
        question: str,
        pack: TenantDomainPack,
        *,
        use_llm: bool,
    ) -> InterpretationResult:
        deterministic = self._heuristic.interpret(question, pack)
        if not use_llm or self._ollama is None:
            return deterministic

        try:
            proposed = await self._ollama.interpret(question, pack)
        except InterpretationError as exc:
            if self._ollama_required:
                raise
            return deterministic.model_copy(
                update={
                    "mode": InterpreterMode.OLLAMA_FAILED_RULES_FALLBACK,
                    "warnings": [str(exc)],
                }
            )

        valid_metric_ids = {metric.id for metric in pack.metrics}
        valid_entity_ids = {entity.id for entity in pack.entities}
        valid_domain_ids = {domain.id for domain in pack.domains}
        valid_dimension_ids = valid_entity_ids

        filtered_metric_ids = [
            value.upper() for value in proposed.candidate_metric_ids if value.upper() in valid_metric_ids
        ]
        filtered_entity_ids = [
            value.upper() for value in proposed.candidate_entity_ids if value.upper() in valid_entity_ids
        ]
        filtered_domain_ids = [
            value.upper() for value in proposed.candidate_domain_ids if value.upper() in valid_domain_ids
        ]
        filtered_dimensions = [
            value.upper() for value in proposed.candidate_dimensions if value.upper() in valid_dimension_ids
        ]

        warnings = list(deterministic.warnings)
        rejected_ids = (
            set(value.upper() for value in proposed.candidate_metric_ids) - valid_metric_ids
        ) | (set(value.upper() for value in proposed.candidate_entity_ids) - valid_entity_ids) | (
            set(value.upper() for value in proposed.candidate_domain_ids) - valid_domain_ids
        )
        if rejected_ids:
            warnings.append("Rejected ungoverned model identifiers: " + ", ".join(sorted(rejected_ids)))

        deterministic_proposal = deterministic.proposal
        merged = InterpretationProposal(
            intent=(
                proposed.intent
                if proposed.intent != QuestionIntent.UNKNOWN
                else deterministic_proposal.intent
            ),
            candidate_metric_ids=unique_preserving_order(
                [*deterministic_proposal.candidate_metric_ids, *filtered_metric_ids]
            ),
            candidate_entity_ids=unique_preserving_order(
                [*deterministic_proposal.candidate_entity_ids, *filtered_entity_ids]
            ),
            candidate_domain_ids=unique_preserving_order(
                [*deterministic_proposal.candidate_domain_ids, *filtered_domain_ids]
            ),
            candidate_dimensions=unique_preserving_order(
                [*deterministic_proposal.candidate_dimensions, *filtered_dimensions]
            ),
            external_topics=deterministic_proposal.external_topics,
            ambiguous_terms=unique_preserving_order(proposed.ambiguous_terms),
            requested_operation=proposed.requested_operation
            or deterministic_proposal.requested_operation,
            summary=proposed.summary,
            confidence=max(deterministic_proposal.confidence, proposed.confidence),
        )
        return InterpretationResult(
            proposal=merged,
            mode=InterpreterMode.OLLAMA_AND_RULES,
            matched_external_adjacency_ids=deterministic.matched_external_adjacency_ids,
            matched_exclusion_ids=deterministic.matched_exclusion_ids,
            matched_terms=deterministic.matched_terms,
            warnings=warnings,
        )
