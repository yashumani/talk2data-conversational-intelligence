from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.governance import DefinitionEdit, DraftStatus
from talk2data.domain.models import AccessContext, ClassificationLevel
from talk2data.services.definition_governance import (
    EDIT,
    PUBLISH,
    REVIEW,
    REVOKE,
    DefinitionDenied,
    DefinitionGovernance,
    DefinitionNotFound,
)
from talk2data.services.definition_store import DefinitionConflict, DefinitionStore, DefinitionUnavailable
from talk2data.services.semantic import SemanticRegistry
from tests.internal_support import access


def steward(subject: str = "author", **updates: Any) -> AccessContext:
    return access(subject).model_copy(
        update={
            "classification_clearance": ClassificationLevel.RESTRICTED,
            "permitted_actions": {
                "READ_AGGREGATED_DATA",
                "ASK_BUSINESS_QUESTIONS",
                EDIT,
                REVIEW,
                PUBLISH,
                REVOKE,
            },
            **updates,
        }
    )


@pytest.fixture
def governed() -> Any:
    registry = DomainPackRegistry()
    registry.load()
    store = DefinitionStore()
    now = [datetime(2099, 9, 7, tzinfo=UTC)]
    service = DefinitionGovernance(store, "test", registry.get("demo-telecom"), clock=lambda: now[0])
    yield service, store, now
    store.close()


def change(service: DefinitionGovernance, **updates: Any) -> DefinitionEdit:
    snapshot = service.inspect_current(steward())
    return DefinitionEdit.model_validate(
        {
            "base_snapshot_id": snapshot.snapshot_id,
            "kind": "METRIC",
            "definition_id": "MOBILE_ACTIVATIONS",
            "name": "Mobile Activations",
            "definition": "Completed new activation events, excluding failed attempts.",
            "owner": "Demo Sales Analytics",
            "aliases": ["activations", "activation count"],
            "reason": "Clarify the approved business meaning.",
            "effective_from": service.clock(),
            **updates,
        }
    )


def reviewed(service: DefinitionGovernance, **updates: Any) -> Any:
    draft = service.create_draft(steward(), change(service, **updates))
    draft = service.transition(steward(), draft.draft_id, "submit", draft.revision, "Ready for review")
    return service.transition(
        steward("reviewer"),
        draft.draft_id,
        "approve",
        draft.revision,
        "Reviewed against the business definition",
    )


def published(service: DefinitionGovernance, **updates: Any) -> Any:
    draft = reviewed(service, **updates)
    return service.transition(
        steward(), draft.draft_id, "publish", draft.revision, "Release approved definition"
    )


def test_approval_then_atomic_publication_pins_immutable_versions(governed: Any) -> None:
    service, _, _ = governed
    before = service.resolve(steward())
    draft = reviewed(service)
    assert service.resolve(steward()).snapshot_id == before.snapshot_id
    result = service.transition(steward(), draft.draft_id, "publish", draft.revision, "Publish now")
    after = service.resolve(steward())
    assert result.status == DraftStatus.PUBLISHED and result.published_snapshot_id == after.snapshot_id
    assert before.snapshot_id != after.snapshot_id
    metric = next(m for m in after.pack.metrics if m.id == "MOBILE_ACTIVATIONS")
    old = next(m for m in before.pack.metrics if m.id == metric.id)
    assert metric.definition_version == old.definition_version + 1
    assert metric.semantic_version == old.semantic_version and metric.aggregation == old.aggregation
    assert service.resolve(steward(), before.snapshot_id).pack == before.pack
    events = service.view(steward())["events"]
    assert [(e["kind"], e["sequence"]) for e in events] == [("PUBLISHED", 1)]
    assert service.view(steward())["mode"] == "SEPARATE_REVIEWER"
    metric.definition = "Mutating a caller copy"
    assert "Mutating" not in str(service.resolve(steward()).pack)


def test_dimension_changes_invalidate_semantic_hash_and_keep_values(governed: Any) -> None:
    service, _, _ = governed
    before = service.resolve(steward()).pack
    published(
        service,
        kind="DIMENSION",
        definition_id="REGION",
        name="Operating Region",
        definition="The reporting geography assigned to the observation.",
        aliases=["region", "regions"],
    )
    after = service.resolve(steward()).pack
    original = next(d for d in before.entities if d.id == "REGION")
    updated = next(d for d in after.entities if d.id == "REGION")
    assert updated.definition_version == 2 and original.values == updated.values
    before_metric = next(m for m in before.metrics if m.id == "MOBILE_ACTIVATIONS")
    after_metric = next(m for m in after.metrics if m.id == "MOBILE_ACTIVATIONS")
    after.version = before.version
    assert SemanticRegistry.semantic_snapshot_hash(
        before, before_metric
    ) != SemanticRegistry.semantic_snapshot_hash(after, after_metric)


@pytest.mark.parametrize("operation", ["read", "edit", "submit", "approve", "publish", "revoke"])
def test_missing_actions_wrong_tenant_and_clearance_cannot_manage(governed: Any, operation: str) -> None:
    service, _, _ = governed
    restricted = steward(permitted_actions=set())
    with pytest.raises(DefinitionDenied):
        if operation == "read":
            service.resolve(restricted)
        elif operation == "edit":
            service.create_draft(restricted, change(service))
        elif operation == "revoke":
            service.revoke(restricted, "unknown", 1, "No permission")
        else:
            service.transition(restricted, "unknown", operation, 1, "No permission")
    with pytest.raises(DefinitionDenied):
        service.resolve(steward(tenant_id="other"))
    with pytest.raises(DefinitionDenied, match="clearance"):
        service.create_draft(steward(classification_clearance=ClassificationLevel.INTERNAL), change(service))


def test_ordinary_readers_only_see_authorized_definitions(governed: Any) -> None:
    service, _, _ = governed
    published(service)
    reader = access().model_copy(update={"classification_clearance": ClassificationLevel.INTERNAL})
    view = service.view(reader)
    assert {m["id"] for m in view["metrics"]} == {"MOBILE_ACTIVATIONS"}
    assert "TECHNOLOGY" not in {d["id"] for d in view["dimensions"]}
    assert view["drafts"] == view["events"] == view["snapshots"] == view["actions"] == []


def test_separate_author_reviewer_and_rejection_are_enforced(governed: Any) -> None:
    service, _, _ = governed
    draft = service.create_draft(steward(), change(service))
    with pytest.raises(DefinitionDenied, match="author"):
        service.transition(steward("other"), draft.draft_id, "submit", 1, "Submit")
    draft = service.transition(steward(), draft.draft_id, "submit", 1, "Submit")
    with pytest.raises(DefinitionDenied, match="different"):
        service.transition(steward(), draft.draft_id, "approve", draft.revision, "Self approve")
    result = service.transition(
        steward("reviewer"),
        draft.draft_id,
        "reject",
        draft.revision,
        "Definition needs a clearer owner decision",
    )
    assert result.status == DraftStatus.REJECTED and result.review_note
    with pytest.raises(DefinitionConflict):
        service.transition(steward(), draft.draft_id, "publish", result.revision, "Publish rejected")


def test_demo_mode_is_explicit_and_never_fakes_a_second_person(governed: Any) -> None:
    service, _, _ = governed
    service.separate_reviewer = False
    draft = service.create_draft(steward(), change(service))
    draft = service.transition(steward(), draft.draft_id, "submit", 1, "Demo submit")
    draft = service.transition(steward(), draft.draft_id, "approve", draft.revision, "Demo approval only")
    assert draft.author == draft.reviewer == "author"
    assert service.view(steward())["mode"] == "DEMO_SINGLE_USER"


def test_stale_review_versions_and_publication_conflicts_are_atomic(governed: Any) -> None:
    service, store, _ = governed
    first = reviewed(service)
    second = reviewed(service, definition="A separately proposed definition.")
    with pytest.raises(DefinitionConflict, match="draft changed"):
        service.transition(steward(), first.draft_id, "publish", 1, "Stale")
    service.transition(steward(), first.draft_id, "publish", first.revision, "First publication")
    before = store.read("test").model_dump_json()
    with pytest.raises(DefinitionConflict, match="Another definition"):
        service.transition(steward(), second.draft_id, "publish", second.revision, "Stale base")
    assert store.read("test").model_dump_json() == before
    with pytest.raises(DefinitionConflict):
        service.create_draft(steward(), first.edit)
    with pytest.raises(DefinitionConflict, match="changed"):
        service.resolve(steward(), first.edit.base_snapshot_id, require_current=True)


def test_scheduled_publication_is_effective_only_at_its_boundary(governed: Any) -> None:
    service, _, now = governed
    old = service.resolve(steward()).snapshot_id
    draft = published(service, effective_from=now[0] + timedelta(hours=1))
    assert service.resolve(steward()).snapshot_id == old
    with pytest.raises(DefinitionUnavailable):
        service.resolve(steward(), draft.published_snapshot_id)
    now[0] += timedelta(hours=1)
    assert service.resolve(steward()).snapshot_id == draft.published_snapshot_id


def test_revoked_context_never_falls_back_and_can_be_replaced(governed: Any) -> None:
    service, _, _ = governed
    old = service.resolve(steward()).snapshot_id
    published(service)
    current = service.resolve(steward()).snapshot_id
    service.revoke(steward(), current, service.view(steward())["revision"], "Withdraw incorrect wording")
    assert service.view(steward())["status"] == "REVOKED"
    with pytest.raises(DefinitionUnavailable):
        service.resolve(steward())
    assert service.resolve(steward(), old).snapshot_id == old
    with pytest.raises(DefinitionConflict):
        service.revoke(steward(), current, service.view(steward())["revision"], "Repeated")
    published(service, definition="Corrected approved meaning.")
    assert service.view(steward())["status"] == "PUBLISHED"
    assert [e["sequence"] for e in service.view(steward())["events"]] == [1, 2, 3]


@pytest.mark.parametrize("kind", ["METRIC", "DIMENSION"])
def test_unknown_targets_and_alias_collisions_fail_without_side_effects(governed: Any, kind: str) -> None:
    service, store, _ = governed
    before = store.read("test").revision
    with pytest.raises(DefinitionNotFound):
        service.create_draft(steward(), change(service, kind=kind, definition_id="UNKNOWN"))
    with pytest.raises(DefinitionConflict, match="conflict"):
        service.create_draft(
            steward(),
            change(
                service,
                kind=kind,
                definition_id="REGION" if kind == "DIMENSION" else "MOBILE_ACTIVATIONS",
                aliases=["Sales Channel" if kind == "DIMENSION" else "Postpaid Churn"],
            ),
        )
    assert store.read("test").revision == before


def test_unknown_ids_and_wrong_transition_fail(governed: Any) -> None:
    service, _, _ = governed
    with pytest.raises(DefinitionNotFound):
        service.resolve(steward(), "a" * 64)
    with pytest.raises(DefinitionNotFound):
        service.transition(steward(), "unknown", "approve", 1, "Missing")
    with pytest.raises(DefinitionNotFound):
        service.revoke(steward(), "unknown", service.view(steward())["revision"], "Missing")
    draft = service.create_draft(steward(), change(service))
    with pytest.raises(DefinitionConflict):
        service.transition(steward(), draft.draft_id, "publish", 1, "Skip review")
    with pytest.raises(DefinitionConflict):
        service.revoke(steward(), draft.edit.base_snapshot_id, 999, "Stale")


@pytest.mark.parametrize(
    "updates",
    [
        {"owner": " "},
        {"definition": ""},
        {"aliases": ["same", "SAME"]},
        {"aliases": ["x"] * 21},
        {"kind": "SQL"},
        {"base_snapshot_id": "wrong"},
        {"tenant_id": "another"},
        {"aggregation": "AVERAGE"},
        {"classification": "PUBLIC"},
        {"definition": "x" * 4001},
        {"effective_from": "2099-09-07T00:00:00"},
    ],
)
def test_edit_schema_cannot_change_authority_or_calculation(governed: Any, updates: dict[str, Any]) -> None:
    service, _, _ = governed
    with pytest.raises(ValidationError):
        change(service, **updates)


def test_durable_store_preserves_history_and_rejects_conflicting_writers(tmp_path: Path) -> None:
    registry = DomainPackRegistry()
    registry.load()
    pack = registry.get("demo-telecom")
    path = tmp_path / "private" / "definitions.db"
    first = DefinitionStore(path)
    service = DefinitionGovernance(first, "internal:demo", pack)
    published(service)
    current = service.resolve(steward()).snapshot_id
    second = DefinitionStore(path)
    restarted = DefinitionGovernance(second, "internal:demo", pack)
    assert restarted.resolve(steward()).snapshot_id == current
    stale = second.read("internal:demo")
    service.create_draft(steward(), change(service))
    with pytest.raises(DefinitionConflict):
        second.save("internal:demo", stale, stale.revision)
    assert len(second.read("internal:demo").drafts) == 2
    with pytest.raises(DefinitionUnavailable, match="bootstrap"):
        DefinitionGovernance(first, "internal:demo", pack.model_copy(update={"version": "changed-bootstrap"}))
    first.close()
    second.close()


@pytest.mark.parametrize("corrupt", ["json", "hash", "revision", "empty"])
def test_corrupt_store_fails_closed(governed: Any, corrupt: str) -> None:
    service, store, _ = governed
    state = store.read("test")
    if corrupt == "hash":
        state.snapshots[0].pack.metrics[0].definition = "Tampered"
    elif corrupt == "revision":
        state.revision += 1
    elif corrupt == "empty":
        state.snapshots = []
    payload = "invalid" if corrupt == "json" else state.model_dump_json()
    store._db.execute("UPDATE definition_streams SET payload = ?", (payload,))
    store._db.commit()
    with pytest.raises(DefinitionUnavailable):
        service.resolve(steward())


def test_missing_store_and_future_initial_pack_are_unavailable(governed: Any) -> None:
    service, store, now = governed
    pack = service.resolve(steward()).pack
    with pytest.raises(DefinitionUnavailable):
        DefinitionGovernance(
            store,
            "future",
            pack.model_copy(update={"effective_from": now[0] + timedelta(days=1)}),
            clock=lambda: now[0],
        )
    now[0] = datetime(2000, 1, 1, tzinfo=UTC)
    with pytest.raises(DefinitionUnavailable):
        service.resolve(steward())
    store.delete("test")
    with pytest.raises(DefinitionUnavailable):
        store.read("test")


@pytest.mark.parametrize("limit", ["drafts", "snapshots"])
def test_bounded_review_history_rejects_capacity_without_dropping_records(governed: Any, limit: str) -> None:
    service, store, _ = governed
    draft = reviewed(service)
    state = store.read("test")
    if limit == "drafts":
        state.drafts = [draft] * 64
    else:
        state.snapshots = [state.snapshots[0]] * 64
    store.save("test", state, state.revision)
    with pytest.raises(DefinitionConflict, match="capacity"):
        if limit == "drafts":
            service.create_draft(steward(), change(service))
        else:
            service.transition(steward(), draft.draft_id, "publish", draft.revision, "At capacity")
