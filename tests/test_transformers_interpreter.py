from __future__ import annotations

import json

import pytest

from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import QuestionIntent
from talk2data.services.interpreter import InterpretationError
from talk2data.services.transformers_interpreter import (
    TransformersConfiguration,
    TransformersQuestionInterpreter,
    extract_first_json_object,
)


def _pack():
    registry = DomainPackRegistry()
    registry.load()
    return registry.get("demo-telecom")


def test_extract_first_json_object_ignores_wrapping_text() -> None:
    payload = extract_first_json_object('Result:\n```json\n{"intent":"UNKNOWN"}\n```')
    assert payload == {"intent": "UNKNOWN"}


@pytest.mark.asyncio
async def test_transformers_interpreter_validates_structured_output() -> None:
    response = {
        "intent": "METRIC_LOOKUP",
        "candidate_metric_ids": ["POSTPAID_CHURN"],
        "candidate_entity_ids": ["PLAN"],
        "candidate_domain_ids": ["WIRELESS_SUBSCRIBER"],
        "candidate_dimensions": ["PLAN"],
        "external_topics": [],
        "ambiguous_terms": [],
        "requested_operation": None,
        "summary": "Postpaid churn by plan.",
        "confidence": 0.96,
    }
    interpreter = TransformersQuestionInterpreter(
        TransformersConfiguration(),
        text_generator=lambda _: json.dumps(response),
    )

    proposal = await interpreter.interpret(
        "What was postpaid churn by plan last month?",
        _pack(),
    )

    assert proposal.intent == QuestionIntent.METRIC_LOOKUP
    assert proposal.candidate_metric_ids == ["POSTPAID_CHURN"]
    assert proposal.candidate_dimensions == ["PLAN"]


@pytest.mark.asyncio
async def test_transformers_interpreter_rejects_malformed_output() -> None:
    interpreter = TransformersQuestionInterpreter(
        TransformersConfiguration(),
        text_generator=lambda _: "not json",
    )

    with pytest.raises(InterpretationError):
        await interpreter.interpret("What was churn last month?", _pack())


@pytest.mark.asyncio
async def test_injected_generator_health_is_ready() -> None:
    interpreter = TransformersQuestionInterpreter(
        TransformersConfiguration(),
        text_generator=lambda _: "{}",
    )
    ready, detail = await interpreter.health()
    assert ready is True
    assert "test generator" in detail


def test_transformers_configuration_rejects_unsafe_values() -> None:
    with pytest.raises(ValueError):
        TransformersConfiguration(model_id="")
    with pytest.raises(ValueError):
        TransformersConfiguration(max_new_tokens=2)
    with pytest.raises(ValueError):
        TransformersConfiguration(device="remote")
