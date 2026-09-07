"""Synthetic private configuration and a recording cloud port for internal contract tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

import yaml

from talk2data.connectors.base import StructuredQueryPlan
from talk2data.core.bigquery_config import BigQuerySettings
from talk2data.core.internal_config import IdentitySettings, InternalRuntimeConfig
from talk2data.domain.bigquery_mapping import BigQueryMapping
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import AccessContext
from talk2data.services.bigquery_port import CloudResult, DryRun
from talk2data.services.bigquery_sql import BigQueryStatement


def access(subject: str = "analyst", tenant: str = "demo-telecom") -> AccessContext:
    return AccessContext(
        tenant_id=tenant,
        user_id=subject,
        roles={"BI_MANAGER"},
        departments={"SALES"},
        regions={"NORTHEAST"},
        business_units={"CONSUMER"},
        classification_clearance="CONFIDENTIAL",
        permitted_actions={"ASK_BUSINESS_QUESTIONS", "READ_AGGREGATED_DATA"},
    )


def settings(**updates: Any) -> BigQuerySettings:
    return BigQuerySettings.model_validate(
        {"billing_project": "example-project", "location": "US", "maximum_bytes_billed": 1_000_000, **updates}
    )


def mapping(**updates: Any) -> BigQueryMapping:
    definitions = DomainPackRegistry()
    definitions.load()
    metrics = []
    for metric in definitions.get("demo-telecom").metrics[:2]:
        metrics.append(
            {
                "metric_id": metric.id,
                "source_value": metric.id,
                "semantic_version": metric.semantic_version,
                "aggregation": metric.aggregation,
                "value_type": metric.value_type,
                "unit": metric.unit,
                "classification": metric.classification,
                "supported_time_grains": metric.supported_time_grains,
                "allowed_dimensions": metric.allowed_dimensions,
                **(
                    {"amount_column": "amount"}
                    if metric.aggregation.value == "SUM"
                    else {"numerator_column": "numerator", "denominator_column": "denominator"}
                ),
            }
        )
    return BigQueryMapping.model_validate(
        {
            "tenant_id": "demo-telecom",
            "connector_id": "telecom_semantic_warehouse",
            "version": "1",
            "view": "example-project.analytics.approved_daily",
            "allowed_references": ["example-project.analytics.approved_daily"],
            "tenant_column": "tenant_id",
            "business_unit_column": "business_unit",
            "date_column": "fact_date",
            "snapshot_column": "source_updated_at",
            "metric_column": "metric_id",
            "dimensions": {
                "REGION": "region",
                "CHANNEL": "channel",
                "STORE": "store",
                "MARKET": "market",
                "PLAN": "plan",
            },
            "metrics": metrics,
            "dimension_classifications": {
                entity.id: entity.classification
                for entity in definitions.get("demo-telecom").entities
                if entity.id in {"REGION", "CHANNEL", "STORE", "MARKET", "PLAN"}
            },
            **updates,
        }
    )


def plan(**updates: Any) -> StructuredQueryPlan:
    return StructuredQueryPlan.model_validate(
        {
            "query_id": str(uuid4()),
            "decision_id": str(uuid4()),
            "plan_hash": "a" * 64,
            "tenant_id": "demo-telecom",
            "connector_id": "telecom_semantic_warehouse",
            "metric_id": "MOBILE_ACTIVATIONS",
            "semantic_version": "2.0",
            "value_type": "INTEGER",
            "aggregation": "SUM",
            "unit": "COUNT",
            "dimensions": ["REGION"],
            "time_window": {
                "preset": "PREVIOUS_COMPLETE_MONTH",
                "grain": "MONTH",
                "calendar": "GREGORIAN",
                "timezone": "UTC",
                "anchor_date": "2026-08-01",
            },
            "comparison": {"comparison_type": "NONE"},
            **updates,
        }
    )


def write_grants(path: Path, *entries: AccessContext) -> None:
    path.write_text(
        json.dumps(
            {
                "version": "1",
                "issuer": "https://identity.example.test",
                "bindings": [entry.model_dump(mode="json") for entry in entries],
            }
        )
    )


def private_config(tmp_path: Path) -> InternalRuntimeConfig:
    domain_dir = tmp_path / "domains"
    domain_dir.mkdir()
    registry = DomainPackRegistry()
    registry.load()
    pack = registry.get("demo-telecom").model_dump(mode="json")
    pack.update(default_calendar="GREGORIAN", default_timezone="UTC")
    for metric in pack["metrics"][2:]:
        metric["source"]["status"] = "UNAVAILABLE"
    (domain_dir / "synthetic.yaml").write_text(yaml.safe_dump(pack))
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"mappings": [mapping().model_dump(mode="json")]}))
    grants = tmp_path / "grants.json"
    write_grants(grants, access(), access("second-analyst"))
    return InternalRuntimeConfig(
        identity=IdentitySettings(
            issuer="https://identity.example.test",
            audience="talk2data-internal",
            jwks_url="https://identity.example.test/keys",
        ),
        bigquery=settings(),
        entitlements_path=grants,
        domain_pack_directory=domain_dir,
        bigquery_catalog_path=catalog,
    )


class RecordingCloud:
    def __init__(self) -> None:
        self.estimate = DryRun(1000, "US", "SELECT", frozenset({"example-project.analytics.approved_daily"}))
        self.statements: list[BigQueryStatement] = []
        self.jobs: list[str] = []
        self.cancellations: list[str] = []
        self.failure: Exception | None = None
        self.rows: list[dict[str, Any]] | None = None
        self.gate: Event | None = None
        self.started = Event()
        self.closed = False

    def validate_view(self, contract: BigQueryMapping) -> None:
        if self.failure:
            raise self.failure

    def dry_run(self, statement: BigQueryStatement) -> DryRun:
        self.statements.append(statement)
        if self.failure:
            raise self.failure
        return self.estimate

    def execute(self, statement: BigQueryStatement, job_id: str, cancelled: Event) -> CloudResult:
        self.jobs.append(job_id)
        self.started.set()
        if self.gate is not None:
            self.gate.wait(timeout=5)
        if cancelled.is_set():
            raise TimeoutError("Cancelled")
        rows = []
        for label, period in [("current", statement.current), ("comparison", statement.comparison)]:
            if period is None:
                continue
            days = (period.end - period.start).days + 1
            metric = next(p.value for p in statement.parameters if p.name == "metric")
            rows.append(
                {
                    "_period": label,
                    "_start": period.start,
                    "_end": period.end,
                    "_days": days,
                    "_snapshot": datetime(2026, 7, 31, tzinfo=UTC),
                    "_invalid": 0,
                    "value": 0.01 if metric == "POSTPAID_CHURN" else days * 100,
                    "REGION": "NORTHEAST",
                    "CHANNEL": "RETAIL",
                    "MARKET": "NEW_JERSEY",
                    "PLAN": "UNLIMITED",
                    "STORE": "STORE_001",
                }
            )
        if self.rows is not None:
            rows = self.rows
        return CloudResult(
            job_id,
            "US",
            "example-project",
            rows,
            len(rows),
            1000,
            1000,
            False,
            datetime(2026, 8, 1, tzinfo=UTC),
            datetime(2026, 8, 1, tzinfo=UTC),
        )

    def cancel(self, job_id: str) -> bool:
        self.cancellations.append(job_id)
        if self.gate:
            self.gate.set()
        return True

    def close(self) -> None:
        self.closed = True
