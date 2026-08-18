from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


AS_OF = "2026-08-17T12:00:00Z"


def ask(
    client: TestClient,
    question: str,
    access: dict[str, object],
    *,
    session_id: str | None = None,
    include_debug: bool = True,
) -> dict[str, Any]:
    response = client.post(
        "/v1/chat/demo",
        json={
            "question": question,
            "access_context": access,
            "session_id": session_id,
            "use_llm": False,
            "include_debug": include_debug,
            "as_of": AS_OF,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_demo_page_is_available(client: TestClient) -> None:
    response = client.get("/demo")
    assert response.status_code == 200
    assert "Talk2Data" in response.text
    assert "Verification panel" in response.text


def test_grouped_churn_answer_is_receipt_backed(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = ask(client, "What was postpaid churn by plan last month?", full_access)

    assert body["status"] == "ANSWERED"
    assert body["decision"]["interpreter_mode"] == "RULES"
    assert body["query_ir"]["metric_id"] == "POSTPAID_CHURN"
    assert body["query_ir"]["dimensions"] == ["PLAN"]
    assert body["receipt"]["data_quality_status"] == "VERIFIED"
    assert body["receipt"]["row_count"] == 3
    assert len(body["receipt"]["result_hash"]) == 64
    assert body["verification"]["status"] == "VERIFIED"
    assert len(body["answer"]["claims"]) == 3
    receipt_id = body["receipt"]["receipt_id"]
    assert {item["receipt_id"] for item in body["answer"]["claims"]} == {receipt_id}
    assert all(0 <= row["value"] <= 1 for row in body["receipt"]["result_rows"])


def test_comparison_and_session_continuity(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    first = ask(client, "What were mobile activations in Northeast last month?", full_access)
    second = ask(
        client,
        "Compare mobile activations in Northeast last month to the previous period.",
        full_access,
        session_id=first["session_id"],
    )

    assert second["session_id"] == first["session_id"]
    assert second["status"] == "ANSWERED"
    assert second["receipt"]["row_count"] == 1
    row = second["receipt"]["result_rows"][0]
    assert row["value"] > row["comparison_value"]
    assert row["absolute_change"] > 0
    assert row["percent_change"] > 0


def test_current_period_abstains_when_source_coverage_is_incomplete(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = ask(client, "What were mobile activations this month?", full_access)

    assert body["status"] == "SOURCE_NOT_READY"
    assert body["receipt"] is None
    assert "2026-07-31" in body["message"]


def test_out_of_domain_and_unavailable_source_are_distinct(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    excluded = ask(client, "What is our restaurant food-cost margin by location?", full_access)
    no_source = ask(client, "What was ARPA last month?", full_access)

    assert excluded["status"] == "OUT_OF_DOMAIN"
    assert no_source["status"] == "NO_SOURCE"
    assert excluded["receipt"] is None
    assert no_source["receipt"] is None


def test_external_driver_question_waits_for_context_integration(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = ask(
        client,
        "Did food-delivery application traffic contribute to network congestion?",
        full_access,
    )

    assert body["status"] == "CONTEXT_NOT_CONNECTED"
    assert body["decision"]["verdict"] == "ACCEPT_EXTERNAL_AUGMENTED"
    assert body["context_used"] is False
    assert body["receipt"] is None


def test_parameterized_execution_survives_sql_injection_text(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    injected = ask(
        client,
        "What were mobile activations in Northeast last month'; DROP TABLE metric_facts; --?",
        full_access,
    )
    normal = ask(client, "What were mobile activations in Northeast last month?", full_access)

    assert injected["status"] == "ANSWERED"
    assert normal["status"] == "ANSWERED"
    assert normal["receipt"]["row_count"] == 1


def test_debug_artifacts_can_be_hidden(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = ask(
        client,
        "What were mobile activations in West last month?",
        full_access,
        include_debug=False,
    )

    assert body["status"] == "ANSWERED"
    assert body["query_ir"] is None
    assert body["receipt"] is None
    assert body["answer"]["claims"]
