"""Cross-instance definition publication and current authorization in the state database."""

from talk2data.domain.governance import GovernanceState, pack_hash
from talk2data.domain.models import AccessContext
from talk2data.domain.runs import digest
from talk2data.services.definition_store import DefinitionConflict, DefinitionUnavailable
from talk2data.services.identity import EntitlementFile, IdentityRejected, IdentityUnavailable
from talk2data.services.postgres_database import PostgresDatabase


class PostgresDefinitionStore:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def seed(self, namespace: str, state: GovernanceState) -> None:
        with self.database.transaction() as db:
            db.execute(
                "INSERT INTO t2d_definitions VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (namespace, state.revision, state.model_dump_json()),
            )

    def read(self, namespace: str) -> GovernanceState:
        with self.database.transaction() as db:
            row = db.execute(
                "SELECT revision,payload FROM t2d_definitions WHERE namespace=%s", (namespace,)
            ).fetchone()
        if row is None:
            raise DefinitionUnavailable("Definition workspace is unavailable.")
        try:
            state = GovernanceState.model_validate_json(row[1])
            if (
                state.revision != row[0]
                or not state.snapshots
                or any(s.snapshot_id != pack_hash(s.pack) for s in state.snapshots)
            ):
                raise ValueError("Integrity failed")
        except ValueError:
            raise DefinitionUnavailable("Definition snapshot integrity failed.") from None
        return state

    def save(self, namespace: str, state: GovernanceState, expected: int) -> None:
        state.revision = expected + 1
        with self.database.transaction() as db:
            changed = db.execute(
                "UPDATE t2d_definitions SET revision=%s,payload=%s WHERE namespace=%s AND revision=%s",
                (state.revision, state.model_dump_json(), namespace, expected),
            ).rowcount
            if changed != 1:
                raise DefinitionConflict("Definitions changed. Refresh before retrying.")

    def delete(self, namespace: str) -> None:
        with self.database.transaction() as db:
            db.execute("DELETE FROM t2d_definitions WHERE namespace=%s", (namespace,))

    def close(self) -> None:
        # Connection ownership belongs to the runtime, shared with the run/authorization stores.
        pass


class PostgresEntitlementStore:
    def __init__(self, database: PostgresDatabase, issuer: str) -> None:
        self.database, self.issuer = database, issuer

    def publish(self, grants: EntitlementFile, expected: int) -> int:
        if grants.issuer != self.issuer:
            raise IdentityUnavailable("Authorization issuer does not match the trust root.")
        with self.database.transaction() as db:
            db.execute("SELECT id FROM t2d_admission WHERE id=1 FOR UPDATE")
            row = db.execute(
                "SELECT revision FROM t2d_grants WHERE issuer=%s FOR UPDATE", (self.issuer,)
            ).fetchone()
            if (0 if row is None else row[0]) != expected:
                raise DefinitionConflict("Authorization changed. Refresh before publishing.")
            revision = expected + 1
            db.execute(
                "INSERT INTO t2d_grants VALUES (%s,%s,%s) ON CONFLICT(issuer) "
                "DO UPDATE SET revision=excluded.revision,payload=excluded.payload",
                (self.issuer, revision, grants.model_dump_json()),
            )
            db.execute(
                "INSERT INTO t2d_grant_audit(issuer,revision,digest) VALUES (%s,%s,%s)",
                (self.issuer, revision, digest(grants.model_dump(mode="json"))),
            )
        return revision

    def resolve(self, subject: str) -> AccessContext:
        with self.database.transaction() as db:
            row = db.execute("SELECT payload FROM t2d_grants WHERE issuer=%s", (self.issuer,)).fetchone()
        if row is None:
            raise IdentityUnavailable("Authorization has not been published.")
        try:
            grants = EntitlementFile.model_validate_json(row[0])
            if grants.issuer != self.issuer:
                raise ValueError("Issuer mismatch")
        except ValueError:
            raise IdentityUnavailable("Authorization configuration is unavailable.") from None
        access = next((entry for entry in grants.bindings if entry.user_id == subject), None)
        if access is None:
            raise IdentityRejected("No active authorization grant exists for this identity.")
        return access
