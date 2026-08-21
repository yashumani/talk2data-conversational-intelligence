from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import QuestionIntent
from talk2data.services.interpreter import InterpretationError
from talk2data.services.transformers_interpreter import (
    TransformersConfiguration,
    TransformersQuestionInterpreter,
    extract_first_json_object,
    resolve_device,
)


def _pack():
    registry = DomainPackRegistry()
    registry.load()
    return registry.get("demo-telecom")


def _proposal_payload() -> dict[str, Any]:
    return {
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


def test_extract_first_json_object_ignores_wrapping_text() -> None:
    payload = extract_first_json_object('Result:\n```json\n{"intent":"UNKNOWN"}\n```')
    assert payload == {"intent": "UNKNOWN"}


@pytest.mark.asyncio
async def test_transformers_interpreter_validates_structured_output() -> None:
    interpreter = TransformersQuestionInterpreter(
        TransformersConfiguration(),
        text_generator=lambda _: json.dumps(_proposal_payload()),
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


@pytest.mark.asyncio
async def test_health_reports_missing_host_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    interpreter = TransformersQuestionInterpreter(TransformersConfiguration())

    monkeypatch.setattr(
        "talk2data.services.transformers_interpreter.importlib.util.find_spec",
        lambda name: None if name == "transformers" else object(),
    )
    ready, detail = await interpreter.health()
    assert ready is False
    assert "transformers" in detail

    monkeypatch.setattr(
        "talk2data.services.transformers_interpreter.importlib.util.find_spec",
        lambda name: None if name == "torch" else object(),
    )
    ready, detail = await interpreter.health()
    assert ready is False
    assert "torch" in detail


class _FakeTensor:
    shape = (1, 3)

    def to(self, _: str) -> _FakeTensor:
        return self


class _FakeBatch(dict[str, Any]):
    def to(self, device: str) -> _FakeBatch:
        for value in self.values():
            if hasattr(value, "to"):
                value.to(device)
        return self


class _FakeTokenizer:
    pad_token_id = None
    eos_token_id = 0

    def apply_chat_template(
        self,
        _: list[dict[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> str:
        assert tokenize is False
        assert add_generation_prompt is True
        return "formatted prompt"

    def __call__(self, _: str, *, return_tensors: str) -> _FakeBatch:
        assert return_tensors == "pt"
        return _FakeBatch(input_ids=_FakeTensor())

    def decode(self, tokens: list[int], *, skip_special_tokens: bool) -> str:
        assert tokens == [13, 14]
        assert skip_special_tokens is True
        return json.dumps(_proposal_payload())


class _FakeModel:
    def __init__(self) -> None:
        self.device = ""
        self.eval_called = False

    def to(self, device: str) -> _FakeModel:
        self.device = device
        return self

    def eval(self) -> None:
        self.eval_called = True

    def generate(self, **kwargs: Any) -> list[list[int]]:
        assert kwargs["max_new_tokens"] == 192
        assert kwargs["do_sample"] is False
        assert kwargs["use_cache"] is True
        assert kwargs["pad_token_id"] == 0
        return [[10, 11, 12, 13, 14]]


@pytest.mark.asyncio
async def test_real_provider_path_can_load_and_generate_with_framework_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = _FakeTokenizer()
    model = _FakeModel()
    transformers = SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=lambda *args, **kwargs: tokenizer),
        AutoModelForCausalLM=SimpleNamespace(from_pretrained=lambda *args, **kwargs: model),
    )
    torch = SimpleNamespace(
        float32="float32",
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
        inference_mode=nullcontext,
    )

    def import_module(name: str) -> Any:
        if name == "transformers":
            return transformers
        if name == "torch":
            return torch
        raise ImportError(name)

    monkeypatch.setattr(
        "talk2data.services.transformers_interpreter.importlib.import_module",
        import_module,
    )
    monkeypatch.setattr(
        "talk2data.services.transformers_interpreter.importlib.util.find_spec",
        lambda _: object(),
    )

    interpreter = TransformersQuestionInterpreter(
        TransformersConfiguration(cache_dir=None, local_files_only=True)
    )
    ready, detail = await interpreter.health()
    assert ready is True
    assert "first use" in detail

    await interpreter.preload()
    proposal = await interpreter.interpret(
        "What was postpaid churn by plan last month?",
        _pack(),
    )

    assert proposal.candidate_metric_ids == ["POSTPAID_CHURN"]
    assert proposal.candidate_dimensions == ["PLAN"]
    assert model.device == "cpu"
    assert model.eval_called is True
    ready, detail = await interpreter.health()
    assert ready is True
    assert "loaded on cpu" in detail


def test_resolve_device_enforces_requested_hardware() -> None:
    cpu_only = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
    )
    cuda_available = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
    )
    mps_available = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
    )

    assert resolve_device(cpu_only, "auto") == "cpu"
    assert resolve_device(cuda_available, "auto") == "cuda"
    assert resolve_device(mps_available, "auto") == "mps"
    assert resolve_device(cpu_only, "cpu") == "cpu"
    with pytest.raises(InterpretationError, match="CUDA"):
        resolve_device(cpu_only, "cuda")
    with pytest.raises(InterpretationError, match="MPS"):
        resolve_device(cpu_only, "mps")


@pytest.mark.asyncio
async def test_preload_normalizes_missing_framework_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "talk2data.services.transformers_interpreter.importlib.import_module",
        lambda name: (_ for _ in ()).throw(ImportError(name)),
    )
    interpreter = TransformersQuestionInterpreter(TransformersConfiguration())
    with pytest.raises(InterpretationError, match="torch and transformers"):
        await interpreter.preload()
