"""Offline SQLite maintenance: exclusive worker ownership, validation and safe new copies."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from talk2data.domain.governance import GovernanceState, pack_hash
from talk2data.domain.runs import Conversation, RunEvent, RunSnapshot
from talk2data.services.run_store import exclusive_worker


class MaintenanceError(RuntimeError):
    pass


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@contextmanager
def offline(path: Path) -> Iterator[None]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise MaintenanceError("An existing absolute regular state file is required.")
    with path.with_suffix(path.suffix + ".lock").open("ab") as lease:
        try:
            exclusive_worker(lease)
        except OSError:
            raise MaintenanceError("Stop the application worker before maintenance.") from None
        yield


def connect(path: Path, *, writable: bool = False) -> sqlite3.Connection:
    if path.is_symlink() or not path.is_file():
        raise MaintenanceError("A regular existing database file is required.")
    database = sqlite3.connect(path.as_uri() + ("?mode=rw" if writable else "?mode=ro"), uri=True)
    database.execute("PRAGMA foreign_keys=ON")
    return database


def validate(database: sqlite3.Connection, kind: Literal["state", "definitions"]) -> None:
    try:
        if database.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Integrity check failed.")
        if database.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Foreign key check failed.")
        tables = {r[0] for r in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if kind == "state":
            if not {"run_schema", "conversations", "durable_runs", "run_events", "csv_checkpoints"} <= tables:
                raise ValueError("Missing state tables.")
            if database.execute("SELECT version FROM run_schema").fetchall() != [(1,)]:
                raise ValueError("Unsupported state schema.")
            for identifier, payload in database.execute("SELECT id,payload FROM conversations"):
                conversation = Conversation.model_validate_json(payload)
                identifiers = [
                    r[0]
                    for r in database.execute(
                        "SELECT id FROM durable_runs WHERE conversation=? ORDER BY rowid", (identifier,)
                    )
                ]
                if (
                    str(conversation.conversation_id) != identifier
                    or conversation.revision != len(identifiers)
                    or (
                        str(conversation.latest_run_id) != identifiers[-1]
                        if identifiers
                        else conversation.latest_run_id is not None
                    )
                ):
                    raise ValueError("Conversation revision/history mismatch.")
            for identifier, conversation_id, status, payload in database.execute(
                "SELECT id,conversation,status,payload FROM durable_runs"
            ):
                run = RunSnapshot.model_validate_json(payload)
                if (
                    str(run.run_id) != identifier
                    or run.status != status
                    or str(run.request.conversation_id) != conversation_id
                ):
                    raise ValueError("Run identity/status mismatch.")
                records = database.execute(
                    "SELECT sequence,payload FROM run_events WHERE run_id=? ORDER BY sequence", (identifier,)
                ).fetchall()
                events = [RunEvent.model_validate_json(row[1]) for row in records]
                if [e.sequence for e in events] != list(range(1, run.sequence + 1)) or any(
                    e.run_id != run.run_id or e.sequence != row[0]
                    for e, row in zip(events, records, strict=True)
                ):
                    raise ValueError("Run event history mismatch.")
                if not events or events[-1].status != run.status:
                    raise ValueError("Run terminal event mismatch.")
        if kind == "definitions" or "definition_streams" in tables:
            for revision, payload in database.execute("SELECT revision,payload FROM definition_streams"):
                state = GovernanceState.model_validate_json(payload)
                if (
                    state.revision != revision
                    or not state.snapshots
                    or any(snapshot.snapshot_id != pack_hash(snapshot.pack) for snapshot in state.snapshots)
                ):
                    raise ValueError("Definition integrity check failed.")
    except (sqlite3.Error, ValueError):
        raise MaintenanceError("Database schema or persisted record integrity failed.") from None
