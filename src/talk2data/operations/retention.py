"""Offline retention with preview, whole-state revision binding and transactional audit."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from talk2data.domain.runs import TERMINAL, Conversation, RunSnapshot, digest
from talk2data.operations.database import MaintenanceError, connect, offline, validate


def selection(database: sqlite3.Connection, before: datetime) -> tuple[dict[str, object], list[str]]:
    if before.tzinfo is None or before.utcoffset() is None or before > datetime.now(UTC):
        raise MaintenanceError("Retention requires an explicit past timezone-aware cutoff.")
    validate(database, "state")
    definitions = database.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='definition_streams'"
    ).fetchone()
    if database.execute("SELECT 1 FROM csv_checkpoints LIMIT 1").fetchone() or (
        definitions
        and any(
            not row[0].startswith("internal:")
            for row in database.execute("SELECT namespace FROM definition_streams")
        )
    ):
        raise MaintenanceError("This retention command is for internal state; CSV uses session expiry/clear.")
    state = {
        table: database.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()
        for table in (
            "conversations",
            "durable_runs",
            "run_events",
            *(("definition_streams",) if definitions else ()),
        )
    }
    candidates, runs_removed = [], 0
    for identifier, _, _, raw in state["conversations"]:
        conversation = Conversation.model_validate_json(raw)
        runs = [
            RunSnapshot.model_validate_json(row[-1]) for row in state["durable_runs"] if row[1] == identifier
        ]
        if any(run.status not in TERMINAL for run in runs):
            continue
        latest = max([conversation.created_at, *(run.updated_at for run in runs)])
        if latest < before:
            candidates.append(identifier)
            runs_removed += len(runs)
    report: dict[str, object] = {
        "cutoff": before.astimezone(UTC).isoformat(),
        "conversations": len(candidates),
        "runs": runs_removed,
        "plan_hash": digest({"cutoff": before.astimezone(UTC).isoformat(), "state": state}),
    }
    return report, candidates


def retain(path: Path, before: datetime, *, expected_plan: str | None = None) -> dict[str, object]:
    with offline(path), closing(connect(path, writable=expected_plan is not None)) as database:
        database.execute("BEGIN IMMEDIATE" if expected_plan is not None else "BEGIN")
        try:
            report, candidates = selection(database, before)
            if expected_plan is None:
                return {"status": "PREVIEW", **report}
            if expected_plan != report["plan_hash"]:
                raise MaintenanceError("Retention state changed. Review a new preview before applying.")
            database.execute(
                "CREATE TABLE IF NOT EXISTS retention_audit (id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, "
                "plan_hash TEXT NOT NULL, conversations INTEGER NOT NULL, runs INTEGER NOT NULL)"
            )
            database.executemany(
                "DELETE FROM conversations WHERE id=?", [(identifier,) for identifier in candidates]
            )
            database.execute(
                "INSERT INTO retention_audit VALUES (?,?,?,?,?)",
                (
                    str(uuid4()),
                    datetime.now(UTC).isoformat(),
                    report["plan_hash"],
                    report["conversations"],
                    report["runs"],
                ),
            )
            database.commit()
            return {"status": "APPLIED", **report}
        finally:
            database.rollback()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--apply-plan", help="Exact plan_hash from a reviewed preview; omission is read-only")
    args = parser.parse_args()
    try:
        result = retain(args.state, datetime.fromisoformat(args.before), expected_plan=args.apply_plan)
    except (OSError, ValueError, sqlite3.Error, MaintenanceError):
        print(json.dumps({"status": "FAILED", "reason": "RETENTION_NOT_COMPLETED"}))
        raise SystemExit(1) from None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
