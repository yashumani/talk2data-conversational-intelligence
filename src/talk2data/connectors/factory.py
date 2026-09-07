from __future__ import annotations

from talk2data.connectors.base import DataConnector
from talk2data.connectors.demo_sqlite import DemoSQLiteConnector
from talk2data.connectors.postgres import PostgreSQLConnector
from talk2data.core.config import DataBackend, Settings
from talk2data.domain.models import TenantDomainPack
from talk2data.domain.physical_mapping import (
    PhysicalConnectorMapping,
    PhysicalMappingRegistry,
    physical_connector_hash,
)
from talk2data.services.secrets import SecretResolver


def build_connectors(
    *,
    settings: Settings,
    domain_pack: TenantDomainPack,
    physical_mappings: PhysicalMappingRegistry,
    secret_resolver: SecretResolver,
) -> list[DataConnector]:
    metric_groups = _available_metric_groups(domain_pack)
    if settings.data_backend == DataBackend.POSTGRESQL:
        mapping_pack = physical_mappings.get(domain_pack.tenant_id)
        connectors: list[DataConnector] = []
        for connector_id in sorted(metric_groups):
            mapping = mapping_pack.connector(connector_id)
            effective_mapping = _apply_physical_object_overrides(mapping, settings)
            dsn = (
                settings.postgres_dsn.get_secret_value()
                if settings.postgres_dsn is not None
                else secret_resolver.resolve(effective_mapping.secret_ref).get_secret_value()
            )
            connectors.append(
                PostgreSQLConnector(
                    mapping=effective_mapping,
                    mapping_version=mapping_pack.version,
                    mapping_hash=physical_connector_hash(
                        tenant_id=mapping_pack.tenant_id,
                        version=mapping_pack.version,
                        connector=effective_mapping,
                    ),
                    dsn=dsn,
                    maximum_rows=settings.postgres_maximum_rows,
                    query_timeout_seconds=settings.postgres_query_timeout_seconds,
                    connect_timeout_seconds=settings.postgres_connect_timeout_seconds,
                )
            )
        return connectors

    demo_database_path = settings.database_path.with_name("demo-telecom.db")
    return [
        DemoSQLiteConnector(
            connector_id=connector_id,
            database_path=demo_database_path,
            allowed_metric_ids=metric_ids,
        )
        for connector_id, metric_ids in sorted(metric_groups.items())
    ]


def _available_metric_groups(domain_pack: TenantDomainPack) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    for metric in domain_pack.metrics:
        if metric.source.status.value != "AVAILABLE":
            continue
        groups.setdefault(metric.source.connector_id, set()).add(metric.id)
    return groups


def _apply_physical_object_overrides(
    mapping: PhysicalConnectorMapping,
    settings: Settings,
) -> PhysicalConnectorMapping:
    update: dict[str, object] = {}
    if settings.postgres_schema is not None:
        update["schema_name"] = settings.postgres_schema
    if settings.postgres_table is not None:
        update["table_name"] = settings.postgres_table
    if not update:
        return mapping
    payload = mapping.model_dump(mode="python")
    payload.update(update)
    return PhysicalConnectorMapping.model_validate(payload)
