from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from talk2data.core.config import Settings
from talk2data.main import create_app

pytestmark = pytest.mark.live_ollama


@pytest.mark.skipif(
    os.getenv("T2D_RUN_LIVE_OLLAMA") != "1",
    reason="Set T2D_RUN_LIVE_OLLAMA=1 to run against a real local Ollama service.",
)
def test_real_ollama_interprets_and_answers_demo_question(tmp_path: Path) -> None:
    model = os.getenv("T2D_OLLAMA_MODEL", "qwen3:0.6b")
    settings = Settings(
        database_path=tmp_path / "live-ollama.db",
        ollama_enabled=True,
        ollama_required=True,
        ollama_base_url=os.getenv("T2D_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=model,
        ollama_timeout_seconds=180,
        hermes_enabled=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["components"]["ollama"]["status"] == "ready"

        response = client.post(
            "/v1/chat/demo",
            json={
                "question": "What was postpaid churn by plan last month?",
                "access_context": {
                    "tenant_id": "demo-telecom",
                    "user_id": "live-ollama-test",
                    "roles": ["TALK2DATA_ADMIN"],
                    "departments": ["BUSINESS_INTELLIGENCE"],
                    "regions": ["NORTH_AMERICA"],
                    "business_units": ["CONSUMER"],
                    "classification_clearance": "RESTRICTED",
                    "permitted_actions": [
                        "ASK_BUSINESS_QUESTIONS",
                        "READ_AGGREGATED_DATA",
                        "USE_EXTERNAL_CONTEXT",
                    ],
                },
                "use_llm": True,
                "include_debug": True,
                "as_of": "2026-08-17T12:00:00Z",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ANSWERED"
    assert body["decision"]["interpreter_mode"] == "OLLAMA_AND_RULES"
    assert body["ai_model"] == model
    assert body["verification"]["status"] == "VERIFIED"
    assert body["receipt"]["row_count"] == 3
