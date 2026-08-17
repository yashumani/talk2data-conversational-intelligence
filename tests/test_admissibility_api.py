from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient


def evaluate(
    client: TestClient,
    question: str,
    access: dict[str, object],
    *,
    session_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "question": question,
        "access_context": access,
        "use_llm": False,
    }
    if session_id is not None:
        payload["session_id"] = session_id
    response = client.post("/v1/questions/evaluate", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_accepts_governed_internal_metric_question(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = evaluate(client, "What was postpaid churn by plan last month?", full_access)

    decision = body["decision"]
    assert decision["verdict"] == "ACCEPT_INTERNAL"
    assert decision["candidate_metric_ids"] == ["POSTPAID_CHURN"]
    assert "PLAN" in decision["candidate_entity_ids"]
    assert "PLAN" in decision["candidate_dimension_ids"]
    assert decision["data_status"] == "AVAILABLE"
    assert decision["domain_pack_version"] == "2026.08.2"


def test_rejects_unrelated_food_business_question(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = evaluate(
        client,
        "What is our restaurant food-cost margin by location?",
        full_access,
    )

    decision = body["decision"]
    assert decision["verdict"] == "OUT_OF_DOMAIN"
    assert "EXPLICIT_DOMAIN_EXCLUSION" in decision["reason_codes"]
    assert decision["domain_anchor_ids"] == []


def test_accepts_external_context_with_retail_anchor(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = evaluate(
        client,
        "Did restaurant foot traffic near our stores affect mobile activations?",
        full_access,
    )

    decision = body["decision"]
    assert decision["verdict"] == "ACCEPT_EXTERNAL_AUGMENTED"
    assert "MOBILE_ACTIVATIONS" in decision["candidate_metric_ids"]
    assert "STORE" in decision["candidate_entity_ids"]
    assert "Restaurant and Dining-Area Foot Traffic" in decision["external_topics"]


def test_accepts_external_application_traffic_with_network_anchor(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = evaluate(
        client,
        "Did food-delivery application traffic contribute to evening network congestion?",
        full_access,
    )

    decision = body["decision"]
    assert decision["verdict"] == "ACCEPT_EXTERNAL_AUGMENTED"
    assert "NETWORK_CONGESTION" in decision["candidate_metric_ids"]
    assert "HOUR" in decision["candidate_entity_ids"]


def test_distinguishes_valid_question_with_no_connected_source(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = evaluate(client, "What was ARPA last month?", full_access)

    decision = body["decision"]
    assert decision["verdict"] == "VALID_NO_SOURCE"
    assert decision["data_status"] == "NOT_CONNECTED"
    assert "NO_CONNECTED_GOVERNED_SOURCE" in decision["reason_codes"]


def test_rejects_invalid_non_additive_aggregation(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = evaluate(client, "Give me the sum of churn rates by plan.", full_access)

    decision = body["decision"]
    assert decision["verdict"] == "INVALID_ANALYTIC_REQUEST"
    assert "INVALID_NON_ADDITIVE_METRIC_AGGREGATION" in decision["reason_codes"]


def test_denies_user_without_question_permission(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    access = deepcopy(full_access)
    access["permitted_actions"] = []

    body = evaluate(client, "What was postpaid churn?", access)

    decision = body["decision"]
    assert decision["verdict"] == "DENY"
    assert decision["authorization_status"] == "DENIED"


def test_denies_confidential_metric_above_clearance(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    access = deepcopy(full_access)
    access["classification_clearance"] = "INTERNAL"

    body = evaluate(client, "What was postpaid churn?", access)

    decision = body["decision"]
    assert decision["verdict"] == "DENY"
    assert "RESOURCE_CLASSIFICATION_DENIED" in decision["reason_codes"]


def test_accepts_domain_knowledge_question(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = evaluate(client, "What does subscriber mean in this business?", full_access)

    decision = body["decision"]
    assert decision["verdict"] == "ACCEPT_KNOWLEDGE"
    assert "WIRELESS_SUBSCRIBER" in decision["domain_anchor_ids"]


def test_external_context_requires_explicit_permission(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    access = deepcopy(full_access)
    access["permitted_actions"] = [
        "ASK_BUSINESS_QUESTIONS",
        "READ_AGGREGATED_DATA",
        "READ_APPROVED_MEMORY",
    ]

    body = evaluate(
        client,
        "Did restaurant foot traffic near our stores affect mobile activations?",
        access,
    )

    assert body["decision"]["verdict"] == "DENY"
    assert "EXTERNAL_ACTION_NOT_ALLOWED" in body["decision"]["reason_codes"]
