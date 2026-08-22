from __future__ import annotations

import hashlib
import json
import math
from calendar import monthrange
from datetime import date
from typing import Any

from talk2data.domain.chat import (
    CertifiedAnswer,
    CertifiedClaim,
    QueryReceipt,
    VerificationReport,
    VerificationStatus,
)
from talk2data.domain.models import BusinessQueryIR, MetricDefinition, MetricValueType, TenantDomainPack


class ResultSenseValidator:
    """Rejects numerically invalid, unreproducible, or structurally inconsistent results."""

    def validate(
        self,
        *,
        metric: MetricDefinition,
        query_ir: BusinessQueryIR,
        receipt: QueryReceipt,
    ) -> tuple[QueryReceipt, VerificationReport]:
        checks: list[str] = []
        failures: list[str] = []

        canonical = json.dumps(
            receipt.result_rows,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        expected_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if expected_hash == receipt.result_hash:
            checks.append("RESULT_HASH_MATCHED")
        else:
            failures.append("RESULT_HASH_MISMATCH")

        if receipt.query_id == query_ir.query_id and receipt.plan_hash == query_ir.plan_hash:
            checks.append("QUERY_LINEAGE_MATCHED")
        else:
            failures.append("QUERY_LINEAGE_MISMATCH")

        if receipt.row_count == len(receipt.result_rows):
            checks.append("ROW_COUNT_MATCHED")
        else:
            failures.append("ROW_COUNT_MISMATCH")

        if receipt.resolved_end <= receipt.coverage_end:
            checks.append("SOURCE_COVERAGE_VALID")
        else:
            failures.append("SOURCE_COVERAGE_EXCEEDED")

        if not receipt.result_rows:
            failures.append("NO_DATA_RETURNED")

        seen_dimension_keys: set[tuple[Any, ...]] = set()
        for index, row in enumerate(receipt.result_rows):
            dimension_key = tuple(row.get(dimension) for dimension in query_ir.dimensions)
            if dimension_key in seen_dimension_keys:
                failures.append(f"DUPLICATE_DIMENSION_KEY_AT_ROW_{index}")
            seen_dimension_keys.add(dimension_key)
            self._validate_value(
                value=row.get("value"),
                metric=metric,
                label=f"ROW_{index}_VALUE",
                failures=failures,
            )
            if "comparison_value" in row:
                self._validate_value(
                    value=row.get("comparison_value"),
                    metric=metric,
                    label=f"ROW_{index}_COMPARISON_VALUE",
                    failures=failures,
                )
            percent_change = row.get("percent_change")
            if percent_change is not None and not self._is_finite_number(percent_change):
                failures.append(f"ROW_{index}_PERCENT_CHANGE_NOT_FINITE")

        if not any(item.startswith("DUPLICATE_DIMENSION_KEY") for item in failures):
            checks.append("DIMENSION_KEYS_UNIQUE")
        if not any("VALUE_" in item or item.endswith("_VALUE") for item in failures):
            checks.append("METRIC_BOUNDS_VALID")

        status = VerificationStatus.FAILED if failures else VerificationStatus.VERIFIED
        updated_receipt = receipt.model_copy(
            update={
                "data_quality_status": status.value,
                "data_quality_checks": [*receipt.data_quality_checks, *checks],
            }
        )
        return updated_receipt, VerificationReport(status=status, checks=checks, failures=failures)

    @classmethod
    def _validate_value(
        cls,
        *,
        value: Any,
        metric: MetricDefinition,
        label: str,
        failures: list[str],
    ) -> None:
        if not cls._is_finite_number(value):
            failures.append(f"{label}_NOT_FINITE")
            return
        numeric = float(value)
        if metric.valid_min is not None and numeric < metric.valid_min:
            failures.append(f"{label}_BELOW_MINIMUM")
        if metric.valid_max is not None and numeric > metric.valid_max:
            failures.append(f"{label}_ABOVE_MAXIMUM")
        if metric.value_type == MetricValueType.INTEGER and not numeric.is_integer():
            failures.append(f"{label}_NOT_INTEGER")

    @staticmethod
    def _is_finite_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


class CertifiedAnswerComposer:
    """Creates natural but deterministic language solely from verified receipt values."""

    def compose(
        self,
        *,
        pack: TenantDomainPack,
        metric: MetricDefinition,
        query_ir: BusinessQueryIR,
        receipt: QueryReceipt,
    ) -> CertifiedAnswer:
        period = format_period(receipt.resolved_start, receipt.resolved_end)
        dimension_names = {
            entity.id: entity.name for entity in pack.entities if entity.id in query_ir.dimensions
        }
        value_labels = {value.id: value.name for entity in pack.entities for value in entity.values}

        claims: list[CertifiedClaim] = []
        lines: list[str] = []
        for row in receipt.result_rows:
            dimensions = {
                dimension: str(row[dimension])
                for dimension in query_ir.dimensions
                if row.get(dimension) is not None
            }
            formatted_value = format_metric_value(float(row["value"]), metric, pack.default_currency)
            comparison_value = row.get("comparison_value")
            formatted_comparison = (
                None
                if comparison_value is None
                else format_metric_value(float(comparison_value), metric, pack.default_currency)
            )
            absolute_change = row.get("absolute_change")
            percent_change = row.get("percent_change")
            subject = format_dimension_subject(dimensions, dimension_names, value_labels)
            statement = f"{metric.name}{subject} was {formatted_value} for {period}."
            if formatted_comparison is not None:
                change_phrase = format_change(
                    metric=metric,
                    absolute_change=(None if absolute_change is None else float(absolute_change)),
                    percent_change=(None if percent_change is None else float(percent_change)),
                )
                statement = (
                    f"{metric.name}{subject} was {formatted_value} for {period}, compared with "
                    f"{formatted_comparison}{change_phrase}."
                )
            lines.append(statement)
            claims.append(
                CertifiedClaim(
                    statement=statement,
                    metric_id=metric.id,
                    dimensions=dimensions,
                    value=float(row["value"]),
                    formatted_value=formatted_value,
                    comparison_value=(None if comparison_value is None else float(comparison_value)),
                    formatted_comparison_value=formatted_comparison,
                    absolute_change=(None if absolute_change is None else float(absolute_change)),
                    percent_change=(None if percent_change is None else float(percent_change)),
                    receipt_id=receipt.receipt_id,
                )
            )

        if query_ir.dimensions:
            grouping = ", ".join(dimension_names.get(item, humanize(item)) for item in query_ir.dimensions)
            headline = f"{metric.name} by {grouping}"
            text = " ".join(lines)
        else:
            headline = metric.name
            text = lines[0]

        suggested = build_suggested_questions(metric, query_ir, pack)
        return CertifiedAnswer(
            headline=headline,
            text=text,
            claims=claims,
            caveats=[
                "This answer uses synthetic telecommunications demonstration data.",
                "No Unified AI Brain context or external evidence was used.",
                f"Certified source coverage ends {receipt.coverage_end.isoformat()}.",
            ],
            suggested_questions=suggested,
        )


def format_metric_value(value: float, metric: MetricDefinition, currency: str) -> str:
    if metric.value_type == MetricValueType.PERCENTAGE:
        return f"{value * 100:.2f}%"
    if metric.value_type == MetricValueType.CURRENCY:
        symbol = "$" if currency == "USD" else f"{currency} "
        return f"{symbol}{value:,.2f}"
    if metric.value_type == MetricValueType.INTEGER:
        return f"{round(value):,}"
    return f"{value:,.2f}"


def format_change(
    *,
    metric: MetricDefinition,
    absolute_change: float | None,
    percent_change: float | None,
) -> str:
    if absolute_change is None:
        return ""
    if absolute_change > 0:
        direction = "an increase"
    elif absolute_change < 0:
        direction = "a decrease"
    else:
        direction = "no change"
    if metric.value_type == MetricValueType.PERCENTAGE:
        magnitude = f"{abs(absolute_change) * 100:.2f} percentage points"
    elif metric.value_type == MetricValueType.INTEGER:
        magnitude = f"{abs(round(absolute_change)):,}"
    else:
        magnitude = f"{abs(absolute_change):,.2f}"
    relative = "" if percent_change is None else f" ({abs(percent_change) * 100:.1f}% relative)"
    return f", {direction} of {magnitude}{relative}"


def format_period(start: date, end: date) -> str:
    is_complete_month = (
        start.day == 1
        and end.day == monthrange(end.year, end.month)[1]
        and start.year == end.year
        and start.month == end.month
    )
    if is_complete_month:
        return start.strftime("%B %Y")
    if start == end:
        return start.strftime("%B %d, %Y")
    return f"{start.isoformat()} through {end.isoformat()}"


def format_dimension_subject(
    dimensions: dict[str, str],
    dimension_names: dict[str, str],
    value_labels: dict[str, str],
) -> str:
    if not dimensions:
        return ""
    parts = [
        f" for {dimension_names.get(key, humanize(key))} {value_labels.get(value, humanize(value))}"
        for key, value in dimensions.items()
    ]
    return "".join(parts)


def build_suggested_questions(
    metric: MetricDefinition,
    query_ir: BusinessQueryIR,
    pack: TenantDomainPack,
) -> list[str]:
    entity_names = {entity.id: entity.name for entity in pack.entities}
    suggestions: list[str] = []
    for dimension in metric.allowed_dimensions:
        if dimension not in query_ir.dimensions:
            suggestions.append(
                f"Show {metric.name} by "
                f"{entity_names.get(dimension, humanize(dimension))} for the same period."
            )
        if len(suggestions) == 2:
            break
    if query_ir.comparison.comparison_type.value == "NONE":
        suggestions.append(f"Compare {metric.name} with the previous equivalent period.")
    return suggestions[:3]


def humanize(value: str) -> str:
    return value.replace("_", " ").title()
