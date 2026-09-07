"""Approved canonical daily-fact view contracts for internal BigQuery execution."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from talk2data.core.bigquery_config import identifier, qualified_object
from talk2data.domain.models import (
    ClassificationLevel,
    MetricAggregation,
    MetricValueType,
    TenantDomainPack,
    TimeGrain,
)


class BigQueryMetricMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str
    source_value: str = Field(min_length=1, max_length=256)
    semantic_version: str = Field(min_length=1)
    aggregation: MetricAggregation
    value_type: MetricValueType
    unit: str
    classification: ClassificationLevel
    supported_time_grains: set[TimeGrain] = Field(min_length=1)
    currency: str | None = None
    amount_column: str | None = None
    numerator_column: str | None = None
    denominator_column: str | None = None
    allowed_dimensions: set[str] = Field(default_factory=set)

    @field_validator("metric_id")
    @classmethod
    def validate_metric(cls, value: str) -> str:
        return identifier(value)

    @field_validator("amount_column", "numerator_column", "denominator_column")
    @classmethod
    def validate_column(cls, value: str | None) -> str | None:
        return None if value is None else identifier(value)

    @model_validator(mode="after")
    def validate_aggregation(self) -> Self:
        if self.aggregation == MetricAggregation.SUM and self.amount_column:
            return self
        if self.aggregation == MetricAggregation.RATIO and self.numerator_column and self.denominator_column:
            return self
        raise ValueError("Daily fact mappings require SUM or RATIO with explicit measure columns.")

    def measure_columns(self) -> set[str]:
        return {c for c in (self.amount_column, self.numerator_column, self.denominator_column) if c}


class BigQueryMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=128)
    connector_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1)
    view: str
    allowed_references: set[str] = Field(min_length=1)
    tenant_column: str
    business_unit_column: str
    date_column: str
    snapshot_column: str
    metric_column: str
    dimensions: dict[str, str]
    dimension_classifications: dict[str, ClassificationLevel]
    metrics: list[BigQueryMetricMapping] = Field(min_length=1)

    @field_validator("view")
    @classmethod
    def validate_view(cls, value: str) -> str:
        return qualified_object(value)

    @field_validator("allowed_references")
    @classmethod
    def validate_references(cls, values: set[str]) -> set[str]:
        return {qualified_object(value) for value in values}

    @field_validator(
        "tenant_column", "business_unit_column", "date_column", "snapshot_column", "metric_column"
    )
    @classmethod
    def validate_column(cls, value: str) -> str:
        return identifier(value)

    @field_validator("dimensions")
    @classmethod
    def validate_dimensions(cls, values: dict[str, str]) -> dict[str, str]:
        if any(key != key.upper() or key.startswith("_") or key == "VALUE" for key in values):
            raise ValueError("Semantic dimension IDs must be uppercase and cannot use result aliases.")
        return {identifier(key): identifier(value) for key, value in values.items()}

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.view not in self.allowed_references or "REGION" not in self.dimensions:
            raise ValueError("The approved view and mandatory REGION binding must be present.")
        if len({m.metric_id for m in self.metrics}) != len(self.metrics):
            raise ValueError("Duplicate metric mapping.")
        if any(m.allowed_dimensions - self.dimensions.keys() for m in self.metrics):
            raise ValueError("A metric refers to an unmapped dimension.")
        if self.dimension_classifications.keys() != self.dimensions.keys():
            raise ValueError("Every mapped dimension requires its approved classification.")
        columns = [
            self.tenant_column,
            self.business_unit_column,
            self.date_column,
            self.snapshot_column,
            self.metric_column,
            *self.dimensions.values(),
        ]
        column_keys = {column.casefold() for column in columns}
        if len(columns) != len(column_keys):
            raise ValueError("Scope, metadata and dimension columns must be distinct.")
        if any(column.casefold() in column_keys for m in self.metrics for column in m.measure_columns()):
            raise ValueError("Measure columns cannot override scope, metadata or dimension columns.")
        return self

    def validate_domain(self, pack: TenantDomainPack) -> None:
        if (
            pack.tenant_id != self.tenant_id
            or pack.default_timezone != "UTC"
            or pack.default_calendar != "GREGORIAN"
        ):
            raise ValueError("This internal increment requires an exact tenant and Gregorian UTC daily view.")
        if (
            pack.status != "APPROVED"
            or pack.effective_from.tzinfo is None
            or pack.effective_from > datetime.now(UTC)
        ):
            raise ValueError("Internal semantics must be approved and currently effective.")
        entities = {entity.id: entity.classification for entity in pack.entities}
        if any(entities.get(key) != value for key, value in self.dimension_classifications.items()):
            raise ValueError("Physical and semantic dimension classifications differ.")
        definitions = {m.id: m for m in pack.metrics}
        for mapping in self.metrics:
            metric = definitions.get(mapping.metric_id)
            if metric is None or metric.source.connector_id != self.connector_id:
                raise ValueError("Physical metric is not bound to its approved semantic connector.")
            for field in ("semantic_version", "aggregation", "value_type", "unit", "classification"):
                if getattr(mapping, field) != getattr(metric, field):
                    raise ValueError("Physical and semantic metric contracts differ.")
            if mapping.currency != (
                pack.default_currency if metric.value_type == MetricValueType.CURRENCY else None
            ):
                raise ValueError("Physical and semantic currency contracts differ.")
            if mapping.allowed_dimensions != set(metric.allowed_dimensions):
                raise ValueError("Physical and semantic dimension contracts differ.")
            if mapping.supported_time_grains != set(metric.supported_time_grains):
                raise ValueError("Physical and semantic time-grain contracts differ.")

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        payload["allowed_references"] = sorted(self.allowed_references)
        for metric in payload["metrics"]:
            metric["allowed_dimensions"] = sorted(metric["allowed_dimensions"])
            metric["supported_time_grains"] = sorted(metric["supported_time_grains"])
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class BigQueryCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mappings: list[BigQueryMapping] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_bindings(self) -> Self:
        keys = [(m.tenant_id, m.connector_id) for m in self.mappings]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate tenant/connector binding.")
        return self

    @classmethod
    def load(cls, path: Path) -> BigQueryCatalog:
        return cls.model_validate_json(path.read_bytes())
