from __future__ import annotations

from fastapi.testclient import TestClient


def compile_query(
    client: TestClient,
    question: str,
    access: dict[str, object],
    *,
    session_id: str | None = None,
    as_of: str = "2026-08-17T12:00:00Z",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "question": question,
        "access_context": access,
        "use_llm": False,
        "as_of": as_of,
    }
    if session_id is not None:
        payload["session_id"] = session_id
    response = client.post("/v1/query-plans/compile", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_compiles_governed_metric_to_business_query_ir(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = compile_query(
        client,
        "What was postpaid churn by plan last month?",
        full_access,
    )

    assert body["status"] == "COMPILED"
    query_ir = body["query_ir"]
    assert query_ir["session_id"] == body["session_id"]
    assert query_ir["decision_id"] == body["decision"]["decision_id"]
    assert query_ir["metric_id"] == "POSTPAID_CHURN"
    assert query_ir["semantic_version"] == "2.0"
    assert query_ir["aggregation"] == "RATIO"
    assert query_ir["additivity"] == "NON_ADDITIVE"
    assert query_ir["dimensions"] == ["PLAN"]
    assert query_ir["time_window"]["preset"] == "PREVIOUS_COMPLETE_MONTH"
    assert query_ir["time_window"]["calendar"] == "CORPORATE_FISCAL"
    assert query_ir["source_connector_id"] == "telecom_semantic_warehouse"
    assert len(query_ir["semantic_snapshot_hash"]) == 64
    assert len(query_ir["plan_hash"]) == 64


def test_compiles_governed_dimension_value_filter(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = compile_query(
        client,
        "What was postpaid churn in the Northeast last month?",
        full_access,
    )

    assert body["status"] == "COMPILED"
    assert body["query_ir"]["filters"] == [
        {
            "dimension_id": "REGION",
            "operator": "IN",
            "values": ["NORTHEAST"],
        }
    ]


def test_semantically_equivalent_questions_have_same_plan_hash(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    first = compile_query(
        client,
        "What was postpaid churn in Northeast last month?",
        full_access,
    )
    second = compile_query(
        client,
        "Show last month postpaid churn for the Northeast.",
        full_access,
    )

    assert first["query_ir"]["plan_hash"] == second["query_ir"]["plan_hash"]


def test_compiles_explicit_closed_date_range(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = compile_query(
        client,
        "What were mobile activations from 2026-07-01 to 2026-07-31?",
        full_access,
    )

    window = body["query_ir"]["time_window"]
    assert window["preset"] == "CUSTOM"
    assert window["start_date"] == "2026-07-01"
    assert window["end_date"] == "2026-07-31"


def test_rejects_dimension_not_allowed_for_metric(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = compile_query(
        client,
        "What was postpaid churn by cell site last month?",
        full_access,
    )

    assert body["decision"]["verdict"] == "ACCEPT_INTERNAL"
    assert body["status"] == "INVALID"
    assert body["issues"][0]["code"] == "DIMENSION_NOT_ALLOWED_FOR_METRIC"
    assert body["query_ir"] is None


def test_requires_clarification_for_multiple_primary_metrics(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = compile_query(
        client,
        "Compare postpaid churn and mobile activations last month.",
        full_access,
    )

    assert body["status"] == "CLARIFICATION_REQUIRED"
    assert body["issues"][0]["code"] == "MULTIPLE_METRICS_REQUIRE_EXPLICIT_PLAN"


def test_non_available_source_does_not_compile(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = compile_query(client, "What was ARPA last month?", full_access)

    assert body["decision"]["verdict"] == "VALID_NO_SOURCE"
    assert body["status"] == "NOT_ELIGIBLE"
    assert body["query_ir"] is None


def test_governed_default_time_window_is_visible(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = compile_query(client, "What are mobile activations?", full_access)

    assert body["status"] == "COMPILED"
    assert body["query_ir"]["time_window"]["preset"] == "PREVIOUS_COMPLETE_MONTH"
    assert "DEFAULT_TIME_WINDOW_APPLIED" in body["warnings"]


def test_external_augmented_plan_preserves_trust_boundary(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = compile_query(
        client,
        "Did restaurant foot traffic near our stores affect mobile activations last month?",
        full_access,
    )

    assert body["status"] == "COMPILED"
    assert body["decision"]["verdict"] == "ACCEPT_EXTERNAL_AUGMENTED"
    assert body["query_ir"]["requires_external_context"] is True


def test_compiled_plan_is_persisted_in_tenant_scoped_session(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = compile_query(client, "What was postpaid churn last month?", full_access)
    session_id = body["session_id"]

    response = client.get(
        f"/v1/sessions/{session_id}",
        headers={"X-Tenant-ID": "demo-telecom", "X-User-ID": "test-user"},
    )
    assert response.status_code == 200, response.text
    session = response.json()
    assert len(session["query_plans"]) == 1
    assert session["query_plans"][0]["plan_hash"] == body["query_ir"]["plan_hash"]


def test_rejects_unsupported_time_grain(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = compile_query(client, "What was network congestion last year?", full_access)

    assert body["status"] == "INVALID"
    assert body["issues"][0]["code"] == "TIME_GRAIN_NOT_SUPPORTED"


def test_rejects_invalid_explicit_calendar_date(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = compile_query(
        client,
        "What were mobile activations on 2026-02-30?",
        full_access,
    )

    assert body["status"] == "INVALID"
    assert body["issues"][0]["code"] == "INVALID_EXPLICIT_DATE"
    assert body["query_ir"] is None


def test_rechecks_classification_for_detected_filter_dimensions(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    body = compile_query(
        client,
        "What was network congestion for 5G last month?",
        full_access,
    )

    assert body["decision"]["verdict"] == "ACCEPT_INTERNAL"
    assert body["status"] == "NOT_ELIGIBLE"
    assert body["issues"][0]["code"] == "FILTER_DIMENSION_ACCESS_DENIED"
    assert body["query_ir"] is None
