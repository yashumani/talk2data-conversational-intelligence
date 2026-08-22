from __future__ import annotations

from fastapi.testclient import TestClient


def test_lists_configured_connector_contracts(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    response = client.post(
        "/v1/connectors/list",
        json={"access_context": full_access},
    )

    assert response.status_code == 200
    body = response.json()
    connector_ids = {item["connector_id"] for item in body["connectors"]}
    assert connector_ids == {"telecom_semantic_warehouse", "network_performance_platform"}
    assert all(item["read_only"] is True for item in body["connectors"])


def test_returns_authorized_catalog_and_freshness(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    request = {
        "connector_id": "telecom_semantic_warehouse",
        "access_context": full_access,
    }

    catalog = client.post("/v1/connectors/catalog", json=request)
    freshness = client.post("/v1/connectors/freshness", json=request)

    assert catalog.status_code == 200
    assert {item["metric_id"] for item in catalog.json()["items"]} == {
        "POSTPAID_CHURN",
        "MOBILE_ACTIVATIONS",
    }
    assert freshness.status_code == 200
    assert freshness.json()["freshness"]["status"] == "AVAILABLE"


def test_denies_connector_metadata_without_data_permission(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    restricted = dict(full_access)
    restricted["permitted_actions"] = ["ASK_BUSINESS_QUESTIONS"]

    response = client.post(
        "/v1/connectors/catalog",
        json={
            "connector_id": "telecom_semantic_warehouse",
            "access_context": restricted,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Connector data access denied."


def test_connector_test_requires_admin_role(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    denied = client.post(
        "/v1/connectors/test",
        json={
            "connector_id": "telecom_semantic_warehouse",
            "access_context": full_access,
        },
    )
    assert denied.status_code == 403

    admin = dict(full_access)
    admin["roles"] = ["TALK2DATA_ADMIN"]
    allowed = client.post(
        "/v1/connectors/test",
        json={
            "connector_id": "telecom_semantic_warehouse",
            "access_context": admin,
        },
    )
    assert allowed.status_code == 200
    assert allowed.json()["ready"] is True
