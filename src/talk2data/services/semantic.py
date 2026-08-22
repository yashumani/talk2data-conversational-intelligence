from __future__ import annotations

import hashlib
import json

from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import (
    AccessContext,
    BusinessEntity,
    MetricDefinition,
    MetricResolutionResponse,
    TenantDomainPack,
)
from talk2data.services.policy import PolicyEngine


class SemanticRegistryError(RuntimeError):
    """Base error for governed semantic resolution."""


class MetricNotFoundError(SemanticRegistryError):
    """Raised when a metric is not present in the tenant's approved semantic registry."""


class SemanticAccessDeniedError(SemanticRegistryError):
    """Raised when the access context cannot read a semantic definition."""


class DimensionNotAllowedError(SemanticRegistryError):
    """Raised when a dimension is unknown, unauthorized, or invalid for a metric."""


class SemanticRegistry:
    """Resolves versioned metric and dimension contracts from approved Domain Packs."""

    def __init__(self, domain_packs: DomainPackRegistry, policy: PolicyEngine) -> None:
        self._domain_packs = domain_packs
        self._policy = policy

    def resolve_metric(
        self,
        access: AccessContext,
        metric_id: str,
    ) -> tuple[TenantDomainPack, MetricDefinition]:
        data_policy = self._policy.can_read_data(access)
        if not data_policy.allowed:
            raise SemanticAccessDeniedError("data-definition access is not allowed")

        pack = self._domain_packs.get(access.tenant_id)
        normalized_metric_id = metric_id.strip().upper()
        metric = next((item for item in pack.metrics if item.id == normalized_metric_id), None)
        if metric is None:
            raise MetricNotFoundError(
                f"metric {normalized_metric_id!r} is not registered for tenant {access.tenant_id!r}"
            )

        classification_policy = self._policy.can_access_classification(
            access,
            metric.classification,
        )
        if not classification_policy.allowed:
            raise SemanticAccessDeniedError("metric definition is above the user's clearance")
        return pack, metric

    def resolve_dimensions(
        self,
        *,
        access: AccessContext,
        pack: TenantDomainPack,
        metric: MetricDefinition,
        dimension_ids: list[str],
    ) -> list[BusinessEntity]:
        entities = {entity.id: entity for entity in pack.entities}
        resolved: list[BusinessEntity] = []
        seen: set[str] = set()
        for raw_dimension_id in dimension_ids:
            dimension_id = raw_dimension_id.strip().upper()
            if dimension_id in seen:
                continue
            seen.add(dimension_id)
            if dimension_id not in metric.allowed_dimensions:
                raise DimensionNotAllowedError(
                    f"dimension {dimension_id!r} is not allowed for metric {metric.id!r}"
                )
            entity = entities.get(dimension_id)
            if entity is None:
                raise DimensionNotAllowedError(
                    f"dimension {dimension_id!r} is not registered for tenant {pack.tenant_id!r}"
                )
            policy = self._policy.can_access_classification(access, entity.classification)
            if not policy.allowed:
                raise SemanticAccessDeniedError(f"dimension {dimension_id!r} is above the user's clearance")
            resolved.append(entity)
        return resolved

    @staticmethod
    def semantic_snapshot_hash(pack: TenantDomainPack, metric: MetricDefinition) -> str:
        payload = {
            "tenant_id": pack.tenant_id,
            "domain_pack_version": pack.version,
            "calendar": pack.default_calendar,
            "currency": pack.default_currency,
            "timezone": pack.default_timezone,
            "metric": metric.model_dump(mode="json"),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def resolve_metric_response(
        self,
        access: AccessContext,
        metric_id: str,
    ) -> MetricResolutionResponse:
        pack, metric = self.resolve_metric(access, metric_id)
        return MetricResolutionResponse(
            domain_pack_version=pack.version,
            semantic_snapshot_hash=self.semantic_snapshot_hash(pack, metric),
            metric=metric,
        )
