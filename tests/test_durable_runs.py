from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from talk2data.domain.agents import AgentRunReport
from talk2data.domain.runs import RunError, RunRequest, principal
from talk2data.services.agent_runtime import AgentFailure
from talk2data.services.run_coordinator import RunCoordinator
from talk2data.services.run_store import RunStore
from tests.claude_support import actor


def request(store: RunStore, *, owner: str = "owner", scope: str = "scope") -> RunRequest:
    conversation = store.create_conversation(owner, scope)
    return RunRequest(
        client_request_id=uuid4(),
        conversation_id=conversation.conversation_id,
        expected_revision=0,
        question="What were mobile activations last month?",
        as_of=datetime(2026, 8, 1, tzinfo=UTC),
        source_fingerprint="a" * 64,
        definition_snapshot_id="b" * 64,
    )


@pytest.fixture
def store() -> Any:
    value = RunStore()
    yield value
    value.close()


def test_principal_separates_profile_identity_and_scope() -> None:
    context = actor(regions={"WEST", "NORTHEAST"}, roles={"VIEWER", "BI_MANAGER"})
    owner, scope = principal("csv", context)
    assert principal("csv", actor(regions={"NORTHEAST", "WEST"}, roles={"BI_MANAGER", "VIEWER"})) == (
        owner,
        scope,
    )
    assert principal("internal", context)[0] != owner
    assert principal("csv", context.model_copy(update={"user_id": "other"}))[0] != owner
    changed = principal("csv", context.model_copy(update={"regions": {"WEST"}}))
    assert changed[0] == owner and changed[1] != scope


def test_transactional_journal_idempotency_and_replay(store: RunStore) -> None:
    payload = request(store)
    assert store.existing("owner", "scope", payload) is None
    run = store.enqueue("owner", "scope", payload, "a" * 64)
    assert store.existing("owner", "scope", payload) == run
    assert store.start(run.run_id) and not store.start(run.run_id)
    report = AgentRunReport()
    report.usage.reserved_tokens = 1024
    store.progress(run.run_id, report)
    final = store.finish(run.run_id, "FAILED", code="TEST_FAILURE", message="No answer.")
    assert store.finish(run.run_id, "COMPLETED") == final
    store.progress(run.run_id, report)
    events = store.events("owner", "scope", run.run_id, 0)
    assert [e.sequence for e in events] == [1, 2, 3, 4]
    assert [e.type for e in events] == ["run.accepted", "run.started", "agent.progress", "run.failed"]
    assert events[2].progress and events[2].progress.usage.reserved_tokens == 1024
    assert store.events("owner", "scope", run.run_id, 2) == events[2:]
    assert store.events("owner", "scope", run.run_id, 4) == []
    assert store.runs("owner", "scope", payload.conversation_id) == [final]
    assert store.conversations("owner", "scope")[0].revision == 1
    assert store.conversations("foreign", "scope") == []
    store.delete("owner", "scope", payload.conversation_id)
    assert store.conversations("owner", "scope") == []
    assert store._db.execute("SELECT count(*) FROM run_events").fetchone()[0] == 0


@pytest.mark.parametrize("owner,scope", [("foreign", "scope"), ("owner", "changed")])
def test_every_saved_object_is_bound_to_identity_and_scope(store: RunStore, owner: str, scope: str) -> None:
    payload = request(store)
    run = store.enqueue("owner", "scope", payload, "source")
    operations = [
        lambda: store.read(owner, scope, run.run_id),
        lambda: store.events(owner, scope, run.run_id, 0),
        lambda: store.cancel(owner, scope, run.run_id),
        lambda: store.delete(owner, scope, payload.conversation_id),
        lambda: store.runs(owner, scope, payload.conversation_id),
        lambda: store.existing(owner, scope, payload),
    ]
    for operation in operations:
        with pytest.raises(RunError) as error:
            operation()
        assert error.value.status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"question": "A different question"},
        {"expected_revision": 1},
        {"source_fingerprint": "c" * 64},
        {"definition_snapshot_id": "d" * 64},
    ],
)
def test_request_id_cannot_be_rebound(store: RunStore, change: Any) -> None:
    payload = request(store)
    store.enqueue("owner", "scope", payload, "source")
    with pytest.raises(RunError, match="request ID"):
        store.existing("owner", "scope", payload.model_copy(update=change))


def test_revision_active_run_and_cursor_conflicts(store: RunStore) -> None:
    payload = request(store)
    run = store.enqueue("owner", "scope", payload, "source")
    with pytest.raises(RunError, match="Conversation changed"):
        store.enqueue("owner", "scope", payload.model_copy(update={"client_request_id": uuid4()}), "source")
    next_request = payload.model_copy(update={"client_request_id": uuid4(), "expected_revision": 1})
    with pytest.raises(RunError, match="active question"):
        store.enqueue("owner", "scope", next_request, "source")
    with pytest.raises(RunError, match="Cancel the active"):
        store.delete("owner", "scope", payload.conversation_id)
    for cursor in [-1, 100]:
        with pytest.raises(RunError, match="cursor"):
            store.events("owner", "scope", run.run_id, cursor)
    with pytest.raises(RunError, match="terminal"):
        store.finish(run.run_id, "RUNNING")
    with pytest.raises(RunError, match="unavailable"):
        store.read("owner", "scope", uuid4())
    store.cancel("owner", "scope", run.run_id)
    assert store.cancel("owner", "scope", run.run_id).sequence == 2
    assert not store.start(run.run_id)
    assert store.finish(run.run_id, "COMPLETED").status == "CANCELLED"
    assert store.cancel("owner", "scope", run.run_id).status == "CANCELLED"


def test_queue_and_event_writes_rollback_together(store: RunStore, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = request(store)
    original = store._write

    def fail(*args: Any) -> None:
        original(*args)
        raise RuntimeError("Simulated disk failure before commit")

    monkeypatch.setattr(store, "_write", fail)
    with pytest.raises(RuntimeError):
        store.enqueue("owner", "scope", payload, "source")
    assert store.conversation("owner", "scope", payload.conversation_id).revision == 0
    assert store.existing("owner", "scope", payload) is None
    assert store._db.execute("SELECT count(*) FROM run_events").fetchone()[0] == 0
    monkeypatch.setattr(store, "_write", original)
    assert store.enqueue("owner", "scope", payload, "source").sequence == 1


def test_storage_and_event_budgets(store: RunStore) -> None:
    payload = request(store)
    for revision in range(64):
        current = payload.model_copy(update={"expected_revision": revision, "client_request_id": uuid4()})
        run = store.enqueue("owner", "scope", current, "source")
        store.finish(run.run_id, "FAILED")
    with pytest.raises(RunError, match="64-run"):
        store.enqueue("owner", "scope", payload.model_copy(update={"expected_revision": 64}), "source")
    for _ in range(15):
        store.create_conversation("owner", "scope")
    with pytest.raises(RunError, match="identity"):
        store.create_conversation("owner", "scope")
    for number in range(496):
        store.create_conversation(str(number), "scope")
    with pytest.raises(RunError, match="storage is full"):
        store.create_conversation("last", "scope")


def test_progress_cannot_grow_without_bound(store: RunStore) -> None:
    run = store.enqueue("owner", "scope", request(store), "source")
    store.start(run.run_id)
    for _ in range(58):
        store.progress(run.run_id, AgentRunReport())
    with pytest.raises(RunError, match="event budget"):
        store.progress(run.run_id, AgentRunReport())
    assert store.finish(run.run_id, "FAILED").sequence == 61


def test_restart_preserves_terminal_runs_and_interrupts_uncertain_work(tmp_path: Path) -> None:
    path = tmp_path / "runs.db"
    first = RunStore(path)
    payload = request(first)
    run = first.enqueue("owner", "scope", payload, "source")
    first.start(run.run_id)
    other = first.enqueue("owner", "scope", request(first), "source")
    first.cancel("owner", "scope", other.run_id)
    completed = first.enqueue("owner", "scope", request(first), "source")
    first.finish(completed.run_id, "COMPLETED")
    with pytest.raises(ValueError, match="already has"):
        RunStore(path)
    first.close()
    second = RunStore(path)
    for identifier in (run.run_id, other.run_id):
        restored = second.read("owner", "scope", identifier)
        assert restored.status == "INTERRUPTED" and restored.error_code == "WORKER_RESTARTED"
    assert second.read("owner", "scope", completed.run_id).status == "COMPLETED"
    assert second.existing("owner", "scope", payload).status == "INTERRUPTED"
    assert path.stat().st_mode & 0o777 == 0o600
    second.close()
    with pytest.raises(ValueError, match="absolute"):
        RunStore(Path("relative.db"))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE run_schema SET version=42")
    with pytest.raises(ValueError, match="migration"):
        RunStore(path)


async def allowed() -> None:
    pass


@pytest.mark.parametrize("queued", [True, False])
async def test_cancellation_never_releases_a_late_answer(store: RunStore, queued: bool) -> None:
    coordinator = RunCoordinator(store)
    entered = asyncio.Event()
    released = []

    async def operation(observer: Any) -> Any:
        entered.set()
        await asyncio.Event().wait()

    run = coordinator.submit(
        "owner", "scope", request(store), "source", operation, allowed, released=lambda: released.append(True)
    )
    if not queued:
        await entered.wait()
    coordinator.cancel("owner", "scope", run.run_id)
    await asyncio.gather(*list(coordinator.tasks.values()))
    assert entered.is_set() is (not queued)
    assert released == [True]
    assert store.read("owner", "scope", run.run_id).status == "CANCELLED"
    assert coordinator.cancel("owner", "scope", run.run_id).status == "CANCELLED"
    await coordinator.close()


@pytest.mark.parametrize(
    "failure",
    [
        AgentFailure("PROVIDER_TIMEOUT", "Provider timed out."),
        RuntimeError("private database password"),
    ],
)
async def test_worker_failures_are_terminal_and_sanitized(store: RunStore, failure: Exception) -> None:
    coordinator = RunCoordinator(store)

    async def operation(observer: Any) -> Any:
        raise failure

    run = coordinator.submit("owner", "scope", request(store), "source", operation, allowed)
    await asyncio.gather(*list(coordinator.tasks.values()))
    result = store.read("owner", "scope", run.run_id)
    assert result.status == "FAILED" and result.result is None
    assert "password" not in result.model_dump_json()
    await coordinator.close()


async def test_duplicate_submission_does_not_consume_worker_capacity(store: RunStore) -> None:
    coordinator = RunCoordinator(store, maximum_active=1)
    payload = request(store)

    async def operation(observer: Any) -> Any:
        await asyncio.Event().wait()

    run = coordinator.submit("owner", "scope", payload, "source", operation, allowed)
    assert coordinator.submit("owner", "scope", payload, "source", operation, allowed) == run
    next_request = request(store)
    with pytest.raises(RunError, match="capacity"):
        coordinator.submit("owner", "scope", next_request, "source", operation, allowed)
    assert store.existing("owner", "scope", next_request) is None
    await coordinator.close()
    assert store.read("owner", "scope", run.run_id).status == "INTERRUPTED"
    assert not coordinator.tasks and not coordinator.cleanup
