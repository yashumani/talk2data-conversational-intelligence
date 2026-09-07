from __future__ import annotations

from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import Forbidden
from google.auth.exceptions import RefreshError
from google.cloud import bigquery

from talk2data.services.bigquery_sdk import GoogleBigQueryTransport
from talk2data.services.bigquery_sql import compile_bigquery
from tests.internal_support import access, mapping, plan, settings


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> Any:
    client = MagicMock()
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(bigquery, "Client", constructor)
    transport = GoogleBigQueryTransport(settings())
    constructor.assert_called_once_with(project="example-project", location="US")
    return transport, client


def statement() -> Any:
    return compile_bigquery(mapping(), mapping().metrics[1], plan(), access())


def table() -> Any:
    contract = mapping()
    columns = {
        contract.tenant_column: "STRING",
        contract.business_unit_column: "STRING",
        contract.date_column: "DATE",
        contract.snapshot_column: "TIMESTAMP",
        contract.metric_column: "STRING",
        **{column: "STRING" for column in contract.dimensions.values()},
        "amount": "INTEGER",
        "numerator": "NUMERIC",
        "denominator": "NUMERIC",
    }
    return SimpleNamespace(
        table_type="VIEW",
        location="US",
        schema=[bigquery.SchemaField(name, kind) for name, kind in columns.items()],
    )


def job(**updates: Any) -> Any:
    iterator = MagicMock()
    iterator.total_rows = 1
    iterator.__iter__.return_value = iter([{"value": 3100}])
    return SimpleNamespace(
        job_id="stable-job",
        location="US",
        project="example-project",
        state="DONE",
        error_result=None,
        statement_type="SELECT",
        result=MagicMock(return_value=iterator),
        total_bytes_processed=1000,
        total_bytes_billed=1000,
        cache_hit=False,
        started=datetime(2026, 8, 1, tzinfo=UTC),
        ended=datetime(2026, 8, 1, tzinfo=UTC),
        **updates,
    )


def test_sdk_checks_exact_view_schema_and_location(sdk: Any) -> None:
    transport, client = sdk
    client.get_table.return_value = table()
    transport.validate_view(mapping())
    args, kwargs = client.get_table.call_args
    assert args == (mapping().view,) and kwargs["timeout"] == 10
    assert kwargs["retry"]._predicate(Forbidden("denied")) is False


@pytest.mark.parametrize("change", ["table_type", "location", "missing", "type", "repeated"])
def test_sdk_rejects_wrong_view_contract(sdk: Any, change: str) -> None:
    transport, client = sdk
    source = table()
    if change == "table_type":
        source.table_type = "TABLE"
    elif change == "location":
        source.location = "EU"
    elif change == "missing":
        source.schema = []
    else:
        source.schema[0] = bigquery.SchemaField(
            "tenant_id",
            "INTEGER" if change == "type" else "STRING",
            mode="REPEATED" if change == "repeated" else "NULLABLE",
        )
    client.get_table.return_value = source
    with pytest.raises(ValueError):
        transport.validate_view(mapping())


def test_google_job_configuration_disables_writes_cache_and_failed_job_retries(sdk: Any) -> None:
    transport, client = sdk
    client.query.return_value = SimpleNamespace(
        total_bytes_processed=1200,
        location="US",
        statement_type="SELECT",
        referenced_tables=[bigquery.TableReference.from_string(mapping().view)],
    )
    query = statement()
    result = transport.dry_run(query)
    assert result.estimated_bytes == 1200 and result.references == frozenset({mapping().view})
    args, kwargs = client.query.call_args
    config = kwargs["job_config"].to_api_repr()
    assert args == (query.sql,) and kwargs["location"] == "US"
    assert kwargs["job_retry"] is None and kwargs["timeout"] == 10
    assert config["dryRun"] is True
    assert config["query"]["useLegacySql"] is False
    assert config["query"]["useQueryCache"] is False
    assert config["query"]["maximumBytesBilled"] == "1000000"
    assert config["jobTimeoutMs"] == "60000"
    assert "destinationTable" not in config["query"] and "scriptOptions" not in config["query"]
    assert {p["name"] for p in config["query"]["queryParameters"]} >= {
        "tenant",
        "regions",
        "units",
        "row_limit",
    }
    assert "analyst" not in str(config["labels"])


def test_completed_cloud_job_reports_limits_cost_and_identity(sdk: Any) -> None:
    transport, client = sdk
    completed = job()
    client.query.return_value = completed
    result = transport.execute(statement(), "stable-job", Event())
    assert result.rows == [{"value": 3100}] and result.total_rows == 1 and result.billed_bytes == 1000
    kwargs = client.query.call_args.kwargs
    assert kwargs["job_id"] == "stable-job" and kwargs["job_retry"] is None
    assert kwargs["job_config"].dry_run is False
    assert completed.result.call_args.kwargs["max_results"] == 101
    assert completed.result.call_args.kwargs["timeout"] == 60
    assert completed.result.call_args.kwargs["job_retry"] is None
    transport.close()
    client.close.assert_called_once()


@pytest.mark.parametrize(
    "failure", [TimeoutError("deadline"), Forbidden("private diagnostic"), ValueError("bad metadata")]
)
def test_cloud_failures_attempt_cancellation(sdk: Any, failure: Exception) -> None:
    transport, client = sdk
    failed = job()
    failed.result.side_effect = failure
    client.query.return_value = failed
    cancelled = Event()
    with pytest.raises(type(failure)):
        transport.execute(statement(), "stable-job", cancelled)
    assert cancelled.is_set()
    assert client.cancel_job.call_args.args == ("stable-job",)
    assert client.cancel_job.call_args.kwargs["project"] == "example-project"
    assert client.cancel_job.call_args.kwargs["location"] == "US"


@pytest.mark.parametrize("change", ["state", "error", "statement", "total_rows"])
def test_unfinished_or_unbounded_cloud_results_are_rejected(sdk: Any, change: str) -> None:
    transport, client = sdk
    result = job()
    if change == "state":
        result.state = "RUNNING"
    elif change == "error":
        result.error_result = {"reason": "denied"}
    elif change == "statement":
        result.statement_type = "DELETE"
    else:
        result.result.return_value.total_rows = None
    client.query.return_value = result
    with pytest.raises(ValueError):
        transport.execute(statement(), "stable-job", Event())
    client.cancel_job.assert_called_once()


def test_cancellation_before_submission_prevents_a_query(sdk: Any) -> None:
    transport, client = sdk
    cancelled = Event()
    cancelled.set()
    with pytest.raises(TimeoutError):
        transport.execute(statement(), "stable-job", cancelled)
    client.query.assert_not_called()


@pytest.mark.parametrize("when", ["submission", "result"])
def test_cancellation_races_cannot_release_results(sdk: Any, when: str) -> None:
    transport, client = sdk
    cancelled = Event()
    completed = job()

    def submitted(*_: Any, **__: Any) -> Any:
        if when == "submission":
            cancelled.set()
        return completed

    client.query.side_effect = submitted
    if when == "result":
        iterator = completed.result.return_value
        completed.result.side_effect = lambda **_: (cancelled.set(), iterator)[1]
    with pytest.raises(TimeoutError):
        transport.execute(statement(), "stable-job", cancelled)
    client.cancel_job.assert_called_once()


def test_cancel_is_best_effort_and_never_retargets_a_project(sdk: Any) -> None:
    transport, client = sdk
    client.cancel_job.return_value = True
    assert transport.cancel("stable-job") is True
    client.cancel_job.side_effect = Forbidden("denied")
    assert transport.cancel("stable-job") is False


@pytest.mark.parametrize(
    "failure", [OSError("transport"), RefreshError("private credentials"), Forbidden("denied")]
)
def test_uncertain_submission_uses_same_job_id_for_cancellation(sdk: Any, failure: Exception) -> None:
    transport, client = sdk
    client.query.side_effect = failure
    client.cancel_job.side_effect = failure
    cancelled = Event()
    with pytest.raises(type(failure)):
        transport.execute(statement(), "stable-job", cancelled)
    assert cancelled.is_set() and client.query.call_count == 1
    assert client.cancel_job.call_args.args == ("stable-job",)
