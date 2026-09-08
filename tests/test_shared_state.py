"""Actual PostgreSQL transactions/concurrency. CI supplies an isolated disposable database."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from talk2data.core.state_config import SharedStateSettings
from talk2data.domain.agents import AgentRunReport
from talk2data.domain.chat import DemoChatResponse
from talk2data.domain.execution import ExecutionGrant
from talk2data.domain.governance import GovernanceState
from talk2data.domain.models import QuestionDecision
from talk2data.domain.runs import RunError, RunRequest, now, principal
from talk2data.internal.bootstrap import create_internal_app
from talk2data.operations.shared_state import main
from talk2data.services.definition_store import DefinitionConflict, DefinitionUnavailable
from talk2data.services.distributed_runs import DistributedCoordinator, DistributedWorker
from talk2data.services.identity import EntitlementFile, IdentityRejected, IdentityUnavailable
from talk2data.services.postgres_database import PostgresDatabase
from talk2data.services.postgres_governance import PostgresDefinitionStore, PostgresEntitlementStore
from talk2data.services.postgres_runs import ClaimedRun, LeaseLost, PostgresRunStore
from talk2data.services.secrets import EnvironmentSecretResolver
from tests.internal_support import RecordingCloud, access, private_config
from tests.test_internal_identity import signed_token


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Any:
    if os.environ.get("T2D_RUN_STATE_TESTS") != "1":
        pytest.skip("Requires the explicitly enabled disposable PostgreSQL acceptance database.")
    dsn = os.environ["T2D_TEST_STATE_DSN"]
    monkeypatch.setenv("T2D_TEST_SHARED_DSN", dsn)
    value = PostgresDatabase(
        SharedStateSettings(
            dsn_secret_ref="env://T2D_TEST_SHARED_DSN", allow_insecure_loopback=True, heartbeat_seconds=0.1
        )
    )
    value.migrate()
    with value.transaction() as db:
        db.execute("TRUNCATE t2d_conversations,t2d_grants,t2d_grant_audit,t2d_definitions CASCADE")
    yield value
    value.close()


def request(store: PostgresRunStore, actor: Any = None) -> tuple[str, str, RunRequest, ExecutionGrant]:
    actor = actor or access()
    owner, scope = principal("internal", actor)
    conversation = store.create_conversation(owner, scope)
    payload = RunRequest(
        client_request_id=uuid4(),
        conversation_id=conversation.conversation_id,
        expected_revision=0,
        question="What were mobile activations last month?",
        as_of=now(),
        definition_snapshot_id="a" * 64,
    )
    return owner, scope, payload, ExecutionGrant(access=actor, expires_at=now() + timedelta(minutes=5))


def submit(store: PostgresRunStore, actor: Any = None) -> tuple[Any, ...]:
    owner, scope, payload, grant = request(store, actor)
    run = store.enqueue(owner, scope, payload, "binding", grant)
    return owner, scope, run


def claimed(store: PostgresRunStore) -> ClaimedRun:
    job = store.claim("binding")
    assert job is not None
    return job


def expire(database: PostgresDatabase, identifier: Any, field: str = "lease_until") -> None:
    from psycopg.sql import SQL, Identifier

    with database.transaction() as db:
        db.execute(
            SQL("UPDATE t2d_runs SET {}=clock_timestamp()-interval '1 second' WHERE id=%s").format(
                Identifier(field)
            ),
            (identifier,),
        )


def test_shared_journal_replay_and_restart(database: PostgresDatabase) -> None:
    first = PostgresRunStore(database)
    other_db = PostgresDatabase(database.settings)
    other = PostgresRunStore(other_db)
    owner, scope, payload, grant = request(first)
    assert first.existing(owner, scope, payload) is None
    run = first.enqueue(owner, scope, payload, "binding", grant)
    assert other.enqueue(owner, scope, payload, "binding", grant) == run
    assert other.existing(owner, scope, payload) == run
    job = claimed(other)
    assert first.claim("binding") is None
    assert first.heartbeat(job)
    other.progress(job, AgentRunReport())
    done = first.finish(job, "FAILED", code="EXPECTED")
    assert done.sequence == 4
    assert other.read(owner, scope, run.run_id) == done
    assert other.runs(owner, scope, payload.conversation_id) == [done]
    assert other.conversation(owner, scope, payload.conversation_id).revision == 1
    assert len(other.events(owner, scope, run.run_id, 0)) == 4
    assert not other.events(owner, scope, run.run_id, 4)
    assert other.conversations(owner, scope)[0].latest_run_id == run.run_id
    for cursor in (-1, 5):
        with pytest.raises(RunError):
            other.events(owner, scope, run.run_id, cursor)
    for action in (
        lambda: first.heartbeat(job),
        lambda: first.progress(job, AgentRunReport()),
        lambda: first.finish(job, "COMPLETED"),
    ):
        with pytest.raises(LeaseLost):
            action()
    assert other.cancel(owner, scope, run.run_id) == done
    other.delete(owner, scope, payload.conversation_id)
    assert not first.conversations(owner, scope)
    with pytest.raises(RunError):
        first.read(owner, scope, run.run_id)
    other.close()


@pytest.mark.parametrize("changed", ["owner", "scope"])
def test_shared_isolation(database: PostgresDatabase, changed: str) -> None:
    store = PostgresRunStore(database)
    owner, scope, payload, grant = request(store)
    run = store.enqueue(owner, scope, payload, "binding", grant)
    wrong = ("other", scope) if changed == "owner" else (owner, "other")
    for action in (
        lambda: store.read(*wrong, run.run_id),
        lambda: store.cancel(*wrong, run.run_id),
        lambda: store.runs(*wrong, payload.conversation_id),
        lambda: store.delete(*wrong, payload.conversation_id),
        lambda: store.existing(*wrong, payload),
    ):
        with pytest.raises(RunError) as failure:
            action()
        assert failure.value.status_code == 404
    with pytest.raises(RunError):
        store.enqueue(*wrong, payload, "binding", grant)


def test_atomic_idempotency_between_instances(database: PostgresDatabase) -> None:
    store = PostgresRunStore(database)
    owner, scope, payload, grant = request(store)
    second_db = PostgresDatabase(database.settings)
    second = PostgresRunStore(second_db)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(s.enqueue, owner, scope, payload, "binding", grant) for s in [store, second]]
        results = [f.result() for f in futures]
    assert results[0].run_id == results[1].run_id
    assert len(store.events(owner, scope, results[0].run_id, 0)) == 1
    with ThreadPoolExecutor(2) as pool:
        jobs = list(pool.map(lambda s: s.claim("binding"), [store, second]))
    assert sum(j is not None for j in jobs) == 1
    second.close()


def test_admission_limits_and_request_conflicts(database: PostgresDatabase) -> None:
    store = PostgresRunStore(database)
    owner, scope, payload, grant = request(store)
    with pytest.raises(RunError):
        store.enqueue(
            owner, scope, payload.model_copy(update={"source_fingerprint": "b" * 64}), "binding", grant
        )
    with pytest.raises(RunError):
        store.enqueue(
            owner,
            scope,
            payload,
            "binding",
            grant.model_copy(update={"expires_at": now() - timedelta(seconds=1)}),
        )
    with pytest.raises(RunError):
        store.enqueue(owner, scope, payload.model_copy(update={"expected_revision": 1}), "binding", grant)
    run = store.enqueue(owner, scope, payload, "binding", grant)
    with pytest.raises(RunError):
        store.existing(owner, scope, payload.model_copy(update={"question": "A different question"}))
    with pytest.raises(RunError):
        store.enqueue(
            owner,
            scope,
            payload.model_copy(update={"client_request_id": uuid4(), "expected_revision": 1}),
            "binding",
            grant,
        )
    with pytest.raises(RunError):
        store.delete(owner, scope, payload.conversation_id)
    second = request(store)
    store.settings = store.settings.model_copy(update={"maximum_pending": 1})
    with pytest.raises(RunError):
        store.enqueue(*second[:3], "binding", second[3])
    assert store.cancel(owner, scope, run.run_id).status == "CANCELLED"
    assert store.claim("binding") is None
    store.settings = store.settings.model_copy(update={"maximum_conversations": 2})
    with pytest.raises(RunError):
        store.create_conversation("another", "scope")


def test_cancel_wins_over_completion_and_late_progress(database: PostgresDatabase) -> None:
    store = PostgresRunStore(database)
    owner, scope, run = submit(store)
    job = claimed(store)
    assert store.cancel(owner, scope, run.run_id).status == "CANCELLATION_REQUESTED"
    assert store.cancel(owner, scope, run.run_id).sequence == 3
    assert not store.heartbeat(job)
    store.progress(job, AgentRunReport())
    done = store.finish(job, "COMPLETED")
    assert done.status == "CANCELLED" and done.result is None


def test_expired_leases_cannot_publish_or_redispatch(database: PostgresDatabase) -> None:
    store = PostgresRunStore(database)
    owner, scope, run = submit(store)
    job = claimed(store)
    with pytest.raises(LeaseLost):
        store.heartbeat(replace(job, fence=uuid4()))
    expire(database, run.run_id)
    with pytest.raises(LeaseLost):
        store.finish(job, "COMPLETED")
    assert store.claim("binding") is None
    assert store.read(owner, scope, run.run_id).status == "INTERRUPTED"
    owner, scope, queued = submit(store)
    expire(database, queued.run_id, "expires_at")
    assert store.claim("binding") is None
    assert store.read(owner, scope, queued.run_id).status == "INTERRUPTED"
    owner, scope, running = submit(store)
    job = claimed(store)
    with pytest.raises(RunError):
        store.finish(job, "RUNNING")
    expire(database, running.run_id, "expires_at")
    assert not store.heartbeat(job)
    assert store.finish(job, "COMPLETED").status == "INTERRUPTED"


def test_capacity_is_shared_and_skips_unrelated_tenants(database: PostgresDatabase) -> None:
    store = PostgresRunStore(database)
    store.settings = store.settings.model_copy(update={"maximum_running": 2, "maximum_running_per_tenant": 1})
    submit(store)
    submit(store)
    submit(store, access("different", "another-tenant"))
    assert store.claim("wrong-binding") is None
    first, second = claimed(store), claimed(store)
    assert first.grant.access.tenant_id != second.grant.access.tenant_id
    assert store.claim("binding") is None
    store.finish(first, "FAILED")
    assert store.claim("binding") is not None


def test_event_failure_rolls_back_admission(database: PostgresDatabase) -> None:
    store = PostgresRunStore(database)
    owner, scope, payload, grant = request(store)
    with database.transaction() as db:
        db.execute("ALTER TABLE t2d_events ADD CONSTRAINT reject_event CHECK (sequence<0)")
    try:
        with pytest.raises(RunError):
            store.enqueue(owner, scope, payload, "binding", grant)
        assert store.existing(owner, scope, payload) is None
        assert store.conversation(owner, scope, payload.conversation_id).revision == 0
    finally:
        with database.transaction() as db:
            db.execute("ALTER TABLE t2d_events DROP CONSTRAINT reject_event")


def test_definitions_and_authorization_are_shared(database: PostgresDatabase, tmp_path: Path) -> None:
    config = private_config(tmp_path)
    cloud = RecordingCloud()
    config = config.model_copy(update={"shared_state": database.settings})
    app = create_internal_app(config, transport_factory=lambda _: cloud)
    governance = app.state.runtime.definitions["demo-telecom"]
    first = PostgresDefinitionStore(database)
    state = first.read("internal:demo-telecom")
    first.seed("internal:demo-telecom", state)
    assert first.read("internal:demo-telecom") == state
    first.save("internal:demo-telecom", state, 0)
    with pytest.raises(DefinitionConflict):
        first.save("internal:demo-telecom", state, 0)
    assert governance._state().revision == 1
    for raw in ("bad", GovernanceState(tenant_id="demo-telecom", snapshots=[]).model_dump_json()):
        with database.transaction() as db:
            db.execute("UPDATE t2d_definitions SET payload=%s", (raw,))
        with pytest.raises(DefinitionUnavailable):
            first.read("internal:demo-telecom")
    first.delete("internal:demo-telecom")
    with pytest.raises(DefinitionUnavailable):
        first.read("internal:demo-telecom")
    first.close()
    grants = EntitlementFile.model_validate_json(config.entitlements_path.read_bytes())
    auth = PostgresEntitlementStore(database, config.identity.issuer)
    with pytest.raises(IdentityUnavailable):
        auth.resolve("analyst")
    with pytest.raises(IdentityUnavailable):
        auth.publish(grants.model_copy(update={"issuer": "wrong"}), 0)
    assert auth.publish(grants, 0) == 1
    assert auth.resolve("analyst") == access()
    with pytest.raises(DefinitionConflict):
        auth.publish(grants, 0)
    auth.publish(grants.model_copy(update={"bindings": []}), 1)
    with pytest.raises(IdentityRejected):
        auth.resolve("analyst")
    with database.transaction() as db:
        db.execute("UPDATE t2d_grants SET payload='bad'")
    with pytest.raises(IdentityUnavailable):
        auth.resolve("analyst")


async def drain(worker: DistributedWorker) -> None:
    for _ in range(200):
        if not worker.tasks:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Worker did not drain")


async def test_worker_executes_once_replays_and_cancels_across_instances(database: PostgresDatabase) -> None:
    store = PostgresRunStore(database)
    calls = []
    gate = asyncio.Event()

    async def authorize(_: ClaimedRun) -> None:
        pass

    async def operation(job: ClaimedRun, observer: Any) -> DemoChatResponse:
        calls.append(job.run.run_id)
        observer(AgentRunReport())
        await gate.wait()
        return DemoChatResponse(
            status="OUT_OF_DOMAIN",
            message="No answer",
            session_id=uuid4(),
            decision=QuestionDecision(
                tenant_id="demo-telecom",
                user_id="analyst",
                verdict="OUT_OF_DOMAIN",
                recognized_intent="UNKNOWN",
                authorization_status="ALLOWED",
                data_status="NOT_REQUIRED",
                user_message="No answer",
                next_action="Ask a business question",
                domain_pack_version="1",
                interpreter_mode="RULES",
            ),
        )

    worker = DistributedWorker(store, "binding", operation, authorize)
    owner, scope, run = submit(store)
    await worker.tick()
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.01)
    assert calls == [run.run_id]
    store.cancel(owner, scope, run.run_id)
    await drain(worker)
    assert store.read(owner, scope, run.run_id).status == "CANCELLED"
    gate.set()
    owner, scope, run = submit(store)
    await worker.tick()
    await drain(worker)
    assert store.read(owner, scope, run.run_id).result is not None
    await worker.close()


async def test_worker_failures_stop_cleanly_and_never_release(database: PostgresDatabase) -> None:
    store = PostgresRunStore(database)

    async def reject(_: ClaimedRun) -> None:
        raise IdentityRejected("Revoked")

    async def unused(job: ClaimedRun, observer: Any) -> DemoChatResponse:
        raise AssertionError("Must not dispatch")

    worker = DistributedWorker(store, "binding", unused, reject)
    owner, scope, run = submit(store)
    await worker.tick()
    await drain(worker)
    assert store.read(owner, scope, run.run_id).status == "FAILED"
    await worker.close()
    coordinator = DistributedCoordinator(store)
    owner, scope, payload, grant = request(store)
    run = coordinator.submit(owner, scope, payload, "binding", grant)
    assert coordinator.cancel(owner, scope, run.run_id).status == "CANCELLED"
    await coordinator.close()
    with pytest.raises(RunError):
        coordinator.submit(owner, scope, payload, "binding", grant)


def test_shared_api_and_worker_use_signed_authority(
    database: PostgresDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    config = private_config(tmp_path).model_copy(update={"shared_state": database.settings})
    grants = EntitlementFile.model_validate_json(config.entitlements_path.read_bytes())
    auth = PostgresEntitlementStore(database, config.identity.issuer)
    auth.publish(grants, 0)
    app = create_internal_app(config, transport_factory=lambda _: RecordingCloud())
    worker_app = create_internal_app(
        config.model_copy(update={"process_role": "worker"}), transport_factory=lambda _: RecordingCloud()
    )
    monkeypatch.setattr(
        app.state.verifier.keys, "get_signing_key_from_jwt", lambda _: SimpleNamespace(key=key.public_key())
    )
    headers = {"Authorization": "Bearer " + signed_token(key)}
    with TestClient(app) as client, TestClient(worker_app) as worker_client:
        assert worker_client.get("/health/live").status_code == 200
        assert worker_client.get("/v1/internal/me", headers=headers).status_code == 404
        conversation = client.post("/v1/internal/conversations", headers=headers).json()
        snapshot = client.get("/v1/internal/definitions", headers=headers).json()["snapshot_id"]
        payload = RunRequest(
            client_request_id=uuid4(),
            conversation_id=conversation["conversation_id"],
            expected_revision=0,
            question="What were mobile activations last month?",
            as_of="2026-08-01T12:00:00Z",
            definition_snapshot_id=snapshot,
        ).model_dump(mode="json")
        response = client.post("/v1/internal/runs", headers=headers, json=payload)
        assert response.status_code == 202, response.text
        identifier = response.json()["run_id"]
        assert client.post("/v1/internal/runs", headers=headers, json=payload).json()["run_id"] == identifier
        assert (
            client.post(
                "/v1/internal/chat", headers=headers, json={"question": "mobile activations"}
            ).status_code
            == 409
        )
        import time

        for _ in range(200):
            result = client.get(f"/v1/internal/runs/{identifier}", headers=headers).json()
            if result["status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(0.01)
        assert result["status"] == "COMPLETED", result
        assert result["result"]["receipt"]["row_count"] == 1
        assert client.get("/health/ready", headers=headers).status_code == 200
        assert worker_client.get("/health/ready").status_code == 200
        auth.publish(grants.model_copy(update={"bindings": []}), 1)
        assert client.get(f"/v1/internal/runs/{identifier}", headers=headers).status_code == 401


def test_migration_and_authorization_cli(database: PostgresDatabase, tmp_path: Path, capsys: Any) -> None:
    config = private_config(tmp_path).model_copy(update={"shared_state": database.settings})
    path = tmp_path / "runtime.json"
    path.write_text(config.model_dump_json())
    assert main(["migrate", "--config", str(path)]) == 0
    assert main(["check", "--config", str(path)]) == 0
    assert main(["publish-grants", "--config", str(path)]) == 1
    assert main(["publish-grants", "--config", str(path), "--expected-revision", "0"]) == 0
    assert main(["publish-grants", "--config", str(path), "--expected-revision", "0"]) == 1
    assert "analyst" not in capsys.readouterr().out


def test_shared_configuration_and_safe_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SharedStateSettings(dsn_secret_ref="env://T2D_TEST_SHARED_DSN")
    for dsn in ["not a dsn", "postgresql://user:secret@remote.example/db?sslmode=disable"]:
        with pytest.raises(ValueError):
            PostgresDatabase(settings, EnvironmentSecretResolver({"T2D_TEST_SHARED_DSN": dsn}))
    valid = PostgresDatabase(
        settings,
        EnvironmentSecretResolver(
            {"T2D_TEST_SHARED_DSN": "postgresql://user:secret@private.example/db?sslmode=verify-full"}
        ),
    )

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise psycopg.OperationalError("secret hostname")

    monkeypatch.setattr(psycopg, "connect", broken)
    with pytest.raises(RunError, match="temporarily unavailable") as failure:
        valid.check()
    assert "secret" not in str(failure.value)
    valid.close()
    for update in [{"heartbeat_seconds": 10}, {"maximum_running": 1}, {"dsn_secret_ref": "literal-secret"}]:
        with pytest.raises(ValidationError):
            SharedStateSettings.model_validate({**settings.model_dump(), **update})
    config = private_config(tmp_path)
    for update in [
        {"process_role": "worker"},
        {"shared_state": settings, "state_database_path": "/tmp/state"},
        {"web_directory": "/app/web"},
    ]:
        with pytest.raises(ValidationError):
            type(config).model_validate({**config.model_dump(), **update})
    path = tmp_path / "config.json"
    path.write_text(config.model_dump_json())
    assert main(["check", "--config", str(path)]) == 1
