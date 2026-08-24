from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.physical_mapping import (
    PhysicalMappingError,
    PhysicalMappingRegistry,
    TenantPhysicalMappingPack,
)


def test_pack_is_versioned_hashed_and_aligned_with_domain_pack() -> None:
    mappings = PhysicalMappingRegistry()
    mappings.load()
    domains = DomainPackRegistry()
    domains.load()

    pack = mappings.get("demo-telecom")
    connector = pack.connector("telecom_semantic_warehouse")

    assert pack.version == "2026.08.2"
    assert len(pack.canonical_hash()) == 64
    assert len(pack.connector_hash(connector.connector_id)) == 64
    assert mappings.validate_domain_pack(domains.get("demo-telecom")) == []
    assert connector.metric("POSTPAID_CHURN").numerator_column == "numerator"
    assert connector.required_columns() >= {
        "fact_date",
        "period_end",
        "metric_id",
        "numerator",
        "denominator",
        "amount",
        "plan_id",
    }


def test_hash_is_stable_when_set_input_order_changes() -> None:
    mappings = PhysicalMappingRegistry()
    mappings.load()
    pack = mappings.get("demo-telecom")
    payload = pack.model_dump(mode="json")
    payload["connectors"][0]["metrics"][0]["allowed_dimensions"].reverse()
    payload["connectors"][0]["scope_value_allowlists"]["REGION"].reverse()
    payload["connectors"][0]["scope_value_mappings"]["REGION"]["NORTH_AMERICA"].reverse()
    reordered = TenantPhysicalMappingPack.model_validate(payload)

    assert reordered.canonical_hash() == pack.canonical_hash()
    assert reordered.connector_hash("telecom_semantic_warehouse") == pack.connector_hash(
        "telecom_semantic_warehouse"
    )


def test_broad_region_scope_expands_to_approved_physical_values() -> None:
    mappings = PhysicalMappingRegistry()
    mappings.load()
    connector = mappings.get("demo-telecom").connector("telecom_semantic_warehouse")

    assert connector.resolve_scope_values("REGION", {"NORTH_AMERICA"}) == {
        "NORTHEAST",
        "SOUTHEAST",
        "CENTRAL",
        "WEST",
    }
    assert connector.resolve_scope_values("REGION", {"NORTHEAST"}) == {"NORTHEAST"}


def test_irrelevant_scope_dimension_is_not_applied_to_connector() -> None:
    mappings = PhysicalMappingRegistry()
    mappings.load()
    connector = mappings.get("demo-telecom").connector("network_performance_platform")

    assert connector.resolve_scope_values("REGION", {"NORTH_AMERICA"}) == set()


def test_unknown_region_scope_is_rejected_instead_of_becoming_unrestricted() -> None:
    mappings = PhysicalMappingRegistry()
    mappings.load()
    connector = mappings.get("demo-telecom").connector("telecom_semantic_warehouse")

    with pytest.raises(PhysicalMappingError, match="no approved physical mapping"):
        connector.resolve_scope_values("REGION", {"EUROPE"})


def test_public_view_never_exposes_secret_reference_name() -> None:
    mappings = PhysicalMappingRegistry()
    mappings.load()

    view = mappings.get("demo-telecom").connector("telecom_semantic_warehouse").public_view()

    assert view["secret_provider"] == "env"
    assert "secret_ref" not in view
    assert "T2D_POSTGRES_DSN" not in str(view)
    assert view["scope_value_mappings"]["REGION"]["NORTH_AMERICA"] == [
        "CENTRAL",
        "NORTHEAST",
        "SOUTHEAST",
        "WEST",
    ]


def test_ratio_mapping_requires_governed_numerator_and_denominator() -> None:
    mappings = PhysicalMappingRegistry()
    mappings.load()
    payload = mappings.get("demo-telecom").model_dump(mode="python")
    invalid = deepcopy(payload)
    invalid["connectors"][0]["metrics"][0]["denominator_column"] = None

    with pytest.raises(ValidationError, match="denominator_column"):
        TenantPhysicalMappingPack.model_validate(invalid)


def test_mapping_rejects_embedded_credentials() -> None:
    mappings = PhysicalMappingRegistry()
    mappings.load()
    payload = mappings.get("demo-telecom").model_dump(mode="python")
    invalid = deepcopy(payload)
    invalid["connectors"][0]["secret_ref"] = "postgresql://user:password@host/db"

    with pytest.raises(ValidationError, match="env://NAME"):
        TenantPhysicalMappingPack.model_validate(invalid)


def test_scope_mapping_cannot_expand_outside_physical_allowlist() -> None:
    mappings = PhysicalMappingRegistry()
    mappings.load()
    payload = mappings.get("demo-telecom").model_dump(mode="python")
    invalid = deepcopy(payload)
    invalid["connectors"][0]["scope_value_mappings"]["REGION"]["NORTH_AMERICA"].add("EUROPE")

    with pytest.raises(ValidationError, match="outside the allowlist"):
        TenantPhysicalMappingPack.model_validate(invalid)


def test_admin_can_read_mapping_without_secret(client: TestClient) -> None:
    response = client.post(
        "/v1/physical-mappings/list",
        json={
            "access_context": {
                "tenant_id": "demo-telecom",
                "user_id": "mapping-admin",
                "roles": ["TALK2DATA_ADMIN"],
                "classification_clearance": "RESTRICTED",
                "permitted_actions": [],
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "demo-telecom"
    assert body["validation_failures"] == []
    assert len(body["mapping_hash"]) == 64
    assert body["connectors"][0]["secret_provider"] == "env"
    assert "secret_ref" not in str(body)


def test_non_admin_cannot_read_physical_mapping(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    response = client.post(
        "/v1/physical-mappings/list",
        json={"access_context": full_access},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Physical mapping administration access denied."


def test_admin_can_read_one_connector_mapping(client: TestClient) -> None:
    access = {
        "tenant_id": "demo-telecom",
        "user_id": "mapping-admin",
        "roles": ["TALK2DATA_ADMIN"],
        "classification_clearance": "RESTRICTED",
        "permitted_actions": [],
    }
    response = client.post(
        "/v1/physical-mappings/connector",
        json={
            "connector_id": "network_performance_platform",
            "access_context": access,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["connector"]["connector_id"] == "network_performance_platform"
    assert body["connector"]["dimensions"]["TECHNOLOGY"] == "technology_id"
    assert len(body["mapping_hash"]) == 64
