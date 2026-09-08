"""Bounded PostgreSQL transactions. Migration is explicit and never performed by the API."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from threading import RLock
from typing import Any

import psycopg
from psycopg.conninfo import conninfo_to_dict

from talk2data.core.state_config import SharedStateSettings
from talk2data.domain.runs import RunError
from talk2data.services.secrets import EnvironmentSecretResolver, SecretResolver


class PostgresDatabase:
    def __init__(self, settings: SharedStateSettings, secrets: SecretResolver | None = None) -> None:
        self.settings = settings
        self._dsn = (secrets or EnvironmentSecretResolver()).resolve(settings.dsn_secret_ref)
        try:
            config = conninfo_to_dict(self._dsn.get_secret_value())
        except psycopg.Error:
            raise ValueError("Shared state connection configuration is invalid.") from None
        host = str(config.get("host", ""))
        local = settings.allow_insecure_loopback and host in {"127.0.0.1", "localhost", "::1"}
        # Cloud SQL's authenticated connector supplies a private Unix socket.
        socket = host.startswith("/cloudsql/") and "," not in host
        if not local and not socket and config.get("sslmode") != "verify-full":
            raise ValueError("Shared state requires verified TLS or an authenticated Cloud SQL socket.")
        self._lock = RLock()
        self._connection: psycopg.Connection[tuple[Any, ...]] | None = None

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection[tuple[Any, ...]]]:
        with self._lock:
            try:
                if self._connection is None or self._connection.closed:
                    self._connection = psycopg.connect(
                        self._dsn.get_secret_value(),
                        connect_timeout=5,
                        autocommit=True,
                        application_name="talk2data-state",
                    )
                with self._connection.transaction():
                    self._connection.execute("SET LOCAL statement_timeout = '5000ms'")
                    self._connection.execute("SET LOCAL lock_timeout = '2000ms'")
                    self._connection.execute("SET LOCAL search_path = public")
                    yield self._connection
            except psycopg.Error:
                raise RunError(
                    "Shared state is temporarily unavailable. Retry the same request ID.", 503
                ) from None

    def migrate(self) -> None:
        with self.transaction() as db:
            db.execute("SELECT pg_advisory_xact_lock(74120501)")
            if db.execute("SELECT to_regclass('public.t2d_schema')").fetchone()[0] is None:  # type: ignore[index]
                sql = files("talk2data").joinpath("resources/migrations/001_shared_state.sql").read_text()
                db.execute(sql)
            self._check(db)

    @staticmethod
    def _check(db: psycopg.Connection[tuple[Any, ...]]) -> None:
        if db.execute("SELECT version FROM t2d_schema").fetchall() != [(1,)]:
            raise RunError("Shared state requires an approved schema migration.", 503)

    def check(self) -> None:
        with self.transaction() as db:
            self._check(db)

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
