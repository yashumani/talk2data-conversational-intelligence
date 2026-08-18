from __future__ import annotations

from datetime import date
from typing import cast

from fastapi.testclient import TestClient

from talk2data.connectors.demo_sqlite import resolve_time_window
from talk2data.domain.chat import QueryReceipt
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import BusinessQueryIR, TimeGrain, TimePreset, TimeWindow
from talk2data.services.certification import ResultSenseValidator


def test_time_presets_resolve_to_complete_business_periods() -> None:
    previous_month = resolve_time_window(
        TimeWindow(
            preset=TimePreset.PREVIOUS_COMPLETE_MONTH,
            grain=TimeGrain.MONTH,
            calendar="CORPORATE_FISCAL",
            timezone="America/New_York",
            anchor_date=date(2026, 8, 17),
        )
    )
    previous_week = resolve_time_window(
        TimeWindow(
            preset=TimePreset.PREVIOUS_COMPLETE_WEEK,
            grain=TimeGrain.WEEK,
            calendar="CORPORATE_FISCAL",
            timezone="America/New_York",
            anchor_date=date(2026, 8, 17),
        )
    )

    assert previous_month.start == date(2026, 7, 1)
    assert previous_month.end == date(2026, 7, 31)
    assert previous_week.start == date(2026, 8, 10)
    assert previous_week.end == date(2026, 8, 16)


def test_result_hash_tampering_is_rejected(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    response = client.post(
        "/v1/chat/demo",
        json={
            "question": "What were mobile activations in Northeast last month?",
            "access_context": full_access,
            "use_llm": False,
            "include_debug": True,
            "as_of": "2026-08-17T12:00:00Z",
        },
    )
    assert response.status_code == 200
    body = response.json()
    query_ir = BusinessQueryIR.model_validate(body["query_ir"])
    receipt = QueryReceipt.model_validate(body["receipt"])
    tampered_rows = [dict(receipt.result_rows[0])]
    tampered_rows[0]["value"] = float(tampered_rows[0]["value"]) + 100
    tampered = receipt.model_copy(update={"result_rows": tampered_rows})

    registry = cast(DomainPackRegistry, client.app.state.domain_registry)
    pack = registry.get("demo-telecom")
    metric = next(item for item in pack.metrics if item.id == query_ir.metric_id)
    _, report = ResultSenseValidator().validate(
        metric=metric,
        query_ir=query_ir,
        receipt=tampered,
    )

    assert report.status == "FAILED"
    assert "RESULT_HASH_MISMATCH" in report.failures


def test_no_data_is_not_released_as_a_numeric_answer(
    client: TestClient,
    full_access: dict[str, object],
) -> None:
    response = client.post(
        "/v1/chat/demo",
        json={
            "question": "What were mobile activations on 2026-07-15?",
            "access_context": full_access,
            "use_llm": False,
            "include_debug": True,
            "as_of": "2026-08-17T12:00:00Z",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "VERIFICATION_FAILED"
    assert body["answer"] is None
    assert "NO_DATA_RETURNED" in body["verification"]["failures"]
