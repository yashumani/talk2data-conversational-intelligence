from __future__ import annotations

import hashlib
import json
from datetime import date
from uuid import uuid4

import pytest

from talk2data.domain.chat import QueryReceipt
from talk2data.domain.models import BusinessQueryIR
from talk2data.services.certification import (
    ResultSenseValidator,
    format_change,
    format_metric_value,
    format_period,
    source_caveat,
)


@pytest.fixture
def evidence(client, full_access):
    response = client.post(
        "/v1/chat/demo",
        json={
            "question": "Mobile activations by region last month",
            "access_context": full_access,
            "use_llm": False,
            "include_debug": True,
            "as_of": "2026-08-17T12:00:00Z",
        },
    ).json()
    assert response["status"] == "ANSWERED"
    ir = BusinessQueryIR.model_validate(response["query_ir"])
    receipt = QueryReceipt.model_validate(response["receipt"])
    metric = next(
        m for m in client.app.state.domain_registry.get("demo-telecom").metrics if m.id == ir.metric_id
    )
    return metric, ir, receipt


@pytest.mark.parametrize(
    ("field", "value", "failure"),
    [
        ("query_id", uuid4(), "QUERY_LINEAGE_MISMATCH"),
        ("decision_id", uuid4(), "QUERY_LINEAGE_MISMATCH"),
        ("plan_hash", "f" * 64, "QUERY_LINEAGE_MISMATCH"),
        ("connector_id", "other", "QUERY_LINEAGE_MISMATCH"),
        ("policy_decision_id", "other", "QUERY_LINEAGE_MISMATCH"),
        ("row_count", 999, "ROW_COUNT_MISMATCH"),
        ("resolved_start", date(2020, 1, 1), "SOURCE_COVERAGE_EXCEEDED"),
        ("resolved_end", date(2030, 1, 1), "SOURCE_COVERAGE_EXCEEDED"),
    ],
)
def test_receipt_lineage_and_entire_period_must_match(evidence, field, value, failure):
    metric, ir, receipt = evidence
    updated, report = ResultSenseValidator().validate(
        metric=metric, query_ir=ir, receipt=receipt.model_copy(update={field: value})
    )
    assert report.status == "FAILED" and failure in report.failures
    assert updated.data_quality_status == "FAILED"


@pytest.mark.parametrize(
    ("row", "failure"),
    [
        ({"REGION": "WEST", "value": None}, "VALUE_NOT_FINITE"),
        ({"REGION": "WEST", "value": True}, "VALUE_NOT_FINITE"),
        ({"REGION": "WEST", "value": -1}, "VALUE_BELOW_MINIMUM"),
        ({"REGION": "WEST", "value": 1.5}, "VALUE_NOT_INTEGER"),
        ({"REGION": "WEST", "value": 1, "comparison_value": "invalid"}, "COMPARISON_VALUE_NOT_FINITE"),
        ({"REGION": "WEST", "value": 1, "percent_change": "invalid"}, "PERCENT_CHANGE_NOT_FINITE"),
        ({"value": 1}, "INVALID_DIMENSION_KEY"),
        ({"REGION": [], "value": 1}, "INVALID_DIMENSION_KEY"),
    ],
)
def test_invalid_values_are_never_certified_even_with_a_matching_hash(evidence, row, failure):
    metric, ir, receipt = evidence
    rows = [row]
    receipt = receipt.model_copy(
        update={
            "result_rows": rows,
            "row_count": 1,
            "result_hash": hashlib.sha256(
                json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
    )
    _, report = ResultSenseValidator().validate(metric=metric, query_ir=ir, receipt=receipt)
    assert report.status == "FAILED"
    assert any(failure in item for item in report.failures)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object()])
def test_noncanonical_payloads_fail_closed_without_crashing(evidence, value):
    metric, ir, receipt = evidence
    _, report = ResultSenseValidator().validate(
        metric=metric, query_ir=ir, receipt=receipt.model_copy(update={"result_rows": [{"value": value}]})
    )
    assert report.failures == ["RESULT_NOT_CANONICAL"]


def test_duplicate_groups_metric_upper_bounds_and_comparison_coverage(evidence):
    metric, ir, receipt = evidence
    rows = [receipt.result_rows[0], receipt.result_rows[0]]
    _, report = ResultSenseValidator().validate(
        metric=metric.model_copy(update={"valid_max": 0}),
        query_ir=ir,
        receipt=receipt.model_copy(
            update={
                "result_rows": rows,
                "comparison_start": date(2020, 1, 1),
                "comparison_end": date(2020, 1, 31),
            }
        ),
    )
    assert "DUPLICATE_DIMENSION_KEY_AT_ROW_1" in report.failures
    assert "SOURCE_COVERAGE_EXCEEDED" in report.failures
    assert "ROW_0_VALUE_ABOVE_MAXIMUM" in report.failures


def test_units_changes_and_source_labels_remain_faithful_to_evidence(evidence):
    metric, _, _ = evidence
    for value_type, currency, expected in [
        ("CURRENCY", "USD", "$1,234.50"),
        ("CURRENCY", "EUR", "EUR 1,234.50"),
        ("DECIMAL", "USD", "1,234.50"),
    ]:
        assert (
            format_metric_value(1234.5, metric.model_copy(update={"value_type": value_type}), currency)
            == expected
        )
    assert format_change(metric=metric, absolute_change=None, percent_change=None) == ""
    assert "no change" in format_change(metric=metric, absolute_change=0, percent_change=0)
    assert "a decrease" in format_change(
        metric=metric.model_copy(update={"value_type": "DECIMAL"}), absolute_change=-1.5, percent_change=None
    )
    assert format_period(date(2026, 7, 1), date(2026, 7, 1)) == "July 01, 2026"
    assert "through" in format_period(date(2026, 7, 2), date(2026, 7, 3))
    assert "synthetic" not in source_caveat("postgresql")


@pytest.mark.parametrize(
    ("current", "previous", "absolute", "relative", "valid"),
    [
        (120, 100, 20, 0.2, True),
        (80, 100, -20, -0.2, True),
        (0, 0, 0, None, True),
        (5, 0, 5, None, True),
        (5, 0, 5, 0, False),
        (120, 100, 999, 0.2, False),
        (120, 100, 20, 99, False),
        (120, 100, None, 0.2, False),
        (120, 100, 20, None, False),
        (None, 100, 20, 0.2, False),
    ],
)
def test_comparison_claims_must_reproduce_the_actual_arithmetic(
    evidence, current, previous, absolute, relative, valid
):
    metric, ir, receipt = evidence
    rows = [
        {
            "REGION": "WEST",
            "value": current,
            "comparison_value": previous,
            "absolute_change": absolute,
            "percent_change": relative,
        }
    ]
    receipt = receipt.model_copy(
        update={
            "result_rows": rows,
            "row_count": 1,
            "result_hash": hashlib.sha256(
                json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "comparison_start": date(2026, 6, 1),
            "comparison_end": date(2026, 6, 30),
        }
    )
    _, report = ResultSenseValidator().validate(metric=metric, query_ir=ir, receipt=receipt)
    assert (report.status == "VERIFIED") is valid
    if not valid:
        assert "ROW_0_COMPARISON_ARITHMETIC_MISMATCH" in report.failures


def test_comparison_cannot_silently_lose_dates_or_values(evidence):
    metric, ir, receipt = evidence
    _, report = ResultSenseValidator().validate(
        metric=metric, query_ir=ir, receipt=receipt.model_copy(update={"comparison_start": date(2026, 6, 1)})
    )
    assert "SOURCE_COVERAGE_EXCEEDED" in report.failures
    assert "ROW_0_COMPARISON_VALUE_MISSING" in report.failures
