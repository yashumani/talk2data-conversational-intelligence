from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from talk2data.domain.models import AccessContext, QuestionDecision, SessionMessage, SessionSnapshot


class SessionStoreError(RuntimeError):
    """Base session-persistence error."""


class SessionNotFoundError(SessionStoreError):
    """Raised when a session cannot be found."""


class SessionAccessDeniedError(SessionStoreError):
    """Raised when a session belongs to another tenant or user."""


class SQLiteSessionStore:
    """Durable local session store with tenant and user ownership checks."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    async def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._initialize_sync)

    async def health(self) -> tuple[bool, str]:
        try:
            row = await asyncio.to_thread(self._health_sync)
        except (OSError, sqlite3.Error) as exc:
            return False, f"Session store is unavailable: {exc}"
        return row == (1,), "Session store is ready."

    async def create_session(
        self,
        context: AccessContext,
        *,
        session_id: UUID | None = None,
    ) -> UUID:
        resolved_id = session_id or uuid4()
        try:
            await asyncio.to_thread(self._create_session_sync, resolved_id, context)
        except sqlite3.IntegrityError as exc:
            raise SessionStoreError(f"session {resolved_id} already exists") from exc
        return resolved_id

    async def ensure_access(self, session_id: UUID, context: AccessContext) -> None:
        row = await asyncio.to_thread(self._get_owner_sync, session_id)
        if row is None:
            raise SessionNotFoundError(f"session {session_id} was not found")
        tenant_id, user_id = row
        if tenant_id != context.tenant_id or user_id != context.user_id:
            raise SessionAccessDeniedError("session is not accessible to this tenant and user")

    async def record_evaluation(
        self,
        *,
        session_id: UUID,
        question: str,
        decision: QuestionDecision,
    ) -> None:
        await asyncio.to_thread(self._record_evaluation_sync, session_id, question, decision)

    async def get_session(
        self,
        session_id: UUID,
        *,
        tenant_id: str,
        user_id: str,
    ) -> SessionSnapshot:
        return await asyncio.to_thread(self._get_session_sync, session_id, tenant_id, user_id)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path, timeout=30.0)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize_sync(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session_created
                    ON messages(session_id, created_at);
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_decisions_session_created
                    ON decisions(session_id, created_at);
                """
            )
            connection.commit()

    def _health_sync(self) -> tuple[int]:
        with self._connection() as connection:
            row = connection.execute("SELECT 1").fetchone()
        return (0,) if row is None else (int(row[0]),)

    def _create_session_sync(self, session_id: UUID, context: AccessContext) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO sessions(id, tenant_id, user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(session_id), context.tenant_id, context.user_id, now, now),
            )
            connection.commit()

    def _get_owner_sync(self, session_id: UUID) -> tuple[str, str] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT tenant_id, user_id FROM sessions WHERE id = ?",
                (str(session_id),),
            ).fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1])

    def _record_evaluation_sync(
        self,
        session_id: UUID,
        question: str,
        decision: QuestionDecision,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO messages(id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid4()), str(session_id), "user", question, now),
            )
            connection.execute(
                "INSERT INTO messages(id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid4()), str(session_id), "system_decision", decision.user_message, now),
            )
            connection.execute(
                "INSERT INTO decisions(id, session_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (
                    str(decision.decision_id),
                    str(session_id),
                    decision.model_dump_json(),
                    decision.created_at.isoformat(),
                ),
            )
            updated = connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, str(session_id)),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise SessionNotFoundError(f"session {session_id} was not found")
            connection.commit()

    def _get_session_sync(
        self,
        session_id: UUID,
        tenant_id: str,
        user_id: str,
    ) -> SessionSnapshot:
        with self._connection() as connection:
            session_row = connection.execute(
                "SELECT tenant_id, user_id, created_at, updated_at FROM sessions WHERE id = ?",
                (str(session_id),),
            ).fetchone()
            if session_row is None:
                raise SessionNotFoundError(f"session {session_id} was not found")
            stored_tenant_id = str(session_row[0])
            stored_user_id = str(session_row[1])
            if stored_tenant_id != tenant_id or stored_user_id != user_id:
                raise SessionAccessDeniedError("session is not accessible to this tenant and user")
            message_rows = connection.execute(
                "SELECT id, role, content, created_at FROM messages "
                "WHERE session_id = ? ORDER BY created_at, id",
                (str(session_id),),
            ).fetchall()
            decision_rows = connection.execute(
                "SELECT payload_json FROM decisions WHERE session_id = ? ORDER BY created_at, id",
                (str(session_id),),
            ).fetchall()

        messages = [
            SessionMessage(
                id=UUID(str(row[0])),
                role=str(row[1]),
                content=str(row[2]),
                created_at=datetime.fromisoformat(str(row[3])),
            )
            for row in message_rows
        ]
        decisions = [
            QuestionDecision.model_validate(json.loads(str(row[0]))) for row in decision_rows
        ]
        return SessionSnapshot(
            session_id=session_id,
            tenant_id=stored_tenant_id,
            user_id=stored_user_id,
            created_at=datetime.fromisoformat(str(session_row[2])),
            updated_at=datetime.fromisoformat(str(session_row[3])),
            messages=messages,
            decisions=decisions,
        )
