from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from talk2data.domain.runs import RunRequest
from talk2data.operations import backup, retention
from talk2data.operations.database import MaintenanceError, connect, validate
from talk2data.services.definition_store import DefinitionStore
from talk2data.services.run_store import RunStore


def state(path: Path, *, old: bool = False) -> dict[str, Any]:
    store = RunStore(path)
    conversation = store.create_conversation("owner", "scope")
    request = RunRequest(
        client_request_id=uuid4(),
        conversation_id=conversation.conversation_id,
        expected_revision=0,
        question="Synthetic question",
        as_of=datetime.now(UTC),
        source_fingerprint="a" * 64,
        definition_snapshot_id="b" * 64,
    )
    run = store.enqueue("owner", "scope", request, "a" * 64)
    store.start(run.run_id)
    run = store.finish(run.run_id, "FAILED", code="SYNTHETIC_TEST", message="No answer released.")
    if old:
        at = datetime.now(UTC) - timedelta(days=60)
        conversation = store.conversation("owner", "scope", conversation.conversation_id)
        conversation.created_at = at
        run.created_at = run.updated_at = at
        with store.transaction() as database:
            database.execute(
                "UPDATE conversations SET payload=? WHERE id=?",
                (conversation.model_dump_json(), str(conversation.conversation_id)),
            )
            database.execute(
                "UPDATE durable_runs SET payload=? WHERE id=?", (run.model_dump_json(), str(run.run_id))
            )
    store.close()
    return {"run": run, "conversation": conversation}


def test_backup_restore_preserves_runs_events_and_never_redispatches(tmp_path: Path) -> None:
    path, bundle, restored = (tmp_path / name for name in ("source.db", "backup", "restored"))
    saved = state(path)
    manifest = backup.create_bundle(path, bundle)
    assert manifest.state.bytes > 0 and (bundle / "state.sqlite3").stat().st_mode & 0o777 == 0o600
    assert backup.restore_bundle(bundle, restored) == manifest
    store = RunStore(restored / "state.sqlite3")
    try:
        result = store.read("owner", "scope", saved["run"].run_id)
        assert result == saved["run"]
        assert [e.sequence for e in store.events("owner", "scope", result.run_id, 0)] == [1, 2, 3]
    finally:
        store.close()
    for target in (bundle, restored):
        with pytest.raises(MaintenanceError):
            backup.restore_bundle(bundle, target)
    with pytest.raises(MaintenanceError):
        backup.create_bundle(path, bundle)
    with pytest.raises(MaintenanceError):
        backup.restore_bundle(bundle, bundle / "nested")


def test_backup_refuses_live_worker_and_relative_or_symlink_input(tmp_path: Path) -> None:
    path = tmp_path / "source.db"
    store = RunStore(path)
    try:
        with pytest.raises(MaintenanceError, match="Stop"):
            backup.create_bundle(path, tmp_path / "copy")
    finally:
        store.close()
    linked = tmp_path / "linked.db"
    linked.symlink_to(path)
    for invalid in (linked, Path("relative.db"), tmp_path / "missing.db"):
        with pytest.raises(MaintenanceError):
            backup.create_bundle(invalid, tmp_path / "copy")
    with pytest.raises(MaintenanceError):
        backup.create_bundle(path, Path("relative"))
    with pytest.raises(MaintenanceError):
        connect(linked)


def test_backup_can_include_separate_governance_database(tmp_path: Path) -> None:
    path, definitions = tmp_path / "source.db", tmp_path / "definitions.db"
    state(path)
    DefinitionStore(definitions).close()
    manifest = backup.create_bundle(path, tmp_path / "copy", definitions)
    assert manifest.definitions is not None
    backup.restore_bundle(tmp_path / "copy", tmp_path / "restored")
    with closing(connect(tmp_path / "restored/definitions.sqlite3")) as database:
        validate(database, "definitions")
    for invalid in (path, Path("relative.db")):
        with pytest.raises(MaintenanceError):
            backup.create_bundle(path, tmp_path / "invalid", invalid)


@pytest.mark.parametrize("damage", ["digest", "size", "version", "json", "symlink", "manifest_link"])
def test_corrupt_backup_fails_before_creating_restore_directory(tmp_path: Path, damage: str) -> None:
    path, bundle, restored = tmp_path / "source.db", tmp_path / "backup", tmp_path / "restored"
    state(path)
    backup.create_bundle(path, bundle)
    manifest = bundle / "manifest.json"
    value = json.loads(manifest.read_text())
    if damage == "digest":
        value["state"]["sha256"] = "0" * 64
    if damage == "size":
        value["state"]["bytes"] += 1
    if damage == "version":
        value["version"] = 2
    manifest.write_text("invalid" if damage == "json" else json.dumps(value))
    if damage == "symlink":
        (bundle / "state.sqlite3").unlink()
        (bundle / "state.sqlite3").symlink_to(path)
    if damage == "manifest_link":
        manifest.rename(tmp_path / "manifest.json")
        manifest.symlink_to(tmp_path / "manifest.json")
    with pytest.raises(MaintenanceError):
        backup.restore_bundle(bundle, restored)
    assert not restored.exists()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE run_schema SET version=2",
        "DROP TABLE csv_checkpoints",
        "UPDATE durable_runs SET status='COMPLETED'",
        "UPDATE durable_runs SET payload='{}'",
        "UPDATE conversations SET payload='{}'",
        "UPDATE conversations SET payload=json_set(payload,'$.revision',99)",
        "UPDATE durable_runs SET conversation='missing-conversation'",
        "DELETE FROM run_events WHERE sequence=2",
        "UPDATE run_events SET sequence=99 WHERE sequence=3",
        "UPDATE run_events SET payload=json_set(payload,'$.status','QUEUED') WHERE sequence=3",
    ],
)
def test_invalid_persisted_contract_is_not_backed_up(tmp_path: Path, sql: str) -> None:
    path = tmp_path / "source.db"
    state(path)
    with closing(sqlite3.connect(path)) as database:
        database.execute(sql)
        database.commit()
    with pytest.raises(MaintenanceError):
        backup.create_bundle(path, tmp_path / "copy")
    assert not (tmp_path / "copy").exists()


def test_retention_preview_stale_rejection_atomic_delete_and_audit(tmp_path: Path) -> None:
    path = tmp_path / "source.db"
    saved = state(path, old=True)
    cutoff = datetime.now(UTC) - timedelta(days=30)
    preview = retention.retain(path, cutoff)
    assert preview["status"] == "PREVIEW" and preview["conversations"] == preview["runs"] == 1
    with closing(connect(path)) as database:
        assert database.execute("SELECT count(*) FROM conversations").fetchone() == (1,)
    with pytest.raises(MaintenanceError, match="changed"):
        retention.retain(path, cutoff, expected_plan="wrong")
    # A distinct metadata change between preview and apply invalidates the exact plan.
    store = RunStore(path)
    store.create_conversation("another-owner", "scope")
    store.close()
    with pytest.raises(MaintenanceError, match="changed"):
        retention.retain(path, cutoff, expected_plan=str(preview["plan_hash"]))
    current = retention.retain(path, cutoff)
    applied = retention.retain(path, cutoff, expected_plan=str(current["plan_hash"]))
    assert applied["status"] == "APPLIED"
    with closing(connect(path)) as database:
        assert database.execute("SELECT count(*) FROM conversations").fetchone() == (1,)
        assert database.execute("SELECT count(*) FROM durable_runs").fetchone() == (0,)
        assert database.execute("SELECT count(*) FROM run_events").fetchone() == (0,)
        assert database.execute("SELECT conversations,runs FROM retention_audit").fetchone() == (1, 1)
        assert str(saved["conversation"].conversation_id) not in str(
            database.execute("SELECT * FROM retention_audit").fetchall()
        )


def test_retention_preserves_active_recent_and_csv_workspaces(tmp_path: Path) -> None:
    path = tmp_path / "source.db"
    saved = state(path, old=True)
    with closing(sqlite3.connect(path)) as database:
        # Restore a consistent accepted, interrupted-in-flight fixture without starting a worker.
        run = saved["run"]
        run.status = "RUNNING"
        database.execute("UPDATE durable_runs SET status=?,payload=?", (run.status, run.model_dump_json()))
        database.execute(
            "UPDATE run_events SET payload=json_set(payload,'$.status','RUNNING') WHERE sequence=3"
        )
        database.commit()
    cutoff = datetime.now(UTC) - timedelta(days=30)
    assert retention.retain(path, cutoff)["conversations"] == 0
    for invalid in (datetime.now(), datetime.now(UTC) + timedelta(days=1)):
        with pytest.raises(MaintenanceError):
            retention.retain(path, invalid)
    with closing(sqlite3.connect(path)) as database:
        database.execute("INSERT INTO csv_checkpoints VALUES ('token-hash','{}')")
        database.commit()
    with pytest.raises(MaintenanceError, match="CSV"):
        retention.retain(path, cutoff)


def test_retention_rolls_back_deletion_if_audit_write_fails(tmp_path: Path) -> None:
    path = tmp_path / "source.db"
    state(path, old=True)
    cutoff = datetime.now(UTC) - timedelta(days=30)
    with closing(sqlite3.connect(path)) as database:
        database.executescript(
            "CREATE TABLE retention_audit (id TEXT, occurred_at TEXT, plan_hash TEXT, "
            "conversations INT, runs INT); CREATE TRIGGER fail_audit BEFORE INSERT ON retention_audit "
            "BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END;"
        )
    preview = retention.retain(path, cutoff)
    with pytest.raises(sqlite3.IntegrityError):
        retention.retain(path, cutoff, expected_plan=str(preview["plan_hash"]))
    with closing(connect(path)) as database:
        assert database.execute("SELECT count(*) FROM conversations").fetchone() == (1,)


def test_operator_clis_report_safe_failures_and_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    path, bundle, restored = tmp_path / "private-secret-name.db", tmp_path / "backup", tmp_path / "restored"
    monkeypatch.setattr("sys.argv", ["backup", "create", "--state", str(path), "--destination", str(bundle)])
    with pytest.raises(SystemExit):
        backup.main()
    assert "private-secret" not in capsys.readouterr().out
    state(path, old=True)
    backup.main()
    assert '"VERIFIED"' in capsys.readouterr().out
    monkeypatch.setattr(
        "sys.argv", ["backup", "restore", "--bundle", str(bundle), "--destination", str(restored)]
    )
    backup.main()
    assert '"VERIFIED"' in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["retention", "--state", str(path), "--before", "invalid-private-value"])
    with pytest.raises(SystemExit):
        retention.main()
    assert "invalid-private-value" not in capsys.readouterr().out
    monkeypatch.setattr(
        "sys.argv",
        ["retention", "--state", str(path), "--before", (datetime.now(UTC) - timedelta(days=30)).isoformat()],
    )
    retention.main()
    assert '"PREVIEW"' in capsys.readouterr().out
