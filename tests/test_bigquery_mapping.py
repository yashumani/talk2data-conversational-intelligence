from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from talk2data.core.bigquery_config import identifier, qualified_object
from talk2data.core.internal_config import IdentitySettings
from talk2data.domain.bigquery_mapping import BigQueryCatalog, BigQueryMapping
from talk2data.domain.domain_pack import DomainPackRegistry
from tests.internal_support import mapping, private_config, settings


@pytest.mark.parametrize("value", ["", "a` UNION SELECT", "table.*", "x-y", "x" * 129])
def test_untrusted_identifiers_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        identifier(value)


@pytest.mark.parametrize("value", ["dataset.view", "project.dataset.*", "a.b.c", "project.dataset.v;DROP"])
def test_objects_must_be_exact_and_qualified(value: str) -> None:
    with pytest.raises(ValueError):
        qualified_object(value)


@pytest.mark.parametrize(
    "updates",
    [
        {"billing_project": ""},
        {"billing_project": "PROJECT"},
        {"maximum_bytes_billed": 0},
        {"maximum_rows": 1001},
        {"query_timeout_seconds": 301},
        {"api_timeout_seconds": 31},
    ],
)
def test_cloud_limits_cannot_be_disabled(updates: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        settings(**updates)


@pytest.mark.parametrize(
    "change",
    [
        "view_allowlist",
        "region",
        "duplicate_metric",
        "unmapped_dimension",
        "classification_missing",
        "reserved_alias",
        "lowercase_alias",
        "column_collision",
        "measure_collision",
        "bad_identifier",
        "unsupported_aggregate",
        "missing_measure",
    ],
)
def test_unsafe_mapping_contracts_fail_before_any_cloud_use(change: str) -> None:
    data = mapping().model_dump(mode="json")
    if change == "view_allowlist":
        data["allowed_references"] = ["example-project.analytics.other"]
    elif change == "region":
        del data["dimensions"]["REGION"]
    elif change == "duplicate_metric":
        data["metrics"].append(data["metrics"][0])
    elif change == "unmapped_dimension":
        data["metrics"][0]["allowed_dimensions"].append("UNKNOWN")
    elif change == "classification_missing":
        data["dimension_classifications"] = {}
    elif change in {"reserved_alias", "lowercase_alias"}:
        data["dimensions"]["VALUE" if change == "reserved_alias" else "region"] = "extra"
    elif change == "column_collision":
        data["tenant_column"] = data["business_unit_column"].upper()
    elif change == "measure_collision":
        data["metrics"][1]["amount_column"] = data["tenant_column"]
    elif change == "bad_identifier":
        data["date_column"] = "x; SELECT 1"
    elif change == "unsupported_aggregate":
        data["metrics"][1]["aggregation"] = "COUNT"
    else:
        data["metrics"][0]["denominator_column"] = None
    with pytest.raises(ValidationError):
        BigQueryMapping.model_validate(data)


@pytest.mark.parametrize(
    "change",
    [
        "tenant",
        "calendar",
        "timezone",
        "future",
        "naive",
        "draft",
        "dimension_classification",
        "missing_metric",
        "connector",
        "semantic_version",
        "currency",
        "dimensions",
        "metric_classification",
    ],
)
def test_semantic_drift_fails_closed(tmp_path: Path, change: str) -> None:
    config = private_config(tmp_path)
    registry = DomainPackRegistry(config.domain_pack_directory)
    registry.load()
    pack = registry.get("demo-telecom").model_copy(deep=True)
    contract = mapping()
    contract.validate_domain(pack)
    if change == "tenant":
        pack.tenant_id = "different"
    elif change == "calendar":
        pack.default_calendar = "CORPORATE_FISCAL"
    elif change == "timezone":
        pack.default_timezone = "America/New_York"
    elif change == "future":
        pack.effective_from = datetime.now(UTC) + timedelta(days=1)
    elif change == "naive":
        pack.effective_from = datetime(2020, 1, 1)
    elif change == "draft":
        pack.status = "DRAFT"
    elif change == "dimension_classification":
        pack.entities = []
    elif change == "missing_metric":
        pack.metrics = []
    elif change == "connector":
        pack.metrics[0].source.connector_id = "other"
    elif change == "semantic_version":
        pack.metrics[0].semantic_version = "99"
    elif change == "currency":
        contract = mapping(metrics=[m.model_copy(update={"currency": "USD"}) for m in contract.metrics])
    elif change == "dimensions":
        pack.metrics[0].allowed_dimensions = ["REGION"]
    else:
        pack.metrics[0] = pack.metrics[0].model_copy(update={"classification": "RESTRICTED"})
    with pytest.raises(ValueError):
        contract.validate_domain(pack)


def test_catalog_rejects_ambiguous_bindings_and_hash_is_order_independent() -> None:
    first = mapping()
    with pytest.raises(ValidationError, match="Duplicate"):
        BigQueryCatalog(mappings=[first, first])
    second = mapping(dimensions=dict(reversed(list(first.dimensions.items()))))
    assert first.fingerprint() == second.fingerprint()


@pytest.mark.parametrize(
    "change", [None, "algorithm", "issuer", "jwks_url", "maximum_token_lifetime_seconds"]
)
def test_iap_trust_root_and_lifetime_are_pinned(change: str | None) -> None:
    data = {
        "issuer": "https://cloud.google.com/iap",
        "audience": "/projects/123/global/backendServices/456",
        "jwks_url": "https://www.gstatic.com/iap/verify/public_key-jwk",
        "algorithm": "ES256",
        "token_header": "x-goog-iap-jwt-assertion",
        "maximum_token_lifetime_seconds": 660,
    }
    if change is None:
        assert IdentitySettings.model_validate(data).algorithm == "ES256"
    else:
        data[change] = {"algorithm": "RS256", "maximum_token_lifetime_seconds": 661}.get(
            change, "https://untrusted.example.test"
        )
        with pytest.raises(ValidationError, match="Signed IAP"):
            IdentitySettings.model_validate(data)
