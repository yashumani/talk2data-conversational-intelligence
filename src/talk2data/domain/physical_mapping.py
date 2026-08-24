from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import date, datetime
from enum import Enum
from importlib.resources import files
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from talk2data.domain.models import (
    AccessContext,
    MetricAggregation,
    TenantDomainPack,
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_REFERENCE = re.compile(r"^env://[A-Z_][A-Z0-9_]*$")


class PhysicalMappingError(RuntimeError):
    """Raised when a governed semantic-to-physical mapping is invalid."""


class PhysicalMappingNotFoundError(PhysicalMappingError):
    """Raised when no approved physical mapping exists for a tenant or connector."""


class PhysicalMetricMapping(BaseModel):
    """Maps one governed metric to approved physical source fields."""

    model_config = ConfigDict(extra="forbid")

    metric_id: str = Field(min_length=1, max_length=128)
    source_value: str = Field(min_length=1, max_length=256)
    aggregation: MetricAggregation
    amount_column: str | None = None
    numerator_column: str | None = None
    denominator_column: str | None = None
    allowed_dimensions: set[str] = Field(default_factory=set)

    @field_validator("amount_column", "numerator_column", "denominator_column")
    @classmethod
    def validate_optional_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_identifier(value, "physical metric column")

    @field_validator("allowed_dimensions", mode="after")
    @classmethod
    def normalize_dimensions(cls, values: set[str]) -> set[str]:
        return {value.strip().upper() for value in values if value.strip()}

    @model_validator(mode="after")
    def validate_aggregation_columns(self) -> Self:
        if self.aggregation == MetricAggregation.RATIO:
            if self.numerator_column is None or self.denominator_column is None:
                raise ValueError("ratio mappings require numerator_column and denominator_column")
        elif self.aggregation == MetricAggregation.SUM:
            if self.amount_column is None:
                raise ValueError("SUM mappings require amount_column")
        else:
            raise ValueError("the PostgreSQL physical mapping currently supports only SUM and RATIO")
        return self

    def required_columns(self) -> set[str]:
        return {
            column
            for column in (
                self.amount_column,
                self.numerator_column,
                self.denominator_column,
            )
            if column is not None
        }


class PhysicalConnectorMapping(BaseModel):
    """Approved physical object and column contract for one connector."""

    model_config = ConfigDict(extra="forbid")

    connector_id: str = Field(min_length=1, max_length=128)
    connector_type: str = "POSTGRESQL"
    schema_name: str
    table_name: str
    secret_ref: str
    fact_date_column: str
    period_end_column: str
    metric_id_column: str
    dimensions: dict[str, str]
    scope_value_allowlists: dict[str, set[str]] = Field(default_factory=dict)
    scope_value_mappings: dict[str, dict[str, set[str]]] = Field(default_factory=dict)
    metrics: list[PhysicalMetricMapping]
    maximum_rows: int = Field(default=1_000, ge=1, le=10_000)
    query_timeout_seconds: int = Field(default=60, ge=1, le=1_800)
    expected_refresh: str = "Source-managed"

    @field_validator(
        "schema_name",
        "table_name",
        "fact_date_column",
        "period_end_column",
        "metric_id_column",
    )
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return _require_identifier(value, "physical mapping identifier")

    @field_validator("secret_ref")
    @classmethod
    def validate_secret_reference(cls, value: str) -> str:
        normalized = value.strip()
        if _SECRET_REFERENCE.fullmatch(normalized) is None:
            raise ValueError("secret_ref must use env://NAME and cannot contain a credential")
        return normalized

    @field_validator("connector_type")
    @classmethod
    def normalize_connector_type(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized != "POSTGRESQL":
            raise ValueError("this physical mapping slice supports POSTGRESQL connectors")
        return normalized

    @field_validator("dimensions", mode="after")
    @classmethod
    def normalize_dimensions(cls, values: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for semantic_id, physical_column in values.items():
            key = semantic_id.strip().upper()
            if not key:
                raise ValueError("dimension IDs cannot be blank")
            normalized[key] = _require_identifier(physical_column, "dimension column")
        if len(normalized.values()) != len(set(normalized.values())):
            raise ValueError("each semantic dimension must map to a distinct physical column")
        return normalized

    @field_validator("scope_value_allowlists", mode="after")
    @classmethod
    def normalize_scope_values(cls, values: dict[str, set[str]]) -> dict[str, set[str]]:
        return {
            dimension.strip().upper(): {value.strip().upper() for value in allowed_values if value.strip()}
            for dimension, allowed_values in values.items()
            if dimension.strip()
        }

    @field_validator("scope_value_mappings", mode="after")
    @classmethod
    def normalize_scope_mappings(
        cls,
        values: dict[str, dict[str, set[str]]],
    ) -> dict[str, dict[str, set[str]]]:
        return {
            dimension.strip().upper(): {
                access_value.strip().upper(): {
                    physical_value.strip().upper()
                    for physical_value in physical_values
                    if physical_value.strip()
                }
                for access_value, physical_values in mappings.items()
                if access_value.strip()
            }
            for dimension, mappings in values.items()
            if dimension.strip()
        }

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        metric_ids = [metric.metric_id for metric in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("duplicate metric mappings are not allowed within a connector")

        known_dimensions = set(self.dimensions)
        for metric in self.metrics:
            unknown = metric.allowed_dimensions - known_dimensions
            if unknown:
                raise ValueError(
                    f"metric {metric.metric_id!r} references unmapped dimensions: "
                    + ", ".join(sorted(unknown))
                )

        scope_dimensions = set(self.scope_value_allowlists) | set(self.scope_value_mappings)
        unknown_scope_dimensions = scope_dimensions - known_dimensions
        if unknown_scope_dimensions:
            raise ValueError(
                "scope rules reference unmapped dimensions: " + ", ".join(sorted(unknown_scope_dimensions))
            )
        for dimension, mappings in self.scope_value_mappings.items():
            allowed_values = self.scope_value_allowlists.get(dimension, set())
            if not allowed_values:
                raise ValueError(f"scope mappings for {dimension!r} require a physical value allowlist")
            mapped_values = {
                physical_value for physical_values in mappings.values() for physical_value in physical_values
            }
            unknown_values = mapped_values - allowed_values
            if unknown_values:
                raise ValueError(
                    f"scope mappings for {dimension!r} contain values outside the allowlist: "
                    + ", ".join(sorted(unknown_values))
                )
        return self

    @property
    def metric_ids(self) -> set[str]:
        return {metric.metric_id for metric in self.metrics}

    def metric(self, metric_id: str) -> PhysicalMetricMapping:
        for metric in self.metrics:
            if metric.metric_id == metric_id:
                return metric
        raise PhysicalMappingNotFoundError(
            f"connector {self.connector_id!r} has no mapping for metric {metric_id!r}"
        )

    def resolve_scope_values(self, dimension_id: str, access_values: set[str]) -> set[str]:
        dimension = dimension_id.strip().upper()
        if dimension not in self.dimensions:
            return set()
        normalized_values = {value.strip().upper() for value in access_values if value.strip()}
        if not normalized_values:
            return set()

        allowed_values = self.scope_value_allowlists.get(dimension, set())
        mappings = self.scope_value_mappings.get(dimension, {})
        resolved: set[str] = set()
        for access_value in normalized_values:
            if access_value in mappings:
                resolved.update(mappings[access_value])
            elif access_value in allowed_values:
                resolved.add(access_value)
            else:
                raise PhysicalMappingError(
                    f"access scope for dimension {dimension!r} has no approved physical mapping"
                )
        return resolved

    def required_columns(self) -> set[str]:
        columns = {
            self.fact_date_column,
            self.period_end_column,
            self.metric_id_column,
        }
        for metric in self.metrics:
            columns.update(metric.required_columns())
            columns.update(self.dimensions[dimension] for dimension in metric.allowed_dimensions)
        return columns

    def public_view(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "connector_type": self.connector_type,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "fact_date_column": self.fact_date_column,
            "period_end_column": self.period_end_column,
            "metric_id_column": self.metric_id_column,
            "dimensions": _canonicalize(self.dimensions),
            "scope_value_allowlists": _canonicalize(self.scope_value_allowlists),
            "scope_value_mappings": _canonicalize(self.scope_value_mappings),
            "metrics": [_canonicalize(metric) for metric in self.metrics],
            "maximum_rows": self.maximum_rows,
            "query_timeout_seconds": self.query_timeout_seconds,
            "expected_refresh": self.expected_refresh,
            "secret_provider": self.secret_ref.split("://", 1)[0],
        }


class TenantPhysicalMappingPack(BaseModel):
    """Versioned tenant mapping from semantic identifiers to physical data objects."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    status: str = "APPROVED"
    effective_from: datetime
    connectors: list[PhysicalConnectorMapping]

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_unique_contracts(self) -> Self:
        connector_ids = [connector.connector_id for connector in self.connectors]
        if len(connector_ids) != len(set(connector_ids)):
            raise ValueError("duplicate connector IDs are not allowed")

        metric_owners: dict[str, str] = {}
        for connector in self.connectors:
            for metric_id in connector.metric_ids:
                existing = metric_owners.get(metric_id)
                if existing is not None:
                    raise ValueError(
                        f"metric {metric_id!r} is mapped by both {existing!r} and {connector.connector_id!r}"
                    )
                metric_owners[metric_id] = connector.connector_id
        return self

    def connector(self, connector_id: str) -> PhysicalConnectorMapping:
        for connector in self.connectors:
            if connector.connector_id == connector_id:
                return connector
        raise PhysicalMappingNotFoundError(
            f"tenant {self.tenant_id!r} has no physical mapping for connector {connector_id!r}"
        )

    def canonical_hash(self) -> str:
        payload = json.dumps(
            _canonicalize(self),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def connector_hash(self, connector_id: str) -> str:
        return physical_connector_hash(
            tenant_id=self.tenant_id,
            version=self.version,
            connector=self.connector(connector_id),
        )


def physical_connector_hash(
    *,
    tenant_id: str,
    version: str,
    connector: PhysicalConnectorMapping,
) -> str:
    payload = _canonicalize(
        {
            "tenant_id": tenant_id,
            "version": version,
            "connector": connector,
        }
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PhysicalMappingRegistry:
    """Loads and validates approved tenant physical mappings."""

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory
        self._packs: dict[str, TenantPhysicalMappingPack] = {}

    def load(self) -> None:
        paths = list(self._iter_paths())
        if not paths:
            raise PhysicalMappingError("no physical mapping files were found")

        packs: dict[str, TenantPhysicalMappingPack] = {}
        for path in paths:
            raw = self._load_yaml(path)
            pack = TenantPhysicalMappingPack.model_validate(raw)
            if pack.status != "APPROVED":
                continue
            existing = packs.get(pack.tenant_id)
            if existing is not None:
                raise PhysicalMappingError(
                    f"multiple approved physical mapping packs found for tenant {pack.tenant_id!r}: "
                    f"{existing.version!r} and {pack.version!r}"
                )
            packs[pack.tenant_id] = pack

        if not packs:
            raise PhysicalMappingError("no approved physical mapping packs were loaded")
        self._packs = packs

    def get(self, tenant_id: str) -> TenantPhysicalMappingPack:
        try:
            return self._packs[tenant_id]
        except KeyError as exc:
            raise PhysicalMappingNotFoundError(
                f"no approved physical mapping pack exists for tenant {tenant_id!r}"
            ) from exc

    def validate_domain_pack(self, domain_pack: TenantDomainPack) -> list[str]:
        mapping_pack = self.get(domain_pack.tenant_id)
        failures: list[str] = []
        for metric in domain_pack.metrics:
            if metric.source.status.value != "AVAILABLE":
                continue
            try:
                connector = mapping_pack.connector(metric.source.connector_id)
                physical_metric = connector.metric(metric.id)
            except PhysicalMappingNotFoundError:
                failures.append(f"MISSING_PHYSICAL_MAPPING:{metric.id}")
                continue
            if physical_metric.aggregation != metric.aggregation:
                failures.append(f"AGGREGATION_MISMATCH:{metric.id}")
            if physical_metric.allowed_dimensions != set(metric.allowed_dimensions):
                failures.append(f"DIMENSION_MAPPING_MISMATCH:{metric.id}")
        return failures

    def list_tenants(self) -> list[str]:
        return sorted(self._packs)

    @property
    def loaded(self) -> bool:
        return bool(self._packs)

    def _iter_paths(self) -> Iterable[Path]:
        if self._directory is not None:
            yield from sorted(self._directory.glob("*.yaml"))
            yield from sorted(self._directory.glob("*.yml"))
            return

        packaged = files("talk2data").joinpath("resources", "physical_mappings")
        for child in sorted(packaged.iterdir(), key=lambda item: item.name):
            if child.name.endswith((".yaml", ".yml")):
                yield Path(str(child))

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise PhysicalMappingError(f"failed to read physical mapping {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise PhysicalMappingError(f"physical mapping {path} must contain a YAML object")
        return raw


class PhysicalMappingAccessRequest(BaseModel):
    access_context: AccessContext


class PhysicalMappingConnectorRequest(PhysicalMappingAccessRequest):
    connector_id: str = Field(min_length=1, max_length=128)


class PhysicalMappingPackResponse(BaseModel):
    tenant_id: str
    version: str
    mapping_hash: str
    connectors: list[dict[str, Any]]
    validation_failures: list[str] = Field(default_factory=list)


class PhysicalMappingConnectorResponse(BaseModel):
    tenant_id: str
    version: str
    mapping_hash: str
    connector: dict[str, Any]


def _canonicalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonicalize(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        items = [_canonicalize(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _require_identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a simple SQL identifier")
    return normalized
