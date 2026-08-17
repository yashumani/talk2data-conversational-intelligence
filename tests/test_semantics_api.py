from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient


def test_resolves_authorized_versioned_metric_definition(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    response = client.post(
        "/v1/semantics/metrics/resolve",
        json={"metric_id": "postpaid_churn", "access_context": full_access},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["domain_pack_version"] == "2026.08.3"
    assert len(body["semantic_snapshot_hash"]) == 64
    assert body["metric"]["id"] == "POSTPAID_CHURN"
    assert body["metric"]["semantic_version"] == "2.0"
    assert body["metric"]["default_time_window"] == "PREVIOUS_COMPLETE_MONTH"


def test_metric_resolution_enforces_classification_clearance(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    access = deepcopy(full_access)
    access["classification_clearance"] = "INTERNAL"

    response = client.post(
        "/v1/semantics/metrics/resolve",
        json={"metric_id": "POSTPAID_CHURN", "access_context": access},
    )

    assert response.status_code == 403


def test_unknown_metric_returns_not_found(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    response = client.post(
        "/v1/semantics/metrics/resolve",
        json={"metric_id": "UNKNOWN_METRIC", "access_context": full_access},
    )

    assert response.status_code == 404
