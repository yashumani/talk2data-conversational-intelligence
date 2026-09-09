from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient

from talk2data.connectors.errors import ConnectorValidationError, SourceNotReadyError
from talk2data.connectors.parquet_snapshot import ParquetSnapshotConnector
from talk2data.core.parquet_config import ParquetSnapshotSettings
from talk2data.domain.parquet_snapshot import ParquetSnapshotManifest
from talk2data.internal.bootstrap import create_internal_app
from talk2data.operations.materialize_snapshot import main as materialize_main
from talk2data.services.snapshot_materializer import SnapshotExtract, SnapshotMaterializer
from tests.internal_support import access, mapping, plan, private_config


class RecordingExtract:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.validated = False
        self.closed = False

    def validate_view(self, _: Any) -> None:
        self.validated = True

    def extract(self, _: Any, maximum_rows: int) -> SnapshotExtract:
        return SnapshotExtract("read-only-job", self.rows, 1234, 1200)

    def close(self) -> None:
        self.closed = True


def source_rows() -> list[dict[str, Any]]:
    return [
        {
            "tenant_id": "demo-telecom",
            "business_unit": "CONSUMER",
            "fact_date": date(2026, 7, day),
            "source_updated_at": datetime(2026, 7, 31, 23, 0, tzinfo=UTC),
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
        for day in range(1, 32)
    ]


def snapshot(tmp_path: Path) -> tuple[ParquetSnapshotSettings, ParquetSnapshotManifest]:
    settings = ParquetSnapshotSettings(directory=tmp_path, maximum_age_seconds=3600)
    transport = RecordingExtract(source_rows())
    manifest = SnapshotMaterializer(settings, transport).materialize(mapping())
    assert transport.validated
    return settings, manifest


async def test_materialized_snapshot_answers_with_same_governed_scope(tmp_path: Path) -> None:
    settings, manifest = snapshot(tmp_path)
    connector = ParquetSnapshotConnector(mapping(), settings)
    await connector.initialize()
    receipt = await connector.execute_read_only(
        plan(filters=[{"dimension_id": "CHANNEL", "values": ["RETAIL"]}]), access()
    )
    assert receipt.result_rows == [{"REGION": "NORTHEAST", "value": 3100.0}]
    assert receipt.source_kind == "parquet_snapshot" and receipt.cloud_job is None
    assert receipt.source_fingerprint == manifest.parquet_sha256
    assert receipt.data_quality_status == "EXECUTED_FROM_MATERIALIZED_SNAPSHOT"
    assert (await connector.estimate_cost(plan()))["cloud_bytes_billed"] == 0
    assert (await connector.get_freshness()).status.value == "AVAILABLE"
    assert await connector.test_connection() == (True, "The approved Parquet snapshot is ready.")
    assert (await connector.discover_catalog(access()))[0]["source_kind"] == "parquet_snapshot"


async def test_parquet_connector_enforces_policy_before_local_execution(tmp_path: Path) -> None:
    settings, _ = snapshot(tmp_path)
    connector = ParquetSnapshotConnector(mapping(), settings)
    await connector.initialize()
    with pytest.raises(ConnectorValidationError, match="REGION_SCOPE_VIOLATION"):
        await connector.execute_read_only(
            plan(filters=[{"dimension_id": "REGION", "values": ["SOUTHEAST"]}]), access()
        )
    assert await connector.discover_catalog(access(tenant="other")) == []
    assert not await connector.cancel_query("unknown")


async def test_uninitialized_snapshot_fails_closed(tmp_path: Path) -> None:
    connector = ParquetSnapshotConnector(mapping(), ParquetSnapshotSettings(directory=tmp_path))
    assert (await connector.get_freshness()).status.value == "NOT_READY"
    with pytest.raises(SourceNotReadyError, match="not been initialized"):
        await connector.execute_read_only(plan(), access())


async def test_duplicate_and_active_snapshot_queries_can_be_cancelled(tmp_path: Path) -> None:
    settings, _ = snapshot(tmp_path)
    connector = ParquetSnapshotConnector(mapping(), settings)
    await connector.initialize()
    request = plan()
    active = duckdb.connect(database=":memory:")
    connector._active[str(request.query_id)] = active
    try:
        with pytest.raises(ConnectorValidationError, match="QUERY_ALREADY_RUNNING"):
            await connector.execute_read_only(request, access())
        assert await connector.cancel_query(str(request.query_id))
    finally:
        connector._active.pop(str(request.query_id), None)
        active.close()


async def test_snapshot_row_count_manifest_mismatch_is_rejected(tmp_path: Path) -> None:
    settings, manifest = snapshot(tmp_path)
    path = tmp_path / ParquetSnapshotManifest.filename(mapping().fingerprint())
    path.write_text(manifest.model_copy(update={"row_count": manifest.row_count + 1}).model_dump_json())
    assert not (await ParquetSnapshotConnector(mapping(), settings).test_connection())[0]


def test_parquet_runtime_never_constructs_a_bigquery_transport(tmp_path: Path) -> None:
    snapshot_settings, _ = snapshot(tmp_path / "snapshots")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    direct = private_config(runtime)
    config = direct.model_copy(
        update={"analytics_mode": "parquet", "bigquery": None, "parquet": snapshot_settings}
    )

    def forbidden(_: Any) -> Any:
        raise AssertionError("Parquet runtime must not initialize Google BigQuery.")

    app = create_internal_app(config, transport_factory=forbidden)
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
    connector = app.state.runtime.registries["demo-telecom"].get("telecom_semantic_warehouse")
    assert connector.descriptor.connector_type == "PARQUET_SNAPSHOT"


@pytest.mark.parametrize("damage", ["file", "manifest", "stale", "missing"])
async def test_snapshot_tamper_staleness_and_absence_fail_closed(tmp_path: Path, damage: str) -> None:
    settings, manifest = snapshot(tmp_path)
    manifest_path = tmp_path / ParquetSnapshotManifest.filename(mapping().fingerprint())
    parquet = tmp_path / manifest.parquet_file
    if damage == "file":
        parquet.write_bytes(parquet.read_bytes() + b"tamper")
    elif damage == "manifest":
        payload = json.loads(manifest_path.read_text())
        payload["mapping_hash"] = "0" * 64
        manifest_path.write_text(json.dumps(payload))
    elif damage == "stale":
        payload = json.loads(manifest_path.read_text())
        payload["materialized_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        manifest_path.write_text(json.dumps(payload))
    else:
        parquet.unlink()
    connector = ParquetSnapshotConnector(mapping(), settings)
    assert (await connector.test_connection())[0] is False


def test_materializer_rejects_empty_oversized_and_wrong_schema(tmp_path: Path) -> None:
    settings = ParquetSnapshotSettings(directory=tmp_path, maximum_rows=31)
    for rows in ([], [*source_rows(), source_rows()[0]], [{"unexpected": 1}]):
        with pytest.raises(ValueError):
            SnapshotMaterializer(settings, RecordingExtract(rows)).materialize(mapping())


def test_manifest_rejects_path_traversal() -> None:
    payload = {
        "tenant_id": "tenant",
        "connector_id": "connector",
        "mapping_hash": "a" * 64,
        "source_view": "project.dataset.view",
        "source_snapshot": datetime.now(UTC),
        "materialized_at": datetime.now(UTC),
        "coverage_start": datetime.now(UTC),
        "coverage_end": datetime.now(UTC),
        "row_count": 1,
        "parquet_file": "../private.parquet",
        "parquet_sha256": hashlib.sha256(b"x").hexdigest(),
        "source_job_id": "job",
    }
    with pytest.raises(ValueError):
        ParquetSnapshotManifest.model_validate(payload)


def test_materialization_cli_uses_private_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    direct = private_config(tmp_path)
    configured = direct.model_copy(
        update={"parquet": ParquetSnapshotSettings(directory=tmp_path / "snapshots")}
    )
    config_path = tmp_path / "runtime.json"
    config_path.write_text(configured.model_dump_json())
    transport = RecordingExtract(source_rows())
    monkeypatch.setattr(
        "talk2data.operations.materialize_snapshot.GoogleSnapshotTransport", lambda _: transport
    )
    monkeypatch.setattr("sys.argv", ["materialize", "--config", str(config_path)])
    materialize_main()
    output = json.loads(capsys.readouterr().out)
    assert output[0]["source_job_id"] == "read-only-job" and transport.closed


def test_materialization_cli_requires_source_and_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = private_config(tmp_path)
    path = tmp_path / "runtime.json"
    path.write_text(config.model_dump_json())
    monkeypatch.setattr("sys.argv", ["materialize", "--config", str(path)])
    with pytest.raises(SystemExit, match="both bigquery and parquet"):
        materialize_main()
