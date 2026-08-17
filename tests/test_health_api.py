from __future__ import annotations

from fastapi.testclient import TestClient


def test_liveness(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_without_optional_runtimes(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["components"]["domain_packs"]["status"] == "ready"
    assert body["components"]["session_store"]["status"] == "ready"
    assert body["components"]["ollama"]["status"] == "disabled"
    assert body["components"]["hermes"]["status"] == "disabled"
