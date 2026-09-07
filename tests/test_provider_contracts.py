from __future__ import annotations

import json

import httpx
import pytest

from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import InterpretationProposal
from talk2data.services.hermes import HermesConfiguration, HermesGatewayClient, HermesRuntimeError
from talk2data.services.interpreter import (
    CompositeQuestionInterpreter,
    HeuristicQuestionInterpreter,
    InterpretationError,
    OllamaConfiguration,
    OllamaQuestionInterpreter,
    phrase_present,
)


@pytest.fixture
def pack():
    registry = DomainPackRegistry()
    registry.load()
    return registry.get("demo-telecom")


@pytest.fixture
def transport(monkeypatch):
    real_client = httpx.AsyncClient
    requests = []
    response = {"status": 200, "body": {}}

    def handler(request):
        requests.append(request)
        if "error" in response:
            raise httpx.ConnectError("Unavailable", request=request)
        return httpx.Response(response["status"], json=response["body"])

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)
    )
    return requests, response


def ollama():
    return OllamaQuestionInterpreter(
        OllamaConfiguration(base_url="http://provider.invalid", model="test-parser", timeout_seconds=2)
    )


@pytest.mark.asyncio
async def test_ollama_uses_catalog_constrained_schema_and_validates_response(transport, pack):
    requests, response = transport
    proposal = InterpretationProposal(
        intent="METRIC_LOOKUP", candidate_metric_ids=["MOBILE_ACTIVATIONS"], summary="Parsed", confidence=0.9
    )
    response["body"] = {"message": {"content": proposal.model_dump_json()}}
    assert await ollama().interpret("Mobile activations last month", pack) == proposal
    sent = json.loads(requests[0].content)
    assert sent["format"]["properties"]["candidate_metric_ids"]["type"] == "array"
    assert sent["stream"] is False
    assert sent["options"]["temperature"] == 0
    assert "MOBILE_ACTIVATIONS" in sent["messages"][1]["content"]
    assert (await ollama().health())[0]
    assert requests[-1].url.path == "/api/tags"
    response["error"] = True
    assert not (await ollama().health())[0]
    with pytest.raises(InterpretationError, match="request failed"):
        await ollama().interpret("question", pack)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"message": None},
        {"message": {"content": "not JSON"}},
        {"message": {"content": '{"confidence":2}'}},
    ],
)
async def test_invalid_model_payload_never_becomes_a_plan(transport, pack, body):
    transport[1]["body"] = body
    with pytest.raises(InterpretationError, match="invalid structured"):
        await ollama().interpret("question", pack)


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [True, False])
async def test_explicit_required_provider_never_silently_falls_back(pack, required):
    class Broken:
        async def interpret(self, question, pack):
            raise InterpretationError("Provider unavailable")

    interpreter = CompositeQuestionInterpreter(
        HeuristicQuestionInterpreter(), Broken(), ollama_required=required
    )
    if required:
        with pytest.raises(InterpretationError):
            await interpreter.interpret("Mobile activations", pack, use_llm=True)
    else:
        result = await interpreter.interpret("Mobile activations", pack, use_llm=True)
        assert result.mode == "OLLAMA_FAILED_RULES_FALLBACK"
        assert result.warnings == ["Provider unavailable"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "metrics", "dimensions", "intent"),
    [
        ("What was postpaid churn by plan last month?", ["POSTPAID_CHURN"], ["PLAN"], "METRIC_LOOKUP"),
        ("What were mobile activations this month?", ["MOBILE_ACTIVATIONS"], [], "METRIC_LOOKUP"),
        ("Compare mobile activations by region last month", ["MOBILE_ACTIVATIONS"], ["REGION"], "COMPARISON"),
    ],
)
async def test_model_cannot_expand_explicit_metric_or_grouping(pack, question, metrics, dimensions, intent):
    class CatalogEcho:
        async def interpret(self, question, pack):
            return InterpretationProposal(
                intent="DRIVER_ANALYSIS",
                candidate_metric_ids=["POSTPAID_CHURN", "MOBILE_ACTIVATIONS"],
                candidate_dimensions=["PLAN", "MARKET", "REGION", "CHANNEL", "HOUR"],
                requested_operation="SUM",
                summary="Overbroad model output",
                confidence=1,
            )

    result = await CompositeQuestionInterpreter(HeuristicQuestionInterpreter(), CatalogEcho()).interpret(
        question, pack, use_llm=True
    )
    assert result.proposal.candidate_metric_ids == metrics
    assert result.proposal.candidate_dimensions == dimensions
    assert result.proposal.intent == intent
    assert result.proposal.requested_operation != "SUM"


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["UNKNOWN", "METRIC_LOOKUP"])
async def test_valid_model_proposal_for_unmatched_paraphrase_is_schema_checked(pack, intent):
    class Proposal:
        async def interpret(self, question, pack):
            return InterpretationProposal(
                intent=intent,
                candidate_metric_ids=["mobile_activations"],
                candidate_entity_ids=["REGION"],
                candidate_domain_ids=[pack.domains[0].id],
                summary="Parsed",
                confidence=0.8,
            )

    result = await CompositeQuestionInterpreter(HeuristicQuestionInterpreter(), Proposal()).interpret(
        "newly connected mobile subscriptions", pack, use_llm=True
    )
    assert result.proposal.candidate_metric_ids == ["MOBILE_ACTIVATIONS"]
    assert result.proposal.candidate_dimensions == []


@pytest.mark.asyncio
async def test_hermes_auth_system_message_and_failure_contract(transport):
    requests, response = transport
    client = HermesGatewayClient(HermesConfiguration("http://hermes.invalid", "test-only-token", 2))
    response["body"] = {"choices": [{"message": {"content": "Allowed response"}}]}
    for system in [None, "Use approved tools only"]:
        assert (
            await client.complete(
                messages=[{"role": "user", "content": "Question"}], system_instruction=system
            )
            == "Allowed response"
        )
        sent = json.loads(requests[-1].content)
        assert len(sent["messages"]) == (2 if system else 1)
        assert requests[-1].headers["Authorization"] == "Bearer test-only-token"
    assert (await client.health())[0]
    response["error"] = True
    assert not (await client.health())[0]
    with pytest.raises(HermesRuntimeError, match="request failed"):
        await client.complete(messages=[])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": " "}}]},
        {"choices": [{"message": {"content": 1}}]},
    ],
)
async def test_hermes_rejects_empty_or_malformed_answers(transport, body):
    transport[1]["body"] = body
    with pytest.raises(HermesRuntimeError):
        await HermesGatewayClient(HermesConfiguration("http://hermes.invalid", "test-only", 1)).complete(
            messages=[]
        )


def test_phrase_boundaries_and_average_operation(pack):
    assert not phrase_present("mobile", "")
    assert not phrase_present("unplanned", "plan")
    assert (
        HeuristicQuestionInterpreter()
        .interpret("average of mobile activations", pack)
        .proposal.requested_operation
        == "AVERAGE"
    )
