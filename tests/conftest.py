from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from talk2data.core.config import Settings
from talk2data.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "talk2data-test.db",
        ollama_enabled=False,
        ollama_required=False,
        hermes_enabled=False,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def full_access() -> dict[str, object]:
    return {
        "tenant_id": "demo-telecom",
        "user_id": "test-user",
        "roles": ["BI_MANAGER"],
        "departments": ["SALES"],
        "regions": ["NORTH_AMERICA"],
        "business_units": ["CONSUMER"],
        "classification_clearance": "CONFIDENTIAL",
        "permitted_actions": [
            "ASK_BUSINESS_QUESTIONS",
            "READ_AGGREGATED_DATA",
            "READ_APPROVED_MEMORY",
            "USE_EXTERNAL_CONTEXT",
        ],
    }
