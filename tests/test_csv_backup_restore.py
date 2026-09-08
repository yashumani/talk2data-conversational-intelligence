from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from talk2data.operations import backup
from talk2data.operations.database import MaintenanceError, connect
from talk2data.operations.retention import retain
from tests.test_csv_demo import new_session, upload
from tests.test_run_workflows import BASE, application, completed, payload, submit


def test_backup_restores_exact_csv_answer_definitions_and_capability(tmp_path: Path) -> None:
    path = tmp_path / "csv.db"
    with TestClient(application(path)) as client:
        auth = new_session(client)
        source = upload(client, auth)
        value = payload(client, auth)
        run = completed(client, auth, submit(client, auth, value)["run_id"])
        definitions = client.get(BASE + "/state", headers=auth).json()["definitions"]
    with pytest.raises(MaintenanceError, match="CSV"):
        retain(path, datetime.now(UTC) - timedelta(days=1))
    backup.create_bundle(path, tmp_path / "backup")
    backup.restore_bundle(tmp_path / "backup", tmp_path / "restored")
    with TestClient(application(tmp_path / "restored/state.sqlite3")) as client:
        state = client.get(BASE + "/state", headers=auth).json()
        assert state["source"] == source and state["definitions"] == definitions
        assert state["last_response"] == run["result"]
        assert submit(client, auth, value) == run
        assert len(state["sync"]["runs"]) == 1
        assert client.post(BASE + "/clear", headers=auth).status_code == 204
    with closing(connect(path, writable=True)) as database:
        database.execute("UPDATE definition_streams SET revision=revision+1")
        database.commit()
    with pytest.raises(MaintenanceError):
        backup.create_bundle(path, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_restore_discards_partial_copy_if_bytes_change_in_transit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "csv.db"
    with TestClient(application(path)) as client:
        new_session(client)
    backup.create_bundle(path, tmp_path / "backup")
    original = backup.shutil.copyfileobj

    def tamper(source: Any, target: Any) -> None:
        original(source, target)
        target.seek(0)
        target.write(b"corrupted")

    monkeypatch.setattr(backup.shutil, "copyfileobj", tamper)
    with pytest.raises(MaintenanceError, match="changed"):
        backup.restore_bundle(tmp_path / "backup", tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
