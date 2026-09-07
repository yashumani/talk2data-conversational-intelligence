from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import yaml
from pydantic import ValidationError

from talk2data.connectors.factory import build_connectors
from talk2data.connectors.registry import ConnectorRegistry, ConnectorRegistryError
from talk2data.core.config import Settings
from talk2data.domain.domain_pack import DomainPackError, DomainPackRegistry
from talk2data.domain.evidence import ApprovedClaim, EvidenceReceipt
from talk2data.domain.memory import ContextCoverageReceipt, MemoryEvidence, MemoryQuery
from talk2data.domain.models import BusinessEntity, MetricDefinition, QuestionRequest, TenantDomainPack
from talk2data.domain.physical_mapping import (
    PhysicalConnectorMapping,
    PhysicalMappingError,
    PhysicalMappingRegistry,
    PhysicalMetricMapping,
    TenantPhysicalMappingPack,
)
from tests.test_postgres_connector import build_access, build_connector


@pytest.fixture
def domain():
    registry = DomainPackRegistry()
    registry.load()
    return registry.get("demo-telecom")


@pytest.mark.parametrize("registry_type", [DomainPackRegistry, PhysicalMappingRegistry])
def test_registry_only_activates_one_complete_approved_snapshot(tmp_path, registry_type):
    bundled = registry_type()
    bundled.load()
    payload = bundled.get("demo-telecom").model_dump(mode="json")
    registry = registry_type(tmp_path)
    with pytest.raises((DomainPackError, PhysicalMappingError), match=r"no .* files"):
        registry.load()
    path = tmp_path / "approved.yml"
    path.write_text(yaml.safe_dump(payload))
    registry.load()
    original = registry.get("demo-telecom")
    assert registry.loaded and registry.list_tenants() == ["demo-telecom"]
    with pytest.raises((DomainPackError, PhysicalMappingError)):
        registry.get("missing")
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(path.read_text())
    with pytest.raises((DomainPackError, PhysicalMappingError), match="multiple approved"):
        registry.load()
    assert registry.get("demo-telecom") is original
    duplicate.write_text(yaml.safe_dump(payload | {"status": "DRAFT"}))
    registry.load()
    path.unlink()
    with pytest.raises((DomainPackError, PhysicalMappingError), match="no approved"):
        registry.load()
    for invalid in ["- a list", "bad: ["]:
        duplicate.write_text(invalid)
        with pytest.raises((DomainPackError, PhysicalMappingError)):
            registry.load()
    with pytest.raises((DomainPackError, PhysicalMappingError), match="failed to read"):
        registry_type._load_yaml(tmp_path / "missing.yaml")


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_domain",
        "duplicate_metric",
        "duplicate_entity",
        "metric_domain",
        "metric_dimension",
        "entity_domain",
        "adjacency",
    ],
)
def test_semantic_snapshot_rejects_broken_references(domain, mutation):
    data = domain.model_dump(mode="json")
    if mutation.startswith("duplicate_"):
        field = {"domain": "domains", "metric": "metrics", "entity": "entities"}[
            mutation.removeprefix("duplicate_")
        ]
        data[field].append(data[field][0])
    elif mutation == "metric_domain":
        data["metrics"][0]["domain_id"] = "UNKNOWN"
    elif mutation == "metric_dimension":
        data["metrics"][0]["allowed_dimensions"] = ["UNKNOWN"]
    elif mutation == "entity_domain":
        data["entities"][0]["domain_id"] = "UNKNOWN"
    else:
        data["external_adjacencies"][0]["anchor_metric_ids"] = ["UNKNOWN"]
    with pytest.raises(ValidationError):
        TenantDomainPack.model_validate(data)


@pytest.mark.parametrize(
    "updates",
    [
        {"supported_time_grains": []},
        {"valid_min": 2, "valid_max": 1},
        {"aggregation": "RATIO", "additivity": "ADDITIVE"},
    ],
)
def test_metric_contract_cannot_contradict_its_bounds_or_aggregation(domain, updates):
    with pytest.raises(ValidationError):
        MetricDefinition.model_validate(domain.metrics[0].model_dump() | updates)


def test_dimension_ids_and_question_whitespace_are_validated(domain):
    entity = next(e for e in domain.entities if e.values)
    with pytest.raises(ValidationError, match="duplicate values"):
        BusinessEntity.model_validate(entity.model_dump() | {"values": [entity.values[0], entity.values[0]]})
    with pytest.raises(ValidationError, match="blank"):
        QuestionRequest(question="   ", access_context=build_access())


@pytest.mark.parametrize(
    "updates",
    [
        {"connector_type": "BIGQUERY"},
        {"dimensions": {" ": "bad"}},
        {"dimensions": {"A": "same", "B": "same"}},
        {"table_name": "facts; DROP TABLE facts"},
        {"scope_value_allowlists": {"MISSING": ["A"]}},
        {"scope_value_allowlists": {}},
        {"scope_value_mappings": {"REGION": {"NORTH_AMERICA": ["UNKNOWN"]}}},
    ],
)
def test_physical_mapping_rejects_unsafe_or_incomplete_scope(updates):
    with pytest.raises(ValidationError):
        PhysicalConnectorMapping.model_validate(build_connector()._mapping.model_dump() | updates)


def test_physical_metric_and_ownership_contracts():
    mapping = build_connector()._mapping
    metric = mapping.metrics[0].model_dump()
    for update in [{"aggregation": "SUM", "amount_column": None}, {"aggregation": "AVERAGE"}]:
        with pytest.raises(ValidationError):
            PhysicalMetricMapping.model_validate(metric | update)
    for metrics in [
        [mapping.metrics[0], mapping.metrics[0]],
        [mapping.metrics[0].model_copy(update={"allowed_dimensions": {"MISSING"}})],
    ]:
        with pytest.raises(ValidationError):
            PhysicalConnectorMapping.model_validate(mapping.model_dump() | {"metrics": metrics})
    with pytest.raises(PhysicalMappingError):
        mapping.metric("missing")
    assert mapping.resolve_scope_values("REGION", set()) == set()
    registry = PhysicalMappingRegistry()
    registry.load()
    pack = registry.get("demo-telecom")
    with pytest.raises(PhysicalMappingError):
        pack.connector("missing")
    for connectors in [
        [mapping, mapping],
        [mapping, mapping.model_copy(update={"connector_id": "duplicate-owner"})],
    ]:
        with pytest.raises(ValidationError):
            TenantPhysicalMappingPack.model_validate(pack.model_dump() | {"connectors": connectors})


def test_semantic_to_physical_compatibility_detects_drift(domain):
    registry = PhysicalMappingRegistry()
    registry.load()
    first = domain.metrics[0]
    for update, expected in [
        ({"aggregation": "SUM"}, "AGGREGATION_MISMATCH"),
        ({"allowed_dimensions": []}, "DIMENSION_MAPPING_MISMATCH"),
        ({"source": first.source.model_copy(update={"connector_id": "unknown"})}, "MISSING_PHYSICAL_MAPPING"),
    ]:
        modified = domain.model_copy(update={"metrics": [first.model_copy(update=update)]})
        assert any(item.startswith(expected) for item in registry.validate_domain_pack(modified))


def test_factory_resolves_secrets_outside_composition_and_pins_effective_mapping(domain, monkeypatch):
    registry = PhysicalMappingRegistry()
    registry.load()
    calls = []

    class Secrets:
        def resolve(self, reference):
            from pydantic import SecretStr

            calls.append(reference)
            return SecretStr("postgresql://example.invalid")

    for direct in [None, "postgresql://example.invalid/direct"]:
        settings = Settings(
            data_backend=" POSTGRESQL ",
            postgres_dsn=direct,
            postgres_schema=" custom_schema ",
            postgres_table="facts",
        )
        connectors = build_connectors(
            settings=settings, domain_pack=domain, physical_mappings=registry, secret_resolver=Secrets()
        )
        assert len(connectors) == 2
        assert all(
            c._mapping.schema_name == "custom_schema" and c._mapping.table_name == "facts" for c in connectors
        )
        assert all(
            c.descriptor.mapping_hash
            != registry.get(domain.tenant_id).connector_hash(c.descriptor.connector_id)
            for c in connectors
        )
    assert len(calls) == 2
    settings = Settings(
        data_backend="postgresql", postgres_dsn="postgresql://example.invalid", postgres_schema=None
    )
    assert build_connectors(
        settings=settings, domain_pack=domain, physical_mappings=registry, secret_resolver=Secrets()
    )
    with pytest.raises(ValidationError):
        Settings(postgres_table="a.b")
    assert Settings(
        cors_allowed_origins=[" ", "https://example.com/", "https://example.com"]
    ).cors_allowed_origins == ["https://example.com"]
    with pytest.raises(ValidationError):
        Settings(data_backend=3)


def test_connector_registry_rejects_writes_and_duplicate_ids():
    registry = ConnectorRegistry()
    connector = build_connector()
    connector.descriptor = connector.descriptor.model_copy(update={"read_only": False})
    with pytest.raises(ConnectorRegistryError, match="read-only"):
        registry.register(connector)
    connector.descriptor = connector.descriptor.model_copy(update={"read_only": True})
    registry.register(connector)
    with pytest.raises(ConnectorRegistryError, match="already registered"):
        registry.register(connector)
    with pytest.raises(ConnectorRegistryError, match="not registered"):
        registry.get("missing")
    assert registry.connectors() == (connector,)
    assert registry.descriptors()[0]["connector_id"] == connector.descriptor.connector_id


def test_context_and_claim_contracts_do_not_implicitly_approve_unverified_evidence():
    query = MemoryQuery(tenant_id="tenant", memory_types={"BUSINESS_DEFINITION"})
    assert query.limit == 20 and query.effective_at is None
    for limit in [0, 101]:
        with pytest.raises(ValidationError):
            MemoryQuery(tenant_id="tenant", limit=limit)
    evidence = MemoryEvidence(
        memory_id=uuid4(),
        memory_type="BUSINESS_DEFINITION",
        source_id="approved-catalog",
        content="Test definition",
        status="APPROVED",
        authority_level=1,
    )
    assert MemoryEvidence.model_validate_json(evidence.model_dump_json()) == evidence
    coverage = ContextCoverageReceipt(
        tenant_id="tenant",
        domain_pack_version="1",
        partitions_requested=["metrics"],
        partitions_searched=[],
        incomplete_sources=["metrics"],
        coverage_status="INCOMPLETE",
    )
    assert coverage.created_at.tzinfo == UTC and coverage.incomplete_sources == ["metrics"]
    receipt = EvidenceReceipt(
        evidence_type="APPROVED_INTERNAL_KNOWLEDGE",
        tenant_id="tenant",
        source_id="catalog",
        source_timestamp=datetime.now(UTC),
        classification="INTERNAL",
        policy_decision_id="policy",
        payload_hash="test",
        payload={},
    )
    claim = ApprovedClaim(
        claim_type="HYPOTHESIS",
        statement="Unverified hypothesis",
        evidence_ids=[receipt.evidence_id],
        confidence="LOW",
    )
    assert not claim.allowed_for_response
    assert claim.causality_status == "NOT_APPLICABLE"
    assert receipt.retrieved_at.tzinfo == UTC
