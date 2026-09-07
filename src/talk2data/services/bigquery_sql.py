"""Compile one bounded parameterized SELECT from approved daily-fact mappings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date

from talk2data.connectors.base import StructuredQueryPlan
from talk2data.connectors.demo_sqlite import ResolvedRange, resolve_comparison_range, resolve_time_window
from talk2data.core.bigquery_config import identifier
from talk2data.domain.bigquery_mapping import BigQueryMapping, BigQueryMetricMapping
from talk2data.domain.models import AccessContext, MetricAggregation


@dataclass(frozen=True)
class QueryParameter:
    name: str
    kind: str
    value: str | int | date | tuple[str, ...]


@dataclass(frozen=True)
class BigQueryStatement:
    sql: str
    parameters: tuple[QueryParameter, ...]
    current: ResolvedRange
    comparison: ResolvedRange | None
    maximum_result_rows: int
    scope_hash: str


def quote(value: str) -> str:
    return "`" + identifier(value) + "`"


def scope_hash(access: AccessContext) -> str:
    data = access.model_dump(mode="json")
    for key, value in data.items():
        if isinstance(value, list):
            data[key] = sorted(value)
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def compile_bigquery(
    mapping: BigQueryMapping,
    metric: BigQueryMetricMapping,
    plan: StructuredQueryPlan,
    access: AccessContext,
) -> BigQueryStatement:
    current = resolve_time_window(plan.time_window)
    comparison = resolve_comparison_range(current, plan.comparison.comparison_type)
    parameters = [
        QueryParameter("tenant", "STRING", access.tenant_id),
        QueryParameter("metric", "STRING", metric.source_value),
        QueryParameter("regions", "STRING_ARRAY", tuple(sorted(access.regions))),
        QueryParameter("units", "STRING_ARRAY", tuple(sorted(access.business_units))),
        QueryParameter("current_start", "DATE", current.start),
        QueryParameter("current_end", "DATE", current.end),
    ]
    fact_date = quote(mapping.date_column)
    current_predicate = f"{fact_date} BETWEEN @current_start AND @current_end"
    period_predicate = current_predicate
    if comparison is not None:
        parameters.extend(
            [
                QueryParameter("comparison_start", "DATE", comparison.start),
                QueryParameter("comparison_end", "DATE", comparison.end),
            ]
        )
        period_predicate += f" OR {fact_date} BETWEEN @comparison_start AND @comparison_end"
    where = [
        f"{quote(mapping.tenant_column)} = @tenant",
        f"{quote(mapping.metric_column)} = @metric",
        f"{quote(mapping.dimensions['REGION'])} IN UNNEST(@regions)",
        f"{quote(mapping.business_unit_column)} IN UNNEST(@units)",
        f"({period_predicate})",
    ]
    for index, item in enumerate(plan.filters):
        name = f"filter_{index}"
        where.append(f"{quote(mapping.dimensions[item.dimension_id])} IN UNNEST(@{name})")
        parameters.append(QueryParameter(name, "STRING_ARRAY", tuple(item.values)))

    if metric.aggregation == MetricAggregation.RATIO:
        numerator, denominator = quote(str(metric.numerator_column)), quote(str(metric.denominator_column))
        expression = f"SAFE_DIVIDE(SUM({numerator}), SUM({denominator}))"
        invalid = f"{numerator} IS NULL OR {denominator} IS NULL"
    else:
        amount = quote(str(metric.amount_column))
        expression, invalid = f"SUM({amount})", f"{amount} IS NULL"
    snapshot = quote(mapping.snapshot_column)
    selected = [
        f"CASE WHEN {current_predicate} THEN 'current' ELSE 'comparison' END AS `_period`",
        *(f"{quote(mapping.dimensions[d])} AS {quote(d)}" for d in plan.dimensions),
        f"{expression} AS `value`",
        f"COUNT(DISTINCT {fact_date}) AS `_days`",
        f"MIN({fact_date}) AS `_start`",
        f"MAX({fact_date}) AS `_end`",
        f"MAX({snapshot}) AS `_snapshot`",
        f"COUNTIF({invalid} OR {snapshot} IS NULL) AS `_invalid`",
    ]
    groups = ", ".join(["`_period`", *(quote(d) for d in plan.dimensions)])
    maximum_rows = plan.row_limit * (2 if comparison else 1) + 1
    parameters.append(QueryParameter("row_limit", "INT64", maximum_rows))
    sql = (
        "SELECT "
        + ", ".join(selected)
        + f" FROM `{mapping.view}` WHERE "
        + " AND ".join(where)
        + f" GROUP BY {groups} ORDER BY {groups} LIMIT @row_limit"
    )
    return BigQueryStatement(sql, tuple(parameters), current, comparison, maximum_rows, scope_hash(access))
