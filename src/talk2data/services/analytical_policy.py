"""Source-neutral validation for governed internal analytical plans."""

from __future__ import annotations

from talk2data.connectors.base import StructuredQueryPlan
from talk2data.connectors.demo_sqlite import resolve_time_window
from talk2data.domain.bigquery_mapping import BigQueryMapping
from talk2data.domain.models import CLASSIFICATION_RANK, AccessContext, FilterOperator, TimeGrain
from talk2data.services.policy import READ_DATA_ACTION


def validate_analytical_plan(
    mapping: BigQueryMapping,
    maximum_rows: int,
    plan: StructuredQueryPlan,
    access: AccessContext,
) -> list[str]:
    errors: list[str] = []
    if plan.connector_id != mapping.connector_id:
        errors.append("CONNECTOR_ID_MISMATCH")
    if plan.tenant_id != access.tenant_id or access.tenant_id != mapping.tenant_id:
        errors.append("TENANT_SCOPE_MISMATCH")
    if READ_DATA_ACTION not in access.permitted_actions or not access.regions or not access.business_units:
        errors.append("EXPLICIT_DATA_SCOPE_REQUIRED")
    metrics = {metric.metric_id: metric for metric in mapping.metrics}
    metric = metrics.get(plan.metric_id)
    if metric is None:
        return sorted(set([*errors, "METRIC_NOT_AVAILABLE"]))
    clearance = CLASSIFICATION_RANK[access.classification_clearance]
    if CLASSIFICATION_RANK[metric.classification] > clearance:
        errors.append("METRIC_CLASSIFICATION_DENIED")
    referenced = set(plan.dimensions) | {item.dimension_id for item in plan.filters}
    if any(
        CLASSIFICATION_RANK[mapping.dimension_classifications[dimension]] > clearance
        for dimension in referenced & mapping.dimensions.keys()
    ):
        errors.append("DIMENSION_CLASSIFICATION_DENIED")
    if any(
        getattr(plan, field) != getattr(metric, field)
        for field in ("semantic_version", "aggregation", "value_type", "unit", "currency")
    ):
        errors.append("SEMANTIC_CONTRACT_MISMATCH")
    if len(plan.dimensions) != len(set(plan.dimensions)) or set(plan.dimensions) - metric.allowed_dimensions:
        errors.append("DIMENSION_NOT_ALLOWED")
    if plan.row_limit > maximum_rows:
        errors.append("ROW_LIMIT_EXCEEDED")
    for item in plan.filters:
        if item.dimension_id not in metric.allowed_dimensions or item.operator not in {
            FilterOperator.IN,
            FilterOperator.EQUALS,
        }:
            errors.append("FILTER_NOT_ALLOWED")
        if item.dimension_id == "REGION" and set(item.values) - access.regions:
            errors.append("REGION_SCOPE_VIOLATION")
    try:
        period = resolve_time_window(plan.time_window)
        if (
            plan.time_window.calendar != "GREGORIAN"
            or plan.time_window.timezone != "UTC"
            or plan.time_window.grain == TimeGrain.HOUR
            or plan.time_window.grain not in metric.supported_time_grains
            or (period.end - period.start).days > 730
        ):
            errors.append("TIME_CONTRACT_NOT_SUPPORTED")
    except ValueError:
        errors.append("INVALID_TIME_WINDOW")
    return sorted(set(errors))
