"""Single-worker SQLite run journal. State and replay events commit in the same transaction."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from threading import RLock
from typing import Any, BinaryIO
from uuid import UUID

from talk2data.domain.agents import AgentRunReport
from talk2data.domain.chat import DemoChatResponse
from talk2data.domain.runs import (
    TERMINAL,
    Conversation,
    RunError,
    RunEvent,
    RunRequest,
    RunSnapshot,
    RunStatus,
    digest,
    now,
)


def exclusive_worker(stream: BinaryIO) -> None:
    try:
        import fcntl
    except ImportError:
        msvcrt = import_module("msvcrt")

        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)


class RunStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = RLock()
        self._lease: BinaryIO | None = None
        if path is not None:
            if not path.is_absolute():
                raise ValueError("Run storage requires an absolute private path.")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._lease = path.with_suffix(path.suffix + ".lock").open("ab")
            try:
                exclusive_worker(self._lease)
            except OSError:
                self._lease.close()
                raise ValueError("This state database already has an application worker.") from None
        self._db = sqlite3.connect(
            ":memory:" if path is None else str(path), check_same_thread=False, timeout=5
        )
        if path is not None:
            path.chmod(0o600)
        schema_exists = self._db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_schema'"
        ).fetchone()
        if schema_exists and [r[0] for r in self._db.execute("SELECT version FROM run_schema")] != [1]:
            self.close()
            raise ValueError("The run database schema needs an approved migration.")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS run_schema (version INTEGER PRIMARY KEY);
            INSERT OR IGNORE INTO run_schema VALUES (1);
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS durable_runs (
                id TEXT PRIMARY KEY,
                conversation TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                request_id TEXT NOT NULL, request_hash TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL,
                UNIQUE(conversation, request_id));
            CREATE TABLE IF NOT EXISTS run_events (
                run_id TEXT NOT NULL REFERENCES durable_runs(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id, sequence));
            CREATE TABLE IF NOT EXISTS csv_checkpoints (token_hash TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)
        self.recover()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

    def create_conversation(self, owner: str, scope: str, identifier: UUID | None = None) -> Conversation:
        conversation = Conversation(**({"conversation_id": identifier} if identifier else {}))
        with self.transaction() as db:
            if db.execute("SELECT count(*) FROM conversations").fetchone()[0] >= 512:
                raise RunError(
                    "Conversation storage is full. Delete old conversations before continuing.", 429
                )
            if db.execute("SELECT count(*) FROM conversations WHERE owner=?", (owner,)).fetchone()[0] >= 16:
                raise RunError("This identity has reached its conversation limit.", 429)
            db.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?)",
                (str(conversation.conversation_id), owner, scope, conversation.model_dump_json()),
            )
        return conversation

    @staticmethod
    def _conversation(db: sqlite3.Connection, owner: str, scope: str, identifier: UUID) -> Conversation:
        row = db.execute(
            "SELECT owner, scope, payload FROM conversations WHERE id=?", (str(identifier),)
        ).fetchone()
        if row is None or row[0] != owner or row[1] != scope:
            raise RunError("Conversation is unavailable to this identity and access scope.", 404)
        return Conversation.model_validate_json(row[2])

    def conversation(self, owner: str, scope: str, identifier: UUID) -> Conversation:
        with self._lock:
            return self._conversation(self._db, owner, scope, identifier)

    def conversations(self, owner: str, scope: str) -> list[Conversation]:
        with self._lock:
            return [
                Conversation.model_validate_json(r[0])
                for r in self._db.execute(
                    "SELECT payload FROM conversations WHERE owner=? AND scope=? ORDER BY rowid DESC",
                    (owner, scope),
                )
            ]

    def _read(self, db: sqlite3.Connection, identifier: UUID) -> RunSnapshot:
        row = db.execute("SELECT payload FROM durable_runs WHERE id=?", (str(identifier),)).fetchone()
        if row is None:
            raise RunError("Run is unavailable.", 404)
        return RunSnapshot.model_validate_json(row[0])

    def read(self, owner: str, scope: str, identifier: UUID) -> RunSnapshot:
        with self._lock:
            run = self._read(self._db, identifier)
            self._conversation(self._db, owner, scope, run.request.conversation_id)
            return run

    def runs(self, owner: str, scope: str, conversation_id: UUID) -> list[RunSnapshot]:
        with self._lock:
            self._conversation(self._db, owner, scope, conversation_id)
            return [
                RunSnapshot.model_validate_json(r[0])
                for r in self._db.execute(
                    "SELECT payload FROM durable_runs WHERE conversation=? ORDER BY rowid",
                    (str(conversation_id),),
                )
            ]

    def existing(self, owner: str, scope: str, request: RunRequest) -> RunSnapshot | None:
        with self._lock:
            self._conversation(self._db, owner, scope, request.conversation_id)
            row = self._db.execute(
                "SELECT request_hash, payload FROM durable_runs WHERE conversation=? AND request_id=?",
                (str(request.conversation_id), str(request.client_request_id)),
            ).fetchone()
            if row is None:
                return None
            if row[0] != digest(request.model_dump(mode="json")):
                raise RunError("This request ID already belongs to a different question or revision.")
            return RunSnapshot.model_validate_json(row[1])

    def enqueue(self, owner: str, scope: str, request: RunRequest, binding: str) -> RunSnapshot:
        run = RunSnapshot(request=request, source_binding=binding)
        with self.transaction() as db:
            conversation = self._conversation(db, owner, scope, request.conversation_id)
            if conversation.revision != request.expected_revision:
                raise RunError("Conversation changed. Refresh before submitting another question.")
            if (
                db.execute(
                    "SELECT count(*) FROM durable_runs WHERE conversation=?", (str(request.conversation_id),)
                ).fetchone()[0]
                >= 64
            ):
                raise RunError("This conversation has reached its 64-run limit.", 429)
            if db.execute(
                "SELECT 1 FROM durable_runs WHERE conversation=? "
                "AND status IN ('QUEUED','RUNNING','CANCELLATION_REQUESTED')",
                (str(request.conversation_id),),
            ).fetchone():
                raise RunError("This conversation already has an active question.")
            conversation.revision += 1
            conversation.latest_run_id = run.run_id
            conversation.title = request.question[:80]
            db.execute(
                "UPDATE conversations SET payload=? WHERE id=?",
                (conversation.model_dump_json(), str(conversation.conversation_id)),
            )
            db.execute(
                "INSERT INTO durable_runs VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(run.run_id),
                    str(request.conversation_id),
                    str(request.client_request_id),
                    digest(request.model_dump(mode="json")),
                    run.status,
                    run.model_dump_json(),
                ),
            )
            self._write(db, run, "run.accepted")
        return run

    @staticmethod
    def _write(db: sqlite3.Connection, run: RunSnapshot, event_type: str) -> None:
        run.sequence += 1
        run.updated_at = now()
        event = RunEvent(
            run_id=run.run_id,
            sequence=run.sequence,
            type=event_type,
            status=run.status,
            progress=run.progress,
        )
        db.execute(
            "UPDATE durable_runs SET payload=?, status=? WHERE id=?",
            (run.model_dump_json(), run.status, str(run.run_id)),
        )
        db.execute(
            "INSERT INTO run_events VALUES (?, ?, ?)",
            (str(run.run_id), run.sequence, event.model_dump_json()),
        )

    def start(self, identifier: UUID) -> bool:
        with self.transaction() as db:
            run = self._read(db, identifier)
            if run.status != "QUEUED":
                return False
            run.status, run.message = "RUNNING", "Processing the governed question."
            self._write(db, run, "run.started")
            return True

    def progress(self, identifier: UUID, report: AgentRunReport) -> None:
        with self.transaction() as db:
            run = self._read(db, identifier)
            if run.status != "RUNNING":
                return
            if run.sequence >= 60:
                raise RunError("Progress event budget was reached.")
            run.progress = report.model_copy(deep=True)
            self._write(db, run, "agent.progress")

    def finish(
        self,
        identifier: UUID,
        status: RunStatus,
        *,
        result: DemoChatResponse | None = None,
        code: str | None = None,
        message: str = "Run finished.",
    ) -> RunSnapshot:
        if status not in TERMINAL:
            raise RunError("A terminal run state is required.")
        with self.transaction() as db:
            run = self._read(db, identifier)
            if run.status in TERMINAL:
                return run
            if run.status == "CANCELLATION_REQUESTED" and status != "INTERRUPTED":
                status, result, code, message = (
                    "CANCELLED",
                    None,
                    None,
                    "Cancellation confirmed; no answer released.",
                )
            run.status, run.result, run.error_code, run.message = status, result, code, message
            if result is not None:
                run.progress = result.agent_run
            self._write(db, run, "run." + status.lower())
            return run

    def cancel(self, owner: str, scope: str, identifier: UUID) -> RunSnapshot:
        with self.transaction() as db:
            run = self._read(db, identifier)
            self._conversation(db, owner, scope, run.request.conversation_id)
            if run.status not in TERMINAL and run.status != "CANCELLATION_REQUESTED":
                run.status, run.message = "CANCELLATION_REQUESTED", "Cancellation requested."
                self._write(db, run, "run.cancellation_requested")
            return run

    def events(self, owner: str, scope: str, identifier: UUID, after: int) -> list[RunEvent]:
        with self._lock:
            run = self.read(owner, scope, identifier)
            if after < 0 or after > run.sequence:
                raise RunError("Replay cursor is outside this run's event history.")
            return [
                RunEvent.model_validate_json(r[0])
                for r in self._db.execute(
                    "SELECT payload FROM run_events WHERE run_id=? AND sequence>? ORDER BY sequence",
                    (str(identifier), after),
                )
            ]

    def recover(self) -> None:
        # A process restart cannot prove whether a remote call ran. Never auto-dispatch it again.
        with self._lock:
            ids = [
                r[0]
                for r in self._db.execute(
                    "SELECT id FROM durable_runs "
                    "WHERE status IN ('QUEUED','RUNNING','CANCELLATION_REQUESTED')"
                )
            ]
        for identifier in ids:
            self.finish(
                UUID(identifier),
                "INTERRUPTED",
                code="WORKER_RESTARTED",
                message="Processing was interrupted. Review before submitting a new request.",
            )

    def delete(self, owner: str, scope: str, identifier: UUID) -> None:
        with self.transaction() as db:
            self._conversation(db, owner, scope, identifier)
            if db.execute(
                "SELECT 1 FROM durable_runs WHERE conversation=? "
                "AND status IN ('QUEUED','RUNNING','CANCELLATION_REQUESTED')",
                (str(identifier),),
            ).fetchone():
                raise RunError("Cancel the active run before deleting its conversation.")
            db.execute("DELETE FROM conversations WHERE id=?", (str(identifier),))

    def checkpoint(self, token: str, payload: dict[str, Any] | None) -> None:
        key = digest(token)
        with self.transaction() as db:
            if payload is None:
                db.execute("DELETE FROM csv_checkpoints WHERE token_hash=?", (key,))
            else:
                db.execute(
                    "INSERT INTO csv_checkpoints VALUES (?, ?) "
                    "ON CONFLICT(token_hash) DO UPDATE SET payload=excluded.payload",
                    (key, json.dumps(payload)),
                )

    def restore(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM csv_checkpoints WHERE token_hash=?", (digest(token),)
            ).fetchone()
        return None if row is None else dict(json.loads(row[0]))

    def checkpoint_count(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT count(*) FROM csv_checkpoints").fetchone()[0])

    def prune_checkpoints(self, wall_time: float) -> list[str]:
        deleted = []
        with self.transaction() as db:
            for key, raw in db.execute("SELECT token_hash, payload FROM csv_checkpoints").fetchall():
                payload = json.loads(raw)
                if payload["expires_wall"] > wall_time:
                    continue
                identifier = payload["conversation_id"]
                if db.execute(
                    "SELECT 1 FROM durable_runs WHERE conversation=? "
                    "AND status IN ('QUEUED','RUNNING','CANCELLATION_REQUESTED')",
                    (identifier,),
                ).fetchone():
                    continue
                db.execute("DELETE FROM conversations WHERE id=?", (identifier,))
                db.execute("DELETE FROM csv_checkpoints WHERE token_hash=?", (key,))
                deleted.append(payload["user_id"])
        return deleted

    def close(self) -> None:
        self._db.close()
        if self._lease is not None:
            self._lease.close()
