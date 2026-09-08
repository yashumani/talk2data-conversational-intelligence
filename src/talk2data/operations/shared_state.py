"""Explicit private migration and authorization publication; never runs from a browser request."""

import argparse
from pathlib import Path

from talk2data.core.internal_config import InternalRuntimeConfig
from talk2data.domain.runs import RunError
from talk2data.services.definition_store import DefinitionConflict
from talk2data.services.identity import EntitlementFile, IdentityUnavailable
from talk2data.services.postgres_database import PostgresDatabase
from talk2data.services.postgres_governance import PostgresEntitlementStore
from talk2data.services.secrets import SecretResolutionError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["migrate", "publish-grants", "check"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--expected-revision", type=int)
    args = parser.parse_args(argv)
    database = None
    try:
        config = InternalRuntimeConfig.load(args.config)
        if config.shared_state is None:
            raise ValueError("Shared state must be configured.")
        database = PostgresDatabase(config.shared_state)
        if args.action == "migrate":
            database.migrate()
        else:
            database.check()
        if args.action == "publish-grants":
            if args.expected_revision is None or args.expected_revision < 0:
                raise ValueError("Publication requires the reviewed current authorization revision.")
            grants = EntitlementFile.model_validate_json(config.entitlements_path.read_bytes())
            PostgresEntitlementStore(database, config.identity.issuer).publish(grants, args.expected_revision)
        print('{"status":"completed"}')
        return 0
    except (OSError, ValueError, RunError, DefinitionConflict, IdentityUnavailable, SecretResolutionError):
        print(
            '{"status":"failed","message":"Shared state operation rejected; inspect private configuration."}'
        )
        return 1
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
