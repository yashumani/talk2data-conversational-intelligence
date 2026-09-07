"""SQLite compare-and-swap boundary for atomic snapshots, review state and publication events."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock

from talk2data.domain.governance import GovernanceState, pack_hash


class DefinitionConflict(RuntimeError):
    pass


class DefinitionUnavailable(RuntimeError):
    pass


class DefinitionStore:
    def __init__(self, path: Path | None = None) -> None:
        self._lock = RLock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(
            ":memory:" if path is None else str(path), check_same_thread=False, timeout=5
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS definition_streams "
            "(namespace TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)"
        )
        self._db.commit()

    def seed(self, namespace: str, state: GovernanceState) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO definition_streams VALUES (?, ?, ?)",
                (namespace, state.revision, state.model_dump_json()),
            )

    def read(self, namespace: str) -> GovernanceState:
        with self._lock:
            row = self._db.execute(
                "SELECT revision, payload FROM definition_streams WHERE namespace = ?", (namespace,)
            ).fetchone()
        if row is None:
            raise DefinitionUnavailable("Definition workspace is unavailable.")
        try:
            state = GovernanceState.model_validate_json(row[1])
            if (
                state.revision != row[0]
                or not state.snapshots
                or any(snapshot.snapshot_id != pack_hash(snapshot.pack) for snapshot in state.snapshots)
            ):
                raise ValueError("Definition snapshot integrity failed.")
        except ValueError as exc:
            raise DefinitionUnavailable("Definition snapshot integrity failed.") from exc
        return state

    def save(self, namespace: str, state: GovernanceState, expected: int) -> None:
        state.revision = expected + 1
        with self._lock, self._db:
            changed = self._db.execute(
                "UPDATE definition_streams SET revision = ?, payload = ? "
                "WHERE namespace = ? AND revision = ?",
                (state.revision, state.model_dump_json(), namespace, expected),
            ).rowcount
            if changed != 1:
                raise DefinitionConflict("Definitions changed. Refresh before retrying.")

    def delete(self, namespace: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM definition_streams WHERE namespace = ?", (namespace,))

    def close(self) -> None:
        self._db.close()
