from __future__ import annotations

from fastapi.testclient import TestClient

PAGES_ORIGIN = "https://yashumani.github.io"


def test_pages_origin_is_allowed(client: TestClient) -> None:
    response = client.get("/health/live", headers={"Origin": PAGES_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PAGES_ORIGIN


def test_pages_preflight_is_allowed(client: TestClient) -> None:
    response = client.options(
        "/v1/chat/demo",
        headers={
            "Origin": PAGES_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PAGES_ORIGIN
    assert "POST" in response.headers["access-control-allow-methods"]
