"""Transactional admission, replay and fenced execution; no uncertain job is redispatched."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import psycopg

from talk2data.domain.agents import AgentRunReport
from talk2data.domain.chat import DemoChatResponse
from talk2data.domain.execution import ExecutionGrant
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
    principal,
)
from talk2data.services.postgres_database import PostgresDatabase

DB = psycopg.Connection[tuple[Any, ...]]


class LeaseLost(RunError):
    def __init__(self) -> None:
        super().__init__("Execution ownership expired or changed; no answer was released.")


@dataclass(frozen=True)
class ClaimedRun:
    run: RunSnapshot
    grant: ExecutionGrant
    fence: UUID


class PostgresRunStore:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database
        self.settings = database.settings

    @staticmethod
    def _conversation(db: DB, owner: str, scope: str, identifier: UUID) -> Conversation:
        row = db.execute(
            "SELECT owner,scope,payload FROM t2d_conversations WHERE id=%s FOR UPDATE", (identifier,)
        ).fetchone()
        if row is None or row[0] != owner or row[1] != scope:
            raise RunError("Conversation is unavailable to this identity and access scope.", 404)
        return Conversation.model_validate_json(row[2])

    @staticmethod
    def _read(db: DB, identifier: UUID) -> RunSnapshot:
        row = db.execute("SELECT payload FROM t2d_runs WHERE id=%s FOR UPDATE", (identifier,)).fetchone()
        if row is None:
            raise RunError("Run is unavailable.", 404)
        return RunSnapshot.model_validate_json(row[0])

    def create_conversation(self, owner: str, scope: str, identifier: UUID | None = None) -> Conversation:
        value = Conversation(conversation_id=identifier or uuid4())
        with self.database.transaction() as db:
            db.execute("SELECT id FROM t2d_admission WHERE id=1 FOR UPDATE")
            total, owned = db.execute(
                "SELECT count(*),count(*) FILTER(WHERE owner=%s) FROM t2d_conversations", (owner,)
            ).fetchone()  # type: ignore[misc]
            if total >= self.settings.maximum_conversations or owned >= 16:
                raise RunError("Conversation capacity is occupied. Remove old conversations.", 429)
            db.execute(
                "INSERT INTO t2d_conversations(id,owner,scope,payload) VALUES (%s,%s,%s,%s)",
                (value.conversation_id, owner, scope, value.model_dump_json()),
            )
        return value

    def conversation(self, owner: str, scope: str, identifier: UUID) -> Conversation:
        with self.database.transaction() as db:
            return self._conversation(db, owner, scope, identifier)

    def conversations(self, owner: str, scope: str) -> list[Conversation]:
        with self.database.transaction() as db:
            return [
                Conversation.model_validate_json(r[0])
                for r in db.execute(
                    "SELECT payload FROM t2d_conversations WHERE owner=%s AND scope=%s "
                    "ORDER BY created_at DESC,id",
                    (owner, scope),
                )
            ]

    def read(self, owner: str, scope: str, identifier: UUID) -> RunSnapshot:
        with self.database.transaction() as db:
            run = self._read(db, identifier)
            # Reads lock the run first; all methods which also modify runs use this order.
            row = db.execute(
                "SELECT owner,scope FROM t2d_conversations WHERE id=%s", (run.request.conversation_id,)
            ).fetchone()
            if row != (owner, scope):
                raise RunError("Run is unavailable to this identity and access scope.", 404)
            return run

    def runs(self, owner: str, scope: str, conversation_id: UUID) -> list[RunSnapshot]:
        with self.database.transaction() as db:
            self._conversation(db, owner, scope, conversation_id)
            return [
                RunSnapshot.model_validate_json(r[0])
                for r in db.execute(
                    "SELECT payload FROM t2d_runs WHERE conversation=%s ORDER BY created_at,id",
                    (conversation_id,),
                )
            ]

    @staticmethod
    def _existing(db: DB, request: RunRequest) -> RunSnapshot | None:
        row = db.execute(
            "SELECT request_hash,payload FROM t2d_runs WHERE conversation=%s AND request_id=%s",
            (request.conversation_id, request.client_request_id),
        ).fetchone()
        if row is None:
            return None
        if row[0] != digest(request.model_dump(mode="json")):
            raise RunError("This request ID already belongs to a different question or revision.")
        return RunSnapshot.model_validate_json(row[1])

    def existing(self, owner: str, scope: str, request: RunRequest) -> RunSnapshot | None:
        with self.database.transaction() as db:
            self._conversation(db, owner, scope, request.conversation_id)
            return self._existing(db, request)

    def enqueue(
        self, owner: str, scope: str, request: RunRequest, binding: str, grant: ExecutionGrant
    ) -> RunSnapshot:
        if principal("internal", grant.access) != (owner, scope) or request.source_fingerprint is not None:
            raise RunError("Execution authority or internal source binding is invalid.", 403)
        with self.database.transaction() as db:
            db.execute("SELECT id FROM t2d_admission WHERE id=1 FOR UPDATE")
            conversation = self._conversation(db, owner, scope, request.conversation_id)
            existing = self._existing(db, request)
            if existing is not None:
                return existing
            if not db.execute("SELECT %s > clock_timestamp()", (grant.expires_at,)).fetchone()[0]:  # type: ignore[index]
                raise RunError("Execution authority expired. Refresh your signed session.", 401)
            if conversation.revision != request.expected_revision:
                raise RunError("Conversation changed. Refresh before submitting another question.")
            total, active = db.execute(
                "SELECT count(*),count(*) FILTER(WHERE status IN "
                "('QUEUED','RUNNING','CANCELLATION_REQUESTED')) "
                "FROM t2d_runs WHERE conversation=%s",
                (request.conversation_id,),
            ).fetchone()  # type: ignore[misc]
            if active:
                raise RunError("This conversation already has an active question.")
            pending = db.execute("SELECT count(*) FROM t2d_runs WHERE status='QUEUED'").fetchone()[0]  # type: ignore[index]
            if total >= 64 or pending >= self.settings.maximum_pending:
                raise RunError("Run capacity is occupied. Retry the same request ID later.", 429)
            run = RunSnapshot(request=request, source_binding=binding)
            conversation.revision += 1
            conversation.latest_run_id, conversation.title = run.run_id, request.question[:80]
            db.execute(
                "UPDATE t2d_conversations SET payload=%s WHERE id=%s",
                (conversation.model_dump_json(), conversation.conversation_id),
            )
            db.execute(
                "INSERT INTO t2d_runs(id,conversation,request_id,request_hash,status,payload,"
                "grant_payload,tenant,binding,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    run.run_id,
                    request.conversation_id,
                    request.client_request_id,
                    digest(request.model_dump(mode="json")),
                    run.status,
                    run.model_dump_json(),
                    grant.model_dump_json(),
                    grant.access.tenant_id,
                    binding,
                    grant.expires_at,
                ),
            )
            self._write(db, run, "run.accepted")
            return run

    @staticmethod
    def _write(db: DB, run: RunSnapshot, event_type: str) -> None:
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
            "UPDATE t2d_runs SET payload=%s,status=%s WHERE id=%s",
            (run.model_dump_json(), run.status, run.run_id),
        )
        db.execute(
            "INSERT INTO t2d_events VALUES (%s,%s,%s)", (run.run_id, event.sequence, event.model_dump_json())
        )

    def cancel(self, owner: str, scope: str, identifier: UUID) -> RunSnapshot:
        with self.database.transaction() as db:
            run = self._read(db, identifier)
            row = db.execute(
                "SELECT owner,scope FROM t2d_conversations WHERE id=%s", (run.request.conversation_id,)
            ).fetchone()
            if row != (owner, scope):
                raise RunError("Run is unavailable to this identity and access scope.", 404)
            if run.status not in TERMINAL and run.status != "CANCELLATION_REQUESTED":
                run.status = "CANCELLED" if run.status == "QUEUED" else "CANCELLATION_REQUESTED"
                run.message = "Cancellation requested; no answer will be released."
                self._write(db, run, "run." + run.status.lower())
            return run

    def events(self, owner: str, scope: str, identifier: UUID, after: int) -> list[RunEvent]:
        run = self.read(owner, scope, identifier)
        if after < 0 or after > run.sequence:
            raise RunError("Replay cursor is outside this run's event history.")
        with self.database.transaction() as db:
            return [
                RunEvent.model_validate_json(r[0])
                for r in db.execute(
                    "SELECT payload FROM t2d_events WHERE run_id=%s AND sequence>%s ORDER BY sequence",
                    (identifier, after),
                )
            ]

    def delete(self, owner: str, scope: str, identifier: UUID) -> None:
        with self.database.transaction() as db:
            db.execute("SELECT id FROM t2d_admission WHERE id=1 FOR UPDATE")
            self._conversation(db, owner, scope, identifier)
            if db.execute(
                "SELECT 1 FROM t2d_runs WHERE conversation=%s AND status IN "
                "('QUEUED','RUNNING','CANCELLATION_REQUESTED')",
                (identifier,),
            ).fetchone():
                raise RunError("Cancel the active run before deleting its conversation.")
            db.execute("DELETE FROM t2d_conversations WHERE id=%s", (identifier,))

    def claim(self, binding: str) -> ClaimedRun | None:
        with self.database.transaction() as db:
            db.execute("SELECT id FROM t2d_admission WHERE id=1 FOR UPDATE")
            # Database time, not a worker's wall clock, controls fencing and recovery.
            for expired_row in db.execute(
                "SELECT payload FROM t2d_runs WHERE "
                "(status IN ('RUNNING','CANCELLATION_REQUESTED') AND lease_until<=clock_timestamp()) "
                "OR (status='QUEUED' AND expires_at<=clock_timestamp()) FOR UPDATE"
            ).fetchall():
                run = RunSnapshot.model_validate_json(expired_row[0])
                run.status, run.error_code = "INTERRUPTED", "EXECUTION_EXPIRED"
                run.message = "Execution authority or worker lease expired. Review before submitting again."
                self._write(db, run, "run.interrupted")
            running = db.execute(
                "SELECT count(*) FROM t2d_runs WHERE status IN ('RUNNING','CANCELLATION_REQUESTED')"
            ).fetchone()[0]  # type: ignore[index]
            if running >= self.settings.maximum_running:
                return None
            row = db.execute(
                "SELECT q.payload,q.grant_payload FROM t2d_runs q WHERE q.status='QUEUED' AND q.binding=%s "
                "AND (SELECT count(*) FROM t2d_runs r WHERE r.tenant=q.tenant AND r.status IN "
                "('RUNNING','CANCELLATION_REQUESTED'))<%s ORDER BY q.created_at,q.id "
                "LIMIT 1 FOR UPDATE SKIP LOCKED",
                (binding, self.settings.maximum_running_per_tenant),
            ).fetchone()
            if row is None:
                return None
            run, grant = RunSnapshot.model_validate_json(row[0]), ExecutionGrant.model_validate_json(row[1])
            fence = uuid4()
            db.execute(
                "UPDATE t2d_runs SET fence=%s,lease_until=clock_timestamp()+%s*interval '1 second' "
                "WHERE id=%s",
                (fence, self.settings.lease_seconds, run.run_id),
            )
            run.status, run.message = "RUNNING", "Processing the governed question."
            self._write(db, run, "run.started")
            return ClaimedRun(run, grant, fence)

    def _owned(self, db: DB, job: ClaimedRun) -> RunSnapshot:
        row = db.execute(
            "SELECT payload,lease_until>clock_timestamp() FROM t2d_runs WHERE id=%s AND fence=%s FOR UPDATE",
            (job.run.run_id, job.fence),
        ).fetchone()
        if row is None or not row[1]:
            raise LeaseLost()
        run = RunSnapshot.model_validate_json(row[0])
        if run.status not in {"RUNNING", "CANCELLATION_REQUESTED"}:
            raise LeaseLost()
        return run

    def heartbeat(self, job: ClaimedRun) -> bool:
        with self.database.transaction() as db:
            run = self._owned(db, job)
            if run.status == "CANCELLATION_REQUESTED":
                return False
            valid = db.execute(
                "UPDATE t2d_runs SET lease_until=clock_timestamp()+%s*interval '1 second' "
                "WHERE id=%s AND expires_at>clock_timestamp()",
                (self.settings.lease_seconds, run.run_id),
            ).rowcount
            return valid == 1

    def progress(self, job: ClaimedRun, report: AgentRunReport) -> None:
        with self.database.transaction() as db:
            run = self._owned(db, job)
            if run.status == "CANCELLATION_REQUESTED":
                return
            if run.sequence >= 60:
                raise RunError("Progress event budget was reached.")
            run.progress = report.model_copy(deep=True)
            self._write(db, run, "agent.progress")

    def finish(
        self,
        job: ClaimedRun,
        status: RunStatus,
        *,
        result: DemoChatResponse | None = None,
        code: str | None = None,
        message: str = "Run finished.",
    ) -> RunSnapshot:
        if status not in TERMINAL:
            raise RunError("A terminal run state is required.")
        with self.database.transaction() as db:
            run = self._owned(db, job)
            if run.status == "CANCELLATION_REQUESTED":
                status, result, code, message = (
                    "CANCELLED",
                    None,
                    None,
                    "Cancellation confirmed; no answer released.",
                )
            elif not db.execute(
                "SELECT expires_at>clock_timestamp() FROM t2d_runs WHERE id=%s", (run.run_id,)
            ).fetchone()[0]:  # type: ignore[index]
                status, result, code, message = (
                    "INTERRUPTED",
                    None,
                    "AUTHORITY_EXPIRED",
                    "Execution authority expired.",
                )
            run.status, run.result, run.error_code, run.message = status, result, code, message
            if result is not None:
                run.progress = result.agent_run
            self._write(db, run, "run." + status.lower())
            return run

    def close(self) -> None:
        self.database.close()
