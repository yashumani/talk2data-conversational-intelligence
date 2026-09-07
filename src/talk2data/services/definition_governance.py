"""Server-authorized review and atomic publication of immutable business definitions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from talk2data.domain.governance import (
    DefinitionDraft,
    DefinitionEdit,
    DefinitionEvent,
    DefinitionSnapshot,
    DraftStatus,
    GovernanceState,
    pack_hash,
)
from talk2data.domain.models import CLASSIFICATION_RANK, AccessContext, TenantDomainPack
from talk2data.services.definition_store import DefinitionConflict, DefinitionStore, DefinitionUnavailable
from talk2data.services.policy import READ_DATA_ACTION

EDIT = "EDIT_DEFINITIONS"
REVIEW = "REVIEW_DEFINITIONS"
PUBLISH = "PUBLISH_DEFINITIONS"
REVOKE = "REVOKE_DEFINITIONS"


class DefinitionDenied(RuntimeError):
    pass


class DefinitionNotFound(RuntimeError):
    pass


class DefinitionGovernance:
    def __init__(
        self,
        store: DefinitionStore,
        namespace: str,
        pack: TenantDomainPack,
        *,
        separate_reviewer: bool = True,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store, self.namespace, self.tenant_id = store, namespace, pack.tenant_id
        self.separate_reviewer, self.clock = separate_reviewer, clock
        if pack.effective_from.tzinfo is None or pack.effective_from > clock():
            raise DefinitionUnavailable("Initial definitions must already be effective.")
        seed = DefinitionSnapshot(
            snapshot_id=pack_hash(pack),
            sequence=0,
            pack=pack,
            published_at=clock(),
            published_by="approved-bootstrap",
        )
        store.seed(namespace, GovernanceState(tenant_id=pack.tenant_id, snapshots=[seed]))
        state = self._state()
        if state.tenant_id != pack.tenant_id or state.snapshots[0].snapshot_id != pack_hash(pack):
            raise DefinitionUnavailable(
                "The definition bootstrap changed; an approved store migration is required."
            )

    def _state(self) -> GovernanceState:
        return self.store.read(self.namespace)

    def _authorize(self, access: AccessContext, action: str = READ_DATA_ACTION) -> None:
        if access.tenant_id != self.tenant_id or not {READ_DATA_ACTION, action} <= access.permitted_actions:
            raise DefinitionDenied("Definition access is not authorized.")

    def _manage(self, access: AccessContext, action: str, state: GovernanceState) -> None:
        self._authorize(access, action)
        pack = state.snapshots[-1].pack
        if any(
            CLASSIFICATION_RANK[level] > CLASSIFICATION_RANK[access.classification_clearance]
            for level in [
                *[m.classification for m in pack.metrics],
                *[d.classification for d in pack.entities],
            ]
        ):
            raise DefinitionDenied("Definition review requires clearance for the complete publication.")

    def _current(self, state: GovernanceState) -> DefinitionSnapshot:
        eligible = [snapshot for snapshot in state.snapshots if snapshot.pack.effective_from <= self.clock()]
        if not eligible:
            raise DefinitionUnavailable("No approved definitions are effective yet.")
        return max(eligible, key=lambda item: (item.pack.effective_from, item.sequence))

    def inspect_current(self, access: AccessContext) -> DefinitionSnapshot:
        self._authorize(access)
        return self._current(self._state())

    def resolve(
        self, access: AccessContext, snapshot_id: str | None = None, *, require_current: bool = False
    ) -> DefinitionSnapshot:
        self._authorize(access)
        state = self._state()
        current = self._current(state)
        snapshot = (
            current
            if snapshot_id is None
            else next((s for s in state.snapshots if s.snapshot_id == snapshot_id), None)
        )
        if snapshot is None:
            raise DefinitionNotFound("The definition snapshot is not available in this workspace.")
        if require_current and snapshot.snapshot_id != current.snapshot_id:
            raise DefinitionConflict("Business definitions changed. Refresh before asking again.")
        if snapshot.snapshot_id in state.revoked or snapshot.pack.effective_from > self.clock():
            raise DefinitionUnavailable("This definition snapshot is revoked or not yet effective.")
        return snapshot

    def view(self, access: AccessContext) -> dict[str, Any]:
        self._authorize(access)
        state = self._state()
        snapshot = self._current(state)
        clearance = CLASSIFICATION_RANK[access.classification_clearance]
        # Review records may contain the complete pack; expose them only to an authorized steward.
        managing = bool(access.permitted_actions & {EDIT, REVIEW, PUBLISH, REVOKE})
        if managing:
            self._manage(
                access, next(iter(access.permitted_actions & {EDIT, REVIEW, PUBLISH, REVOKE})), state
            )
        return {
            "revision": state.revision,
            "mode": "SEPARATE_REVIEWER" if self.separate_reviewer else "DEMO_SINGLE_USER",
            "snapshot_id": snapshot.snapshot_id,
            "version": snapshot.pack.version,
            "effective_from": snapshot.pack.effective_from.isoformat(),
            "status": "REVOKED" if snapshot.snapshot_id in state.revoked else "PUBLISHED",
            "metrics": [
                m.model_dump(mode="json")
                for m in snapshot.pack.metrics
                if CLASSIFICATION_RANK[m.classification] <= clearance
            ],
            "dimensions": [
                d.model_dump(mode="json")
                for d in snapshot.pack.entities
                if CLASSIFICATION_RANK[d.classification] <= clearance
            ],
            "drafts": [d.model_dump(mode="json") for d in state.drafts] if managing else [],
            "events": [event.model_dump(mode="json") for event in state.events] if managing else [],
            "snapshots": [
                {
                    "snapshot_id": s.snapshot_id,
                    "version": s.pack.version,
                    "effective_from": s.pack.effective_from.isoformat(),
                    "revoked": s.snapshot_id in state.revoked,
                }
                for s in state.snapshots
            ]
            if managing
            else [],
            "actions": sorted(access.permitted_actions & {EDIT, REVIEW, PUBLISH, REVOKE}),
        }

    @staticmethod
    def _apply(pack: TenantDomainPack, edit: DefinitionEdit) -> TenantDomainPack:
        candidate = pack.model_copy(deep=True)
        definitions = candidate.metrics if edit.kind == "METRIC" else candidate.entities
        target = next((item for item in definitions if item.id == edit.definition_id), None)
        if target is None:
            raise DefinitionNotFound("The metric or dimension is not registered.")
        requested = {word.casefold() for word in [edit.name, *edit.aliases]}
        others = {
            word.casefold()
            for item in definitions
            if item.id != target.id
            for word in [item.id, item.name, *item.aliases]
        }
        if requested & others:
            raise DefinitionConflict("The name or aliases conflict with another business definition.")
        target.name, target.definition, target.owner = edit.name, edit.definition, edit.owner
        target.aliases = list(edit.aliases)
        target.definition_version += 1
        return TenantDomainPack.model_validate(candidate.model_dump())

    def create_draft(self, access: AccessContext, edit: DefinitionEdit) -> DefinitionDraft:
        state = self._state()
        self._manage(access, EDIT, state)
        if len(state.drafts) >= 64:
            raise DefinitionConflict("The definition review workspace has reached its capacity.")
        head = state.snapshots[-1]
        if edit.base_snapshot_id != head.snapshot_id:
            raise DefinitionConflict("The draft requires the latest published snapshot.")
        self._apply(head.pack, edit)
        draft = DefinitionDraft(edit=edit, author=access.user_id, created_at=self.clock())
        state.drafts.append(draft)
        self.store.save(self.namespace, state, state.revision)
        return draft

    def transition(
        self,
        access: AccessContext,
        draft_id: str,
        action: Literal["submit", "approve", "reject", "publish"],
        expected_revision: int,
        note: str,
    ) -> DefinitionDraft:
        state = self._state()
        self._manage(
            access, {"submit": EDIT, "approve": REVIEW, "reject": REVIEW, "publish": PUBLISH}[action], state
        )
        draft = next((d for d in state.drafts if d.draft_id == draft_id), None)
        if draft is None:
            raise DefinitionNotFound("The draft does not exist in this workspace.")
        if draft.revision != expected_revision:
            raise DefinitionConflict("The draft changed. Refresh its review state.")
        required = {
            "submit": DraftStatus.DRAFT,
            "approve": DraftStatus.IN_REVIEW,
            "reject": DraftStatus.IN_REVIEW,
            "publish": DraftStatus.APPROVED,
        }[action]
        if draft.status != required:
            raise DefinitionConflict("The requested transition is not valid for this review state.")
        if action == "submit":
            if draft.author != access.user_id:
                raise DefinitionDenied("Only the author can submit this draft.")
            draft.status = DraftStatus.IN_REVIEW
            draft.submission_note = note
        elif action in {"approve", "reject"}:
            if self.separate_reviewer and draft.author == access.user_id:
                raise DefinitionDenied("A different authorized person must review the definition.")
            draft.reviewer, draft.review_note = access.user_id, note
            draft.status = DraftStatus.APPROVED if action == "approve" else DraftStatus.REJECTED
        else:
            if draft.edit.base_snapshot_id != state.snapshots[-1].snapshot_id:
                raise DefinitionConflict("Another definition was published. Create and review a new draft.")
            if len(state.snapshots) >= 64:
                raise DefinitionConflict("Definition history capacity has been reached.")
            pack = self._apply(state.snapshots[-1].pack, draft.edit)
            pack.version = f"publication-{len(state.snapshots) + 1}"
            pack.effective_from = max(
                draft.edit.effective_from, self.clock(), state.snapshots[-1].pack.effective_from
            )
            snapshot = DefinitionSnapshot(
                snapshot_id=pack_hash(pack),
                sequence=len(state.events) + 1,
                pack=pack,
                published_at=self.clock(),
                published_by=access.user_id,
            )
            state.snapshots.append(snapshot)
            state.events.append(
                DefinitionEvent(
                    sequence=len(state.events) + 1,
                    kind="PUBLISHED",
                    snapshot_id=snapshot.snapshot_id,
                    occurred_at=self.clock(),
                    effective_from=pack.effective_from,
                    actor=access.user_id,
                    reason=draft.edit.reason,
                )
            )
            draft.status, draft.published_snapshot_id = DraftStatus.PUBLISHED, snapshot.snapshot_id
            draft.publication_note = note
        draft.revision += 1
        self.store.save(self.namespace, state, state.revision)
        return draft

    def revoke(self, access: AccessContext, snapshot_id: str, expected_revision: int, note: str) -> None:
        state = self._state()
        self._manage(access, REVOKE, state)
        if expected_revision != state.revision or snapshot_id in state.revoked:
            raise DefinitionConflict("The definition state changed or was already revoked.")
        snapshot = next((s for s in state.snapshots if s.snapshot_id == snapshot_id), None)
        if snapshot is None:
            raise DefinitionNotFound("The snapshot does not exist in this workspace.")
        state.revoked.add(snapshot_id)
        state.events.append(
            DefinitionEvent(
                sequence=len(state.events) + 1,
                kind="REVOKED",
                snapshot_id=snapshot_id,
                occurred_at=self.clock(),
                effective_from=self.clock(),
                actor=access.user_id,
                reason=note,
            )
        )
        self.store.save(self.namespace, state, state.revision)
