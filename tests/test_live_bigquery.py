"""Private, opt-in acceptance. Never uses recording ports, fake JWT keys, or demo cloud data."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import Forbidden
from google.cloud import bigquery

from talk2data.core.bigquery_config import qualified_object
from talk2data.core.internal_config import InternalRuntimeConfig
from talk2data.internal.bootstrap import create_internal_app
from talk2data.services.bigquery_sdk import GoogleBigQueryTransport

pytestmark = pytest.mark.live_bigquery


@pytest.fixture(scope="module")
def approved_environment() -> tuple[InternalRuntimeConfig, dict[str, Any]]:
    if os.environ.get("T2D_RUN_LIVE_BIGQUERY") != "1":
        pytest.skip("Set T2D_RUN_LIVE_BIGQUERY=1 with an approved private acceptance manifest and ADC.")
    path = Path(os.environ["T2D_BIGQUERY_ACCEPTANCE_FILE"])
    assert path.is_absolute(), "The acceptance manifest must live at an approved private absolute path."
    manifest = json.loads(path.read_text())
    assert len(manifest["cases"]) >= 2, "Provide two independently authorized business scopes."
    assert all(case["expected_rows"] for case in manifest["cases"]), "Known numeric evidence is required."
    return InternalRuntimeConfig.load(Path(manifest["config_file"])), manifest


def token_headers(config: InternalRuntimeConfig, case: dict[str, Any]) -> dict[str, str]:
    token_path = Path(case["token_file"])
    assert token_path.is_absolute()
    token = token_path.read_text().strip()
    prefix = "Bearer " if config.identity.token_header == "authorization" else ""
    return {config.identity.token_header: prefix + token}


def test_live_signed_identity_scopes_and_known_results(approved_environment: Any) -> None:
    config, manifest = approved_environment
    scopes = set()
    jobs = set()
    with TestClient(create_internal_app(config)) as client:
        assert client.get("/v1/internal/me").status_code == 401
        for case in manifest["cases"]:
            auth = token_headers(config, case)
            me = client.get("/v1/internal/me", headers=auth)
            assert me.status_code == 200, "Signed identity verification failed."
            identity = me.json()
            scopes.add((identity["tenant_id"], tuple(identity["regions"]), tuple(identity["business_units"])))
            payload = {"question": case["question"], "as_of": case["as_of"]}
            assert (
                client.post(
                    "/v1/internal/chat", headers=auth, json={**payload, "roles": ["ADMIN"]}
                ).status_code
                == 422
            )
            response = client.post("/v1/internal/chat", headers=auth, json=payload)
            assert response.status_code == 200, "The authorized benchmark request failed."
            result = response.json()["result"]
            assert result["status"] == "ANSWERED" and result["verification"]["status"] == "VERIFIED"
            receipt = result["receipt"]
            assert receipt["source_kind"] == "bigquery"
            assert receipt["result_rows"] == case["expected_rows"]
            job = receipt["cloud_job"]
            assert job["billing_project"] == config.bigquery.billing_project
            assert job["location"] == config.bigquery.location
            assert job["estimated_bytes"] <= config.bigquery.maximum_bytes_billed
            jobs.add(job["job_id"])
    assert len(scopes) >= 2, "Two different subjects with identical scope do not prove scope isolation."
    assert len(jobs) == len(manifest["cases"]), "Each independent benchmark must identify its own cloud job."


def test_live_runtime_principal_cannot_read_forbidden_probe(approved_environment: Any) -> None:
    config, manifest = approved_environment
    forbidden_view = qualified_object(manifest["forbidden_probe_view"])
    transport = GoogleBigQueryTransport(config.bigquery)
    try:
        # Only an owner-approved, deliberately inaccessible synthetic probe; never issue a write test.
        with pytest.raises(Forbidden):
            transport.client.query(
                f"SELECT * FROM `{forbidden_view}` LIMIT 0",
                job_config=bigquery.QueryJobConfig(dry_run=True, use_legacy_sql=False, use_query_cache=False),
                location=config.bigquery.location,
                retry=transport.no_retry,
                job_retry=None,
                timeout=config.bigquery.api_timeout_seconds,
            )
    finally:
        transport.close()


def test_live_scan_budget_abstains(approved_environment: Any) -> None:
    config, manifest = approved_environment
    config = config.model_copy(
        update={"bigquery": config.bigquery.model_copy(update={"maximum_bytes_billed": 1})}
    )
    case = manifest["cases"][0]
    with TestClient(create_internal_app(config)) as client:
        response = client.post(
            "/v1/internal/chat",
            headers=token_headers(config, case),
            json={"question": case["question"], "as_of": case["as_of"]},
        )
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["status"] != "ANSWERED" and result["receipt"] is None
        assert "SCAN_BUDGET_EXCEEDED_OR_UNKNOWN" in result["message"]
