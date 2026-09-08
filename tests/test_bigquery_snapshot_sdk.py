from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.cloud import bigquery

from talk2data.services.bigquery_snapshot_sdk import GoogleSnapshotTransport
from tests.internal_support import mapping, settings
from tests.test_bigquery_sdk import table


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> tuple[GoogleSnapshotTransport, MagicMock]:
    client = MagicMock()
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(bigquery, "Client", constructor)
    transport = GoogleSnapshotTransport(settings(maximum_bytes_billed=2_000))
    client.get_table.return_value = table()
    return transport, client


def jobs() -> tuple[Any, Any]:
    dry = SimpleNamespace(
        statement_type="SELECT",
        location="US",
        referenced_tables=[bigquery.TableReference.from_string(mapping().view)],
        total_bytes_processed=1_000,
    )
    row = {
        "tenant_id": "demo-telecom",
        "business_unit": "CONSUMER",
        "fact_date": date(2026, 7, 1),
        "source_updated_at": datetime(2026, 7, 31, tzinfo=UTC),
        "metric_id": "MOBILE_ACTIVATIONS",
        "region": "NORTHEAST",
        "channel": "RETAIL",
        "store": "STORE_001",
        "market": "NEW_JERSEY",
        "plan": "UNLIMITED",
        "amount": 100,
        "numerator": None,
        "denominator": None,
    }
    complete = SimpleNamespace(
        job_id="extract-job",
        state="DONE",
        error_result=None,
        statement_type="SELECT",
        total_bytes_processed=1_000,
        total_bytes_billed=900,
        result=MagicMock(return_value=[row]),
    )
    return dry, complete


def test_snapshot_sdk_uses_one_tenant_scoped_read_only_query(sdk: Any) -> None:
    transport, client = sdk
    dry, complete = jobs()
    client.query.side_effect = [dry, complete]
    transport.validate_view(mapping())
    result = transport.extract(mapping(), 100)
    assert result.job_id == "extract-job" and result.billed_bytes == 900 and len(result.rows) == 1
    sql = client.query.call_args_list[0].args[0]
    assert "WHERE `tenant_id` = @tenant" in sql and "LIMIT @limit" in sql and ";" not in sql
    dry_config = client.query.call_args_list[0].kwargs["job_config"]
    live_config = client.query.call_args_list[1].kwargs["job_config"]
    assert dry_config.dry_run is True and live_config.dry_run is not True
    assert live_config.maximum_bytes_billed == 2_000 and live_config.use_query_cache is False
    complete.result.assert_called_once_with(timeout=60, retry=None, job_retry=None)
    transport.close()
    client.close.assert_called_once()


@pytest.mark.parametrize("failure", ["statement", "location", "references", "bytes", "unknown"])
def test_snapshot_sdk_rejects_an_unapproved_dry_run(sdk: Any, failure: str) -> None:
    transport, client = sdk
    dry, _ = jobs()
    if failure == "statement":
        dry.statement_type = "INSERT"
    elif failure == "location":
        dry.location = "EU"
    elif failure == "references":
        dry.referenced_tables = []
    elif failure == "bytes":
        dry.total_bytes_processed = 2_001
    else:
        dry.referenced_tables = [bigquery.TableReference.from_string("example-project.private.raw")]
    client.query.return_value = dry
    with pytest.raises(ValueError, match="dry run"):
        transport.extract(mapping(), 100)
    assert client.query.call_count == 1


@pytest.mark.parametrize("failure", ["state", "error", "statement"])
def test_snapshot_sdk_rejects_an_unfinished_or_mutating_job(sdk: Any, failure: str) -> None:
    transport, client = sdk
    dry, complete = jobs()
    if failure == "state":
        complete.state = "RUNNING"
    elif failure == "error":
        complete.error_result = {"reason": "denied"}
    else:
        complete.statement_type = "UPDATE"
    client.query.side_effect = [dry, complete]
    with pytest.raises(ValueError, match="read-only SELECT"):
        transport.extract(mapping(), 100)
