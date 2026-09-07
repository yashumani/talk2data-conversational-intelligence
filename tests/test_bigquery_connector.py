from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event
from typing import Any

import pytest

from talk2data.connectors.bigquery import BigQueryConnector
from talk2data.connectors.errors import ConnectorValidationError, SourceNotReadyError
from talk2data.domain.models import AccessContext, ClassificationLevel, TimeGrain
from talk2data.services.bigquery_port import DryRun
from talk2data.services.bigquery_sql import compile_bigquery
from tests.internal_support import RecordingCloud, access, mapping, plan, settings


@pytest.fixture
def cloud() -> RecordingCloud:
    return RecordingCloud()


@pytest.fixture
def connector(cloud: RecordingCloud) -> BigQueryConnector:
    return BigQueryConnector(mapping(), settings(), cloud)


async def test_read_only_query_enforces_scope_and_returns_reproducible_receipt(
    connector: BigQueryConnector, cloud: RecordingCloud
) -> None:
    request = plan(filters=[{"dimension_id": "CHANNEL", "values": ["RETAIL"]}])
    receipt = await connector.execute_read_only(request, access())
    assert receipt.result_rows == [{"REGION": "NORTHEAST", "value": 3100.0}]
    assert receipt.source_kind == "bigquery"
    assert receipt.cloud_job and receipt.cloud_job.estimated_bytes == 1000
    assert receipt.cloud_job.job_id == cloud.jobs[0]
    assert receipt.cloud_job.semantic_version == "2.0"
    assert receipt.physical_mapping_hash == mapping().fingerprint()
    assert (
        receipt.result_hash
        == hashlib.sha256(
            json.dumps(receipt.result_rows, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    statement = cloud.statements[0]
    values = {p.name: p.value for p in statement.parameters}
    assert values["tenant"] == "demo-telecom"
    assert values["regions"] == ("NORTHEAST",) and values["units"] == ("CONSUMER",)
    assert values["filter_0"] == ("RETAIL",)
    assert "`tenant_id` = @tenant" in statement.sql
    assert "`region` IN UNNEST(@regions)" in statement.sql
    assert "`business_unit` IN UNNEST(@units)" in statement.sql
    assert statement.sql.startswith("SELECT ") and ";" not in statement.sql
    assert "COUNT(DISTINCT `fact_date`)" in statement.sql
    assert not connector._active


async def test_scalar_aggregate_keeps_row_scope_without_grouping(
    connector: BigQueryConnector, cloud: RecordingCloud
) -> None:
    receipt = await connector.execute_read_only(plan(dimensions=[]), access())
    assert receipt.result_rows == [{"value": 3100.0}]
    assert "`region` IN UNNEST(@regions)" in cloud.statements[0].sql


async def test_ratio_and_comparison_share_one_bounded_job(
    connector: BigQueryConnector, cloud: RecordingCloud
) -> None:
    request = plan(
        metric_id="POSTPAID_CHURN",
        aggregation="RATIO",
        value_type="PERCENTAGE",
        unit="PERCENT",
        dimensions=["PLAN"],
        comparison={"comparison_type": "PRIOR_PERIOD"},
    )
    receipt = await connector.execute_read_only(request, access())
    assert receipt.result_rows[0]["value"] == 0.01
    assert receipt.result_rows[0]["comparison_value"] == 0.01
    assert receipt.result_rows[0]["absolute_change"] == 0
    assert "SAFE_DIVIDE(SUM(`numerator`), SUM(`denominator`))" in cloud.statements[0].sql
    assert len(cloud.jobs) == 1 and receipt.comparison_start is not None


async def test_injection_stays_a_bound_value(connector: BigQueryConnector, cloud: RecordingCloud) -> None:
    malicious = "RETAIL' OR TRUE; DELETE FROM sensitive --"
    await connector.execute_read_only(
        plan(filters=[{"dimension_id": "CHANNEL", "values": [malicious]}]), access()
    )
    assert malicious not in cloud.statements[0].sql
    assert any(p.value == (malicious,) for p in cloud.statements[0].parameters)


@pytest.mark.parametrize(
    "updates",
    [
        {"connector_id": "another"},
        {"tenant_id": "another"},
        {"metric_id": "UNAPPROVED"},
        {"semantic_version": "3"},
        {"aggregation": "RATIO"},
        {"value_type": "PERCENTAGE"},
        {"unit": "CURRENCY"},
        {"currency": "USD"},
        {"dimensions": ["UNKNOWN"]},
        {"dimensions": ["REGION", "REGION"]},
        {"row_limit": 101},
        {"filters": [{"dimension_id": "UNKNOWN", "values": ["x"]}]},
        {"filters": [{"dimension_id": "REGION", "values": ["SOUTHEAST"]}]},
        {
            "time_window": {
                "preset": "CURRENT_DAY",
                "grain": "DAY",
                "calendar": "FISCAL",
                "timezone": "UTC",
                "anchor_date": "2026-08-01",
            }
        },
        {
            "time_window": {
                "preset": "CURRENT_DAY",
                "grain": "DAY",
                "calendar": "GREGORIAN",
                "timezone": "America/New_York",
                "anchor_date": "2026-08-01",
            }
        },
        {
            "time_window": {
                "preset": "CUSTOM",
                "grain": "YEAR",
                "calendar": "GREGORIAN",
                "timezone": "UTC",
                "anchor_date": "2026-08-01",
                "start_date": "2020-01-01",
                "end_date": "2026-07-31",
            }
        },
    ],
)
async def test_unapproved_plans_never_reach_google(
    connector: BigQueryConnector, cloud: RecordingCloud, updates: dict[str, Any]
) -> None:
    with pytest.raises(ConnectorValidationError):
        await connector.execute_read_only(plan(**updates), access())
    assert not cloud.statements and not cloud.jobs


@pytest.mark.parametrize(
    "updates",
    [{"tenant_id": "another"}, {"regions": set()}, {"business_units": set()}, {"permitted_actions": set()}],
)
async def test_explicit_scope_is_mandatory(
    connector: BigQueryConnector, cloud: RecordingCloud, updates: dict[str, Any]
) -> None:
    scoped = AccessContext.model_validate({**access().model_dump(), **updates})
    with pytest.raises(ConnectorValidationError):
        await connector.execute_read_only(plan(), scoped)
    assert not cloud.jobs


@pytest.mark.parametrize(
    "estimate",
    [
        DryRun(None, "US", "SELECT", frozenset({"example-project.analytics.approved_daily"})),
        DryRun(-1, "US", "SELECT", frozenset({"example-project.analytics.approved_daily"})),
        DryRun(1_000_001, "US", "SELECT", frozenset({"example-project.analytics.approved_daily"})),
        DryRun(1, "EU", "SELECT", frozenset({"example-project.analytics.approved_daily"})),
        DryRun(1, "US", "DELETE", frozenset({"example-project.analytics.approved_daily"})),
        DryRun(1, "US", "SELECT", frozenset()),
        DryRun(1, "US", "SELECT", frozenset({"example-project.private.raw"})),
    ],
)
async def test_failed_dry_run_blocks_execution(
    connector: BigQueryConnector, cloud: RecordingCloud, estimate: DryRun
) -> None:
    cloud.estimate = estimate
    with pytest.raises(ConnectorValidationError):
        await connector.execute_read_only(plan(), access())
    assert not cloud.jobs


async def test_no_unscoped_cost_or_freshness_query(
    connector: BigQueryConnector, cloud: RecordingCloud
) -> None:
    assert (await connector.estimate_cost(plan()))["requires_authorized_execution"]
    assert (await connector.get_freshness()).status.value == "NOT_READY"
    assert not cloud.statements
    assert await connector.discover_catalog(access())
    assert await connector.discover_catalog(access(tenant="another")) == []
    assert await connector.discover_catalog(access().model_copy(update={"permitted_actions": set()})) == []
    assert await connector.test_connection() == (True, "The approved BigQuery view contract is ready.")
    cloud.failure = OSError("private source diagnostic")
    assert (await connector.test_connection())[0] is False
    with pytest.raises(ConnectorValidationError, match="before a result could be certified"):
        await connector.execute_read_only(plan(), access())


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"_days": 30}, SourceNotReadyError),
        ({"_invalid": 1}, SourceNotReadyError),
        ({"_start": None}, SourceNotReadyError),
        ({"_end": None}, SourceNotReadyError),
        ({"_period": "unexpected"}, ConnectorValidationError),
        ({"_period": "comparison"}, ConnectorValidationError),
        ({"REGION": None}, ConnectorValidationError),
        ({"REGION": ""}, ConnectorValidationError),
        ({"value": float("nan")}, ConnectorValidationError),
        ({"value": float("inf")}, ConnectorValidationError),
        ({"value": None}, SourceNotReadyError),
        ({"value": True}, SourceNotReadyError),
        ({"_snapshot": None}, SourceNotReadyError),
        ({"_snapshot": datetime(2026, 7, 31)}, SourceNotReadyError),
        ({"_snapshot": datetime(2100, 1, 1, tzinfo=UTC)}, SourceNotReadyError),
    ],
)
async def test_uncertifiable_rows_never_release_an_answer(
    connector: BigQueryConnector, cloud: RecordingCloud, changes: dict[str, Any], error: type[Exception]
) -> None:
    request = plan()
    statement = compile_bigquery(mapping(), mapping().metrics[1], request, access())
    good = cloud.execute(statement, "seed", Event()).rows[0]
    cloud.rows = [{**good, **changes}]
    with pytest.raises(error):
        await connector.execute_read_only(request, access())


async def test_empty_duplicate_and_truncated_results(
    connector: BigQueryConnector, cloud: RecordingCloud
) -> None:
    request = plan()
    statement = compile_bigquery(mapping(), mapping().metrics[1], request, access())
    row = cloud.execute(statement, "seed", Event()).rows[0]
    for rows, error in [
        ([], SourceNotReadyError),
        ([row, row], ConnectorValidationError),
        ([row] * 101, ConnectorValidationError),
    ]:
        cloud.rows = rows
        with pytest.raises(error):
            await connector.execute_read_only(request, access())


async def test_comparison_groups_must_match(connector: BigQueryConnector, cloud: RecordingCloud) -> None:
    request = plan(comparison={"comparison_type": "PRIOR_PERIOD"})
    statement = compile_bigquery(mapping(), mapping().metrics[1], request, access())
    rows = cloud.execute(statement, "seed", Event()).rows
    rows[1]["REGION"] = "SOUTHEAST"
    cloud.rows = rows
    with pytest.raises(SourceNotReadyError, match="matching"):
        await connector.execute_read_only(request, access())


@pytest.mark.parametrize(
    "changes",
    [
        {"job_id": "foreign-job"},
        {"location": "EU"},
        {"billing_project": "foreign-project"},
        {"total_rows": 999},
    ],
)
async def test_cloud_result_identity_and_pagination(
    connector: BigQueryConnector,
    cloud: RecordingCloud,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any],
) -> None:
    execute = cloud.execute
    monkeypatch.setattr(cloud, "execute", lambda *args: replace(execute(*args), **changes))
    with pytest.raises(ConnectorValidationError):
        await connector.execute_read_only(plan(), access())


async def test_cancellation_and_duplicate_running_query(
    connector: BigQueryConnector, cloud: RecordingCloud
) -> None:
    request = plan()
    cloud.gate = Event()
    task = asyncio.create_task(connector.execute_read_only(request, access()))
    assert await asyncio.to_thread(cloud.started.wait, 2)
    with pytest.raises(ConnectorValidationError, match="ALREADY_RUNNING"):
        await connector.execute_read_only(request, access())
    assert await connector.cancel_query(str(request.query_id))
    with pytest.raises(TimeoutError):
        await task
    assert cloud.cancellations and not connector._active
    assert await connector.cancel_query("unknown") is False


async def test_request_cancellation_attempts_cloud_cancellation(
    connector: BigQueryConnector, cloud: RecordingCloud
) -> None:
    cloud.gate = Event()
    task = asyncio.create_task(connector.execute_read_only(plan(), access()))
    assert await asyncio.to_thread(cloud.started.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cloud.cancellations and not connector._active


async def test_raw_tool_access_cannot_bypass_classification(cloud: RecordingCloud) -> None:
    contract = mapping()
    contract = mapping(
        dimension_classifications={**contract.dimension_classifications, "STORE": "RESTRICTED"}
    )
    connector = BigQueryConnector(contract, settings(), cloud)
    limited = access().model_copy(update={"classification_clearance": ClassificationLevel.INTERNAL})
    catalog = await connector.discover_catalog(limited)
    assert [item["metric_id"] for item in catalog] == ["MOBILE_ACTIVATIONS"]
    assert "STORE" not in catalog[0]["dimensions"]
    for request, reason in [
        (plan(metric_id="POSTPAID_CHURN"), "METRIC_CLASSIFICATION_DENIED"),
        (plan(dimensions=["STORE"]), "DIMENSION_CLASSIFICATION_DENIED"),
        (
            plan(dimensions=[], filters=[{"dimension_id": "STORE", "values": ["STORE_001"]}]),
            "DIMENSION_CLASSIFICATION_DENIED",
        ),
    ]:
        with pytest.raises(ConnectorValidationError, match=reason):
            await connector.execute_read_only(request, limited)
    assert not cloud.statements and not cloud.jobs


async def test_hourly_time_grain_cannot_use_daily_view(connector: BigQueryConnector) -> None:
    request = plan()
    request.time_window.grain = TimeGrain.HOUR
    assert "TIME_CONTRACT_NOT_SUPPORTED" in await connector.validate_plan(request, access())


@pytest.mark.parametrize("value", [1.5, 2**53, -(2**53)])
async def test_integer_precision_is_preserved(
    connector: BigQueryConnector, cloud: RecordingCloud, value: float
) -> None:
    request = plan()
    statement = compile_bigquery(mapping(), mapping().metrics[1], request, access())
    cloud.rows = cloud.execute(statement, "seed", Event()).rows
    cloud.rows[0]["value"] = value
    with pytest.raises(ConnectorValidationError, match="NOT_EXACTLY_REPRESENTABLE"):
        await connector.execute_read_only(request, access())


@pytest.mark.parametrize("stage", ["dry_run", "execute"])
async def test_late_cancellation_discards_result(
    connector: BigQueryConnector, cloud: RecordingCloud, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    original = getattr(cloud, stage)

    def late(*args: Any) -> Any:
        result = original(*args)
        next(iter(connector._active.values()))[1].set()
        return result

    monkeypatch.setattr(cloud, stage, late)
    with pytest.raises(TimeoutError):
        await connector.execute_read_only(plan(), access())
    assert cloud.cancellations and not connector._active
