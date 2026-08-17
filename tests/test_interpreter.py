from __future__ import annotations

import pytest

from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import InterpretationProposal, QuestionIntent
from talk2data.services.interpreter import (
    CompositeQuestionInterpreter,
    HeuristicQuestionInterpreter,
)


class InventingOllamaInterpreter:
    async def interpret(self, question: str, pack: object) -> InterpretationProposal:
        del question, pack
        return InterpretationProposal(
            intent=QuestionIntent.METRIC_LOOKUP,
            candidate_metric_ids=["RESTAURANT_FOOD_MARGIN"],
            candidate_entity_ids=["KITCHEN"],
            candidate_domain_ids=["FOOD_BUSINESS"],
            summary="Invented identifiers must not pass validation.",
            confidence=1.0,
        )


@pytest.mark.asyncio
async def test_composite_interpreter_rejects_model_invented_identifiers() -> None:
    registry = DomainPackRegistry()
    registry.load()
    pack = registry.get("demo-telecom")
    interpreter = CompositeQuestionInterpreter(
        HeuristicQuestionInterpreter(),
        InventingOllamaInterpreter(),  # type: ignore[arg-type]
    )

    result = await interpreter.interpret(
        "What is restaurant food margin?",
        pack,
        use_llm=True,
    )

    assert result.proposal.candidate_metric_ids == []
    assert result.proposal.candidate_entity_ids == []
    assert result.proposal.candidate_domain_ids == []
    assert any("RESTAURANT_FOOD_MARGIN" in warning for warning in result.warnings)
