from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest

from talk2data.domain.models import (
    AccessContext,
    BusinessQueryIR,
    ClassificationLevel,
    QueryCompilationRequest,
    QueryFilter,
    QuestionDecision,
)
from talk2data.services.ephemeral_run import EphemeralRunStore
from talk2data.services.interpreter import (
    CompositeQuestionInterpreter,
    HeuristicQuestionInterpreter,
    InterpretationError,
)
from talk2data.services.policy import PolicyEngine
from talk2data.services.query_compiler import BusinessQueryCompiler
from talk2data.services.semantic import DimensionNotAllowedError, SemanticRegistry
from talk2data.services.session_store import (
    SessionAccessDeniedError,
    SessionNotFoundError,
    SessionStoreError,
    SQLiteSessionStore,
)


@pytest.fixture
def compiled(client, full_access):
    request = QueryCompilationRequest(
        question="Mobile activations last month",
        access_context=AccessContext.model_validate(full_access),
        use_llm=False,
        as_of="2026-08-17T12:00:00Z",
    )
    response = client.post("/v1/query-plans/compile", json=request.model_dump(mode="json")).json()
    assert response["status"] == "COMPILED"
    return (
        request,
        QuestionDecision.model_validate(response["decision"]),
        BusinessQueryIR.model_validate(response["query_ir"]),
    )


@pytest.mark.parametrize(
    ("question", "code"),
    [
        ("Mobile activations from 2026-01-01 to 2026-01-02 and 2026-01-03", "TOO_MANY_EXPLICIT_DATES"),
        ("Mobile activations from 2026-02-30 to 2026-03-02", "INVALID_EXPLICIT_DATE"),
        ("Mobile activations from 2026-07-31 to 2026-07-01", "INVALID_DATE_RANGE"),
        ("Mobile activations since 2026-07-01", "UNSUPPORTED_OPEN_ENDED_DATE_RANGE"),
    ],
)
def test_ambiguous_or_invalid_dates_require_correction(client, full_access, question, code):
    result = client.post(
        "/v1/query-plans/compile",
        json={"question": question, "access_context": full_access, "use_llm": False},
    ).json()
    assert result["status"] == "INVALID"
    assert result["issues"][0]["code"] == code


@pytest.mark.parametrize(
    ("ids", "access_updates", "code"),
    [
        ([], {}, "NO_GOVERNED_METRIC"),
        (["UNKNOWN"], {}, "METRIC_NOT_FOUND"),
        (["MOBILE_ACTIVATIONS"], {"classification_clearance": "PUBLIC"}, "SEMANTIC_ACCESS_DENIED"),
        (["ARPA"], {}, "GOVERNED_SOURCE_NOT_AVAILABLE"),
    ],
)
def test_compiler_rechecks_semantic_and_policy_contracts(compiled, client, ids, access_updates, code):
    request, decision, ir = compiled
    access = request.access_context.model_copy(update=access_updates)
    result = client.app.state.query_compiler.compile(
        request=request.model_copy(update={"access_context": access}),
        decision=decision.model_copy(update={"candidate_metric_ids": ids}),
        session_id=ir.session_id,
    )
    assert result.query_ir is None
    assert result.issues[0].code == code


def test_compiler_rechecks_group_and_filter_clearance(compiled, client, monkeypatch):
    request, decision, ir = compiled
    registry = client.app.state.domain_registry
    pack = registry.get("demo-telecom")
    entities = [
        e.model_copy(update={"classification": ClassificationLevel.RESTRICTED}) if e.id == "REGION" else e
        for e in pack.entities
    ]
    monkeypatch.setitem(registry._packs, pack.tenant_id, pack.model_copy(update={"entities": entities}))
    result = client.app.state.query_compiler.compile(
        request=request,
        decision=decision.model_copy(update={"candidate_dimension_ids": ["REGION"]}),
        session_id=ir.session_id,
    )
    assert result.issues[0].code == "DIMENSION_ACCESS_DENIED"
    monkeypatch.setattr(
        client.app.state.query_compiler,
        "_resolve_filters",
        lambda *args: [QueryFilter(dimension_id="UNKNOWN", values=["x"])],
    )
    result = client.app.state.query_compiler.compile(
        request=request, decision=decision, session_id=ir.session_id
    )
    assert result.issues[0].code == "FILTER_DIMENSION_NOT_ALLOWED_FOR_METRIC"


def test_semantic_dimensions_deduplicate_and_fail_on_incomplete_snapshot(compiled, client):
    request, _, _ = compiled
    semantics = SemanticRegistry(client.app.state.domain_registry, PolicyEngine())
    pack, metric = semantics.resolve_metric(request.access_context, "MOBILE_ACTIVATIONS")
    assert [
        e.id
        for e in semantics.resolve_dimensions(
            access=request.access_context, pack=pack, metric=metric, dimension_ids=["REGION", "REGION"]
        )
    ] == ["REGION"]
    with pytest.raises(DimensionNotAllowedError):
        semantics.resolve_dimensions(
            access=request.access_context,
            pack=pack.model_copy(update={"entities": []}),
            metric=metric,
            dimension_ids=["REGION"],
        )
    comparison, warnings = BusinessQueryCompiler._resolve_comparison(
        "Compare activations", "COMPARISON", metric.model_copy(update={"default_comparison": "PRIOR_PERIOD"})
    )
    assert comparison.comparison_type == "PRIOR_PERIOD" and warnings == ["DEFAULT_COMPARISON_APPLIED"]
    comparison, _ = BusinessQueryCompiler._resolve_comparison(
        "activations year over year", "COMPARISON", metric
    )
    assert comparison.comparison_type == "YEAR_OVER_YEAR"


@pytest.mark.asyncio
async def test_durable_session_lifecycle_never_crosses_ownership(tmp_path, compiled, monkeypatch):
    request, _, ir = compiled
    store = SQLiteSessionStore(tmp_path / "session.db")
    await store.initialize()
    session_id = await store.create_session(request.access_context)
    with pytest.raises(SessionStoreError, match="already exists"):
        await store.create_session(request.access_context, session_id=session_id)
    with pytest.raises(SessionNotFoundError):
        await store.ensure_access(uuid4(), request.access_context)
    with pytest.raises(SessionNotFoundError):
        await store.get_session(uuid4(), tenant_id="unknown", user_id="unknown")
    with pytest.raises(SessionNotFoundError):
        await store.record_query_plan(session_id=uuid4(), query_ir=ir)
    with store._connection() as connection, pytest.raises(SessionNotFoundError):
        store._touch_session(connection, uuid4(), "2026-08-17")
    monkeypatch.setattr(store, "_health_sync", lambda: (0,))
    assert not (await store.health())[0]

    def unavailable():
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(store, "_health_sync", unavailable)
    assert not (await store.health())[0]


@pytest.mark.asyncio
async def test_ephemeral_evidence_is_scoped_to_its_run_and_owner(compiled):
    request, decision, ir = compiled
    store = EphemeralRunStore()
    session = await store.create_session(request.access_context, session_id=uuid4())
    await store.ensure_access(session, request.access_context)
    await store.record_evaluation(session_id=session, question=request.question, decision=decision)
    await store.record_query_plan(session_id=session, query_ir=ir)
    assert store.question == request.question and store.query_ir == ir
    for identifier, access in [
        (uuid4(), request.access_context),
        (session, request.access_context.model_copy(update={"user_id": "intruder"})),
    ]:
        with pytest.raises(SessionAccessDeniedError):
            await store.ensure_access(identifier, access)
    with pytest.raises(SessionAccessDeniedError):
        await store.record_evaluation(session_id=uuid4(), question="injected", decision=decision)
    with pytest.raises(SessionAccessDeniedError):
        await store.record_query_plan(session_id=uuid4(), query_ir=ir)
    assert store.question == request.question and store.query_ir == ir


@pytest.mark.asyncio
async def test_required_provider_cannot_be_missing(compiled, client):
    request, _, _ = compiled
    interpreter = CompositeQuestionInterpreter(HeuristicQuestionInterpreter(), None, ollama_required=True)
    with pytest.raises(InterpretationError, match="not configured"):
        await interpreter.interpret(
            request.question, client.app.state.domain_registry.get("demo-telecom"), use_llm=True
        )


@pytest.mark.parametrize(
    ("question", "actions"),
    [
        ("What are our region policies?", ["ASK_BUSINESS_QUESTIONS"]),
        ("Mobile activations last month", ["ASK_BUSINESS_QUESTIONS"]),
        (
            "Did restaurant foot traffic near our stores affect mobile activations?",
            ["ASK_BUSINESS_QUESTIONS", "READ_AGGREGATED_DATA"],
        ),
    ],
)
def test_ungranted_data_memory_and_external_actions_are_denied(client, full_access, question, actions):
    response = client.post(
        "/v1/questions/evaluate",
        json={
            "question": question,
            "access_context": full_access | {"permitted_actions": actions},
            "use_llm": False,
        },
    ).json()
    assert response["decision"]["verdict"] == "DENY"


def test_non_additive_operation_rejected_even_when_terms_are_separated(client, full_access):
    response = client.post(
        "/v1/questions/evaluate",
        json={
            "question": "Sum of postpaid churn last month",
            "access_context": full_access,
            "use_llm": False,
        },
    ).json()
    assert response["decision"]["verdict"] == "INVALID_ANALYTIC_REQUEST"
