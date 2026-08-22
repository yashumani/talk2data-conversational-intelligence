from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from tests.test_admissibility_api import evaluate


def test_session_persists_messages_and_decision(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    first = evaluate(client, "What was postpaid churn by plan?", full_access)
    session_id = first["session_id"]

    second = evaluate(
        client,
        "Did it change over time?",
        full_access,
        session_id=session_id,
    )
    assert second["session_id"] == session_id

    response = client.get(
        f"/v1/sessions/{session_id}",
        headers={"X-Tenant-ID": "demo-telecom", "X-User-ID": "test-user"},
    )
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert len(snapshot["messages"]) == 4
    assert len(snapshot["decisions"]) == 2
    assert snapshot["decisions"][0]["candidate_metric_ids"] == ["POSTPAID_CHURN"]


def test_session_isolation_rejects_other_user(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    first = evaluate(client, "What was postpaid churn?", full_access)
    session_id = first["session_id"]

    response = client.get(
        f"/v1/sessions/{session_id}",
        headers={"X-Tenant-ID": "demo-telecom", "X-User-ID": "other-user"},
    )
    assert response.status_code == 403

    other_access = deepcopy(full_access)
    other_access["user_id"] = "other-user"
    reuse = client.post(
        "/v1/questions/evaluate",
        json={
            "question": "What was postpaid churn?",
            "access_context": other_access,
            "session_id": session_id,
            "use_llm": False,
        },
    )
    assert reuse.status_code == 403
