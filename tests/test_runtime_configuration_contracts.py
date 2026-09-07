from __future__ import annotations

from copy import deepcopy

import pytest

from talk2data.bootstrap import _is_sensitive_validation_location
from talk2data.domain.physical_mapping import PhysicalMappingRegistry
from talk2data.main import create_app
from tests.test_runtime_package import runtime_package_payload


@pytest.mark.parametrize(
    "mutation",
    ["model", "slug", "draft_domain", "draft_mapping", "missing_metric", "extra_metric", "dimensions"],
)
def test_runtime_generation_rejects_invalid_or_unapproved_contracts(client, mutation):
    payload = deepcopy(runtime_package_payload())
    if mutation == "model":
        payload["model"]["model_id"] = "model; run command"
    elif mutation == "slug":
        payload["project_slug"] = "../outside"
    elif mutation == "draft_domain":
        payload["domain_pack"]["status"] = "DRAFT"
    elif mutation == "draft_mapping":
        payload["physical_mapping_pack"]["status"] = "DRAFT"
    elif mutation == "missing_metric":
        payload["physical_mapping_pack"]["connectors"][0]["metrics"] = []
    elif mutation == "extra_metric":
        payload["domain_pack"]["metrics"] = payload["domain_pack"]["metrics"][1:]
        payload["domain_pack"]["external_adjacencies"] = []
    else:
        payload["physical_mapping_pack"]["connectors"][0]["metrics"][0]["allowed_dimensions"] = []
    response = client.post("/v1/runtime-packages/preview", json=payload)
    assert response.status_code == 422
    assert "application/zip" not in response.headers["content-type"]


def test_bootstrap_rejects_mapping_drift_and_requires_hermes_credentials(settings, monkeypatch):
    with pytest.raises(ValueError, match="API_KEY"):
        create_app(settings.model_copy(update={"hermes_enabled": True, "hermes_api_key": None}))
    app = create_app(
        settings.model_copy(
            update={"hermes_enabled": True, "hermes_api_key": "test-only", "cors_allowed_origins": []}
        )
    )
    assert app.state.hermes_client is not None
    monkeypatch.setattr(
        PhysicalMappingRegistry, "validate_domain_pack", lambda *args: ["MISSING_PHYSICAL_MAPPING"]
    )
    with pytest.raises(ValueError, match="physical mapping validation failed"):
        create_app(settings)
    assert not _is_sensitive_validation_location(None)
    assert _is_sensitive_validation_location(["body", "credentials", 0])
