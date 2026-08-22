from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient

from talk2data.core.config import Settings
from talk2data.main import create_app

pytestmark = pytest.mark.live_postgres

SCHEMA = "talk2data_integration"
TABLE = "metric_facts"


def churn_row(fact_date: str, numerator: int, plan: str) -> tuple[object, ...]:
    return (
        fact_date,
        "POSTPAID_CHURN",
        None,
        numerator,
        5000,
        plan,
        "NORTHEAST_MARKET",
        "NORTHEAST",
        "RETAIL",
        None,
        None,
        None,
        None,
    )


@contextmanager
def seeded_postgres(dsn: str) -> Iterator[None]:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        connection.execute(f'CREATE SCHEMA "{SCHEMA}"')
        connection.execute(
            f"""
            CREATE TABLE "{SCHEMA}"."{TABLE}" (
                fact_date date NOT NULL,
                metric_id text NOT NULL,
                amount double precision,
                numerator double precision,
                denominator double precision,
                plan_id text,
                market_id text,
                region_id text,
                channel_id text,
                store_id text,
                cell_site_id text,
                hour_id text,
                technology_id text
            )
            """
        )
        connection.executemany(
            f"""
            INSERT INTO "{SCHEMA}"."{TABLE}" (
                fact_date, metric_id, amount, numerator, denominator,
                plan_id, market_id, region_id, channel_id, store_id,
                cell_site_id, hour_id, technology_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                churn_row("2026-06-01", 120, "STARTER"),
                churn_row("2026-06-01", 92, "UNLIMITED"),
                churn_row("2026-06-01", 67, "PREMIUM"),
                churn_row("2026-07-01", 117, "STARTER"),
                churn_row("2026-07-01", 89, "UNLIMITED"),
                churn_row("2026-07-01", 64, "PREMIUM"),
            ],
        )
    try:
        yield
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')


def test_live_postgres_end_to_end_receipt_backed_answer(tmp_path) -> None:  # type: ignore[no-untyped-def]
    if os.environ.get("T2D_RUN_LIVE_POSTGRES") != "1":
        pytest.skip("Set T2D_RUN_LIVE_POSTGRES=1 to run the live PostgreSQL integration test.")
    dsn = os.environ.get("T2D_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("T2D_TEST_POSTGRES_DSN is not configured.")

    access = {
        "tenant_id": "demo-telecom",
        "user_id": "postgres-integration-user",
        "roles": ["BI_MANAGER"],
        "departments": ["BUSINESS_INTELLIGENCE"],
        "regions": ["NORTH_AMERICA"],
        "business_units": ["CONSUMER"],
        "classification_clearance": "CONFIDENTIAL",
        "permitted_actions": ["ASK_BUSINESS_QUESTIONS", "READ_AGGREGATED_DATA"],
    }

    with seeded_postgres(dsn):
        settings = Settings(
            database_path=tmp_path / "sessions.db",
            data_backend="postgresql",
            postgres_dsn=dsn,
            postgres_schema=SCHEMA,
            postgres_table=TABLE,
            ollama_enabled=False,
            ollama_required=False,
            hermes_enabled=False,
        )
        with TestClient(create_app(settings)) as client:
            readiness = client.get("/health/ready")
            response = client.post(
                "/v1/chat/demo",
                json={
                    "question": "What was postpaid churn by plan last month?",
                    "access_context": access,
                    "use_llm": False,
                    "include_debug": True,
                    "as_of": "2026-08-17T12:00:00Z",
                },
            )
            freshness = client.post(
                "/v1/connectors/freshness",
                json={
                    "connector_id": "telecom_semantic_warehouse",
                    "access_context": access,
                },
            )

    assert readiness.status_code == 200
    assert readiness.json()["components"]["connector:telecom_semantic_warehouse"]["status"] == "ready"
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ANSWERED"
    assert body["synthetic_data"] is False
    assert body["verification"]["status"] == "VERIFIED"
    assert body["receipt"]["row_count"] == 3
    assert body["receipt"]["result_hash"]
    assert "POSTGRESQL_READ_ONLY_TRANSACTION" in body["receipt"]["data_quality_checks"]
    assert freshness.status_code == 200
    assert freshness.json()["freshness"]["coverage_end"] == "2026-07-31T23:59:59.999999Z"
