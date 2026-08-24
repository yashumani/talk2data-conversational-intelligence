from __future__ import annotations

import hashlib
import io
import json
import zipfile

from fastapi.testclient import TestClient


def _admin_access(full_access: dict[str, object]) -> dict[str, object]:
    access = dict(full_access)
    access["roles"] = ["TALK2DATA_ADMIN"]
    return access


def _request(full_access: dict[str, object]) -> dict[str, object]:
    return {
        "access_context": _admin_access(full_access),
        "project_slug": "network-insights",
        "display_name": "Network Insights Talk2Data",
        "ollama_model": "qwen3:0.6b",
        "api_port": 8080,
        "include_codespaces": True,
    }


def test_onboarding_requires_admin(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    response = client.post(
        "/v1/onboarding/validate",
        json={
            "access_context": full_access,
            "project_slug": "network-insights",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Data source onboarding administration access denied."
    )


def test_validates_approved_tenant_runtime_package(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    response = client.post("/v1/onboarding/validate", json=_request(full_access))

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["tenant_id"] == "demo-telecom"
    assert body["project_slug"] == "network-insights"
    assert body["connector_ids"] == [
        "network_performance_platform",
        "telecom_semantic_warehouse",
    ]
    assert body["mapping_version"]
    assert len(body["mapping_hash"]) == 64
    assert body["package_file_count"] >= 10
    assert body["errors"] == []


def test_downloads_deterministic_credential_free_runtime_package(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    payload = _request(full_access)
    first = client.post("/v1/onboarding/package", json=payload)
    second = client.post("/v1/onboarding/package", json=payload)

    assert first.status_code == 200
    assert first.headers["content-type"] == "application/zip"
    assert first.content == second.content
    assert first.headers["x-talk2data-package-sha256"] == hashlib.sha256(
        first.content
    ).hexdigest()
    assert "network-insights-talk2data-runtime.zip" in first.headers[
        "content-disposition"
    ]

    with zipfile.ZipFile(io.BytesIO(first.content)) as bundle:
        names = set(bundle.namelist())
        assert {
            ".env.example",
            "README.md",
            "docker-compose.yml",
            "checksums.json",
            "config/domain-packs/demo-telecom.yaml",
            "config/physical-mappings/demo-telecom.yaml",
            "config/talk2data.yaml",
            ".devcontainer/devcontainer.json",
            ".github/workflows/validate.yml",
        } <= names

        environment = bundle.read(".env.example").decode("utf-8")
        compose = bundle.read("docker-compose.yml").decode("utf-8")
        mapping = bundle.read(
            "config/physical-mappings/demo-telecom.yaml"
        ).decode("utf-8")
        all_text = "\n".join(
            bundle.read(name).decode("utf-8")
            for name in names
            if not name.endswith(".json") or name == "config/talk2data.yaml"
        )

        assert "T2D_POSTGRES_DSN=" in environment
        assert "env://T2D_POSTGRES_DSN" in mapping
        assert "${T2D_POSTGRES_DSN:?Set T2D_POSTGRES_DSN in .env}" in compose
        assert "postgresql://" not in all_text
        assert "password=" not in all_text.lower()

        expected = json.loads(bundle.read("checksums.json"))
        actual = {
            name: hashlib.sha256(bundle.read(name)).hexdigest()
            for name in expected
        }
        assert actual == expected


def test_rejects_package_that_omits_required_connector(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    payload = _request(full_access)
    payload["selected_connector_ids"] = ["telecom_semantic_warehouse"]

    validation = client.post("/v1/onboarding/validate", json=payload)
    package = client.post("/v1/onboarding/package", json=payload)

    assert validation.status_code == 200
    assert validation.json()["valid"] is False
    assert "network_performance_platform" in validation.json()["errors"][0]
    assert package.status_code == 422
