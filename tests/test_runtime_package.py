from __future__ import annotations

import io
import json
import zipfile
from copy import deepcopy

from fastapi.testclient import TestClient

from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.physical_mapping import PhysicalMappingRegistry
from talk2data.domain.runtime_package import RuntimePackageRequest
from talk2data.services.runtime_package import RUNTIME_IMAGE, RuntimePackageBuilder


def runtime_package_payload(*, admin: bool = True) -> dict[str, object]:
    domains = DomainPackRegistry()
    domains.load()
    mappings = PhysicalMappingRegistry()
    mappings.load()
    return {
        "project_name": "Network Intelligence Assistant",
        "project_slug": "network-intelligence-assistant",
        "api_port": 8080,
        "model": {
            "provider": "OLLAMA",
            "model_id": "qwen3:0.6b",
            "timeout_seconds": 180,
        },
        "access_context": {
            "tenant_id": "demo-telecom",
            "user_id": "package-admin",
            "roles": ["TALK2DATA_ADMIN"] if admin else ["BI_MANAGER"],
            "classification_clearance": "RESTRICTED",
            "permitted_actions": [],
        },
        "domain_pack": domains.get("demo-telecom").model_dump(mode="json"),
        "physical_mapping_pack": mappings.get("demo-telecom").model_dump(mode="json"),
    }


def test_builder_is_deterministic_and_credential_free() -> None:
    request = RuntimePackageRequest.model_validate(runtime_package_payload())
    builder = RuntimePackageBuilder()

    first = builder.build(request)
    second = builder.build(request)

    assert first.preview.package_id == second.preview.package_id
    assert first.archive == second.archive
    assert first.preview.runtime_image == RUNTIME_IMAGE
    assert first.filename == "network-intelligence-assistant-talk2data-runtime.zip"
    assert (
        "postgresql://readonly_user:replace-me" in first.archive.decode("latin-1", errors="ignore") is False
    )

    with zipfile.ZipFile(io.BytesIO(first.archive)) as archive:
        names = set(archive.namelist())
        assert names >= {
            "talk2data.yaml",
            "docker-compose.yml",
            ".env.example",
            "manifest.json",
            "config/domain-packs/domain-pack.yaml",
            "config/physical-mappings/physical-mapping.yaml",
            "config/policies/policies.yaml",
            "config/harness/harness.yaml",
        }
        compose = archive.read("docker-compose.yml").decode("utf-8")
        environment = archive.read(".env.example").decode("utf-8")
        manifest = json.loads(archive.read("manifest.json"))

    assert RUNTIME_IMAGE in compose
    assert "T2D_POSTGRES_DSN" in compose
    assert "${T2D_POSTGRES_DSN:?Set T2D_POSTGRES_DSN}" in compose
    assert "T2D_POSTGRES_DSN=postgresql://readonly_user:replace-me" in environment
    assert "password@" not in compose
    assert manifest["package_id"] == first.preview.package_id
    assert manifest["physical_mapping_hash"] == request.physical_mapping_pack.canonical_hash()


def test_preview_api_returns_file_receipts(client: TestClient) -> None:
    response = client.post(
        "/v1/runtime-packages/preview",
        json=runtime_package_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["project_slug"] == "network-intelligence-assistant"
    assert body["runtime_image"] == RUNTIME_IMAGE
    assert len(body["package_id"]) == 64
    assert {item["path"] for item in body["files"]} >= {
        "docker-compose.yml",
        "manifest.json",
        "talk2data.yaml",
    }
    assert all(len(item["sha256"]) == 64 for item in body["files"])


def test_download_api_returns_deterministic_zip(client: TestClient) -> None:
    first = client.post(
        "/v1/runtime-packages/download",
        json=runtime_package_payload(),
    )
    second = client.post(
        "/v1/runtime-packages/download",
        json=runtime_package_payload(),
    )

    assert first.status_code == 200
    assert first.headers["content-type"] == "application/zip"
    assert "network-intelligence-assistant-talk2data-runtime.zip" in first.headers["content-disposition"]
    assert len(first.headers["x-talk2data-package-id"]) == 64
    assert first.headers["x-talk2data-package-id"] == second.headers["x-talk2data-package-id"]
    assert first.content == second.content

    with zipfile.ZipFile(io.BytesIO(first.content)) as archive:
        readme = archive.read("README.md").decode("utf-8")
    assert "Ollama interprets language only" in readme
    assert "Every released number must pass verification" in readme


def test_non_admin_cannot_generate_package(client: TestClient) -> None:
    response = client.post(
        "/v1/runtime-packages/preview",
        json=runtime_package_payload(admin=False),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Talk2Data administrator access is required to generate a runtime package."
    )


def test_tenant_mismatch_is_rejected_before_generation(client: TestClient) -> None:
    payload = runtime_package_payload()
    access = deepcopy(payload["access_context"])
    assert isinstance(access, dict)
    access["tenant_id"] = "different-tenant"
    payload["access_context"] = access

    response = client.post("/v1/runtime-packages/preview", json=payload)

    assert response.status_code == 422
    assert "tenant IDs must match" in response.text


def test_semantic_mapping_mismatch_is_rejected(client: TestClient) -> None:
    payload = runtime_package_payload()
    mapping = deepcopy(payload["physical_mapping_pack"])
    assert isinstance(mapping, dict)
    connectors = mapping["connectors"]
    assert isinstance(connectors, list)
    first_connector = connectors[0]
    assert isinstance(first_connector, dict)
    metrics = first_connector["metrics"]
    assert isinstance(metrics, list)
    first_metric = metrics[0]
    assert isinstance(first_metric, dict)
    first_metric["allowed_dimensions"] = ["PLAN", "REGION"]
    payload["physical_mapping_pack"] = mapping

    response = client.post("/v1/runtime-packages/preview", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "Dimension mapping mismatch for metric 'POSTPAID_CHURN'."


def test_embedded_database_credential_is_rejected(client: TestClient) -> None:
    payload = runtime_package_payload()
    mapping = deepcopy(payload["physical_mapping_pack"])
    assert isinstance(mapping, dict)
    connectors = mapping["connectors"]
    assert isinstance(connectors, list)
    first_connector = connectors[0]
    assert isinstance(first_connector, dict)
    first_connector["secret_ref"] = "postgresql://user:actual-secret@database/analytics"
    payload["physical_mapping_pack"] = mapping

    response = client.post("/v1/runtime-packages/preview", json=payload)

    assert response.status_code == 422
    assert "secret_ref must use env://NAME" in response.text
    assert "actual-secret" not in response.text
