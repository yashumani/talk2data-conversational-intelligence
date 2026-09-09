from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from talk2data.api.web_assets import install_web_assets
from talk2data.connectors.base import StructuredQueryPlan
from talk2data.connectors.csv_demo import CsvDemoConnector
from talk2data.connectors.errors import ConnectorValidationError, SourceNotReadyError
from talk2data.core.config import Settings
from talk2data.core.csv_config import CsvDemoSettings
from talk2data.domain.models import (
    AccessContext,
    ComparisonSpec,
    MetricAggregation,
    MetricValueType,
    QueryFilter,
    TimeGrain,
    TimePreset,
    TimeWindow,
)
from talk2data.main import create_app
from talk2data.services.csv_import import parse_csv
from talk2data.services.csv_workspace import CsvDemoWorkspace, DemoSessionExpired, DemoWorkspaceBusy


def sample(*, start: date = date(2026, 7, 1), days: int = 31, amount: int = 100) -> bytes:
    rows = ["date,region,channel,activations"]
    rows.extend(f"{start + timedelta(days=day)},NORTHEAST,RETAIL,{amount}" for day in range(days))
    return ("\n".join(rows) + "\n").encode()


@pytest.fixture
def csv_client(tmp_path: Path) -> Any:
    app = create_app(
        Settings(database_path=tmp_path / "sessions.db", ollama_enabled=False, ollama_required=False),
        csv_settings=CsvDemoSettings(enabled=True),
    )
    with TestClient(app) as client:
        yield client


def new_session(client: TestClient) -> dict[str, str]:
    response = client.post("/v1/demo/csv/sessions")
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    return {"X-Demo-Session": response.json()["session_token"]}


def upload(client: TestClient, headers: dict[str, str], raw: bytes | None = None) -> dict[str, Any]:
    response = client.post(
        "/v1/demo/csv/upload",
        headers={**headers, "Content-Type": "text/csv"},
        content=sample() if raw is None else raw,
    )
    assert response.status_code == 200, response.text
    return response.json()


def ask(client: TestClient, headers: dict[str, str], fingerprint: str, **extra: Any) -> Any:
    return client.post(
        "/v1/demo/csv/chat",
        headers=headers,
        json={
            "question": "What were mobile activations by region last month?",
            "as_of": "2026-08-01T12:00:00Z",
            "source_fingerprint": fingerprint,
            **extra,
        },
    )


def test_optional_feature_is_off_by_default(client: TestClient) -> None:
    assert client.post("/v1/demo/csv/sessions").status_code == 404


def test_csv_answer_uses_its_own_connection_and_definition(csv_client: TestClient) -> None:
    headers = new_session(csv_client)
    source = upload(csv_client, headers)
    # An unusable internal registry must have no effect on a CSV run.
    csv_client.app.state.connector_registry = object()
    csv_client.app.state.demo_chat_service = object()
    response = ask(csv_client, headers, source["source_fingerprint"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "ANSWERED", result
    assert result["receipt"]["result_rows"] == [{"REGION": "NORTHEAST", "value": 3100.0}]
    assert result["receipt"]["source_kind"] == "csv_demo"
    assert result["receipt"]["source_fingerprint"] == source["source_fingerprint"]
    assert result["verification"]["status"] == "VERIFIED"
    assert result["ai_model"] is None
    assert result["synthetic_data"] is False
    assert "uploaded demo CSV" in result["answer"]["caveats"][0]
    state = csv_client.get("/v1/demo/csv/state", headers=headers).json()
    assert state["last_response"]["receipt"]["receipt_id"] == result["receipt"]["receipt_id"]
    assert state["definition"]["metric"]["semantic_version"] == result["query_ir"]["semantic_version"]
    assert state["internal_connections_available"] is False


def test_upload_replace_reset_and_session_isolation(csv_client: TestClient) -> None:
    first, second = new_session(csv_client), new_session(csv_client)
    one = upload(csv_client, first)
    two = upload(csv_client, second, sample(amount=5))
    assert ask(csv_client, first, one["source_fingerprint"]).json()["status"] == "ANSWERED"
    assert (
        ask(csv_client, second, two["source_fingerprint"]).json()["receipt"]["result_rows"][0]["value"] == 155
    )
    bad = csv_client.post(
        "/v1/demo/csv/upload",
        headers={**first, "Content-Type": "text/csv"},
        content=b"bad",
    )
    assert bad.status_code == 422
    assert csv_client.get("/v1/demo/csv/state", headers=first).json()["source"] == one
    replacement = upload(csv_client, first, sample(amount=7))
    assert ask(csv_client, first, one["source_fingerprint"]).status_code == 409
    assert csv_client.get("/v1/demo/csv/state", headers=first).json()["last_response"] is None
    assert ask(csv_client, first, replacement["source_fingerprint"]).json()["status"] == "ANSWERED"
    assert csv_client.post("/v1/demo/csv/clear", headers=first).status_code == 204
    assert csv_client.get("/v1/demo/csv/state", headers=first).status_code == 401
    assert csv_client.get("/v1/demo/csv/state", headers=second).status_code == 200


def test_no_role_or_connector_injection(csv_client: TestClient) -> None:
    headers = new_session(csv_client)
    source = upload(csv_client, headers)
    for extra in (
        {"access_context": {"roles": ["ADMIN"]}},
        {"connector_id": "bigquery"},
        {"session_id": str(uuid4())},
        {"use_llm": True},
    ):
        assert ask(csv_client, headers, source["source_fingerprint"], **extra).status_code == 422
    assert ask(csv_client, headers, source["source_fingerprint"], as_of="2026-08-01").status_code == 422
    assert csv_client.get("/v1/demo/csv/state").status_code == 422
    assert csv_client.get("/v1/demo/csv/state", headers={"X-Demo-Session": "x" * 43}).status_code == 401


def test_missing_days_and_unsupported_metrics_never_fall_back(csv_client: TestClient) -> None:
    headers = new_session(csv_client)
    source = upload(csv_client, headers, sample(days=30))
    result = ask(csv_client, headers, source["source_fingerprint"]).json()
    assert result["status"] == "SOURCE_NOT_READY"
    assert result["receipt"] is None
    result = ask(
        csv_client,
        headers,
        source["source_fingerprint"],
        question="What was postpaid churn by plan last month?",
    ).json()
    assert result["status"] == "INVALID"
    assert result["receipt"] is None


def test_upload_limits_and_required_source(csv_client: TestClient) -> None:
    headers = new_session(csv_client)
    assert ask(csv_client, headers, "a" * 64).status_code == 422
    assert csv_client.post("/v1/demo/csv/upload", headers=headers, content=sample()).status_code == 415
    response = csv_client.post(
        "/v1/demo/csv/upload",
        headers={**headers, "Content-Type": "text/csv"},
        content=b"a" * 2_000_001,
    )
    assert response.status_code == 413


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xff",
        b"\x00",
        b"date,region,channel,activations\n",
        b"date,region,channel,activations,activations\n",
        b"date,region,channel,activations,sql\n",
        b"date,region,channel,activations\n2026-07-01,NORTHEAST,RETAIL\n",
        b"date,region,channel,activations\ninvalid,NORTHEAST,RETAIL,2\n",
        b"date,region,channel,activations\n20260701,NORTHEAST,RETAIL,2\n",
        b"date,region,channel,activations\n2026-07-01,NORTHEAST,RETAIL,NaN\n",
        b"date,region,channel,activations\n2026-07-01,NORTHEAST,RETAIL,-2\n",
        b"date,region,channel,activations\n2026-07-01,NORTHEAST,RETAIL,1.5\n",
        b"date,region,channel,activations\n2026-07-01,UNKNOWN,RETAIL,2\n",
        b"date,region,channel,activations\n2026-07-01,NORTHEAST,UNKNOWN,2\n",
        b"date,region,channel,activations\n2026-07-01,=SUM(1),RETAIL,2\n",
        b'date,region,channel,activations\n"unterminated',
        sample(days=1) + b"2026-07-01,NORTHEAST,RETAIL,100\n",
    ],
)
def test_invalid_csv_rejected(raw: bytes) -> None:
    with pytest.raises(ConnectorValidationError):
        parse_csv(raw, maximum_bytes=10000, maximum_rows=100)


def test_row_limit_and_utf8_bom() -> None:
    with pytest.raises(ConnectorValidationError):
        parse_csv(sample(days=2), maximum_bytes=10000, maximum_rows=1)
    dataset = parse_csv(b"\xef\xbb\xbf" + sample(days=1), maximum_bytes=10000, maximum_rows=100)
    assert dataset.coverage_start == date(2026, 7, 1)


async def test_expiry_capacity_and_operation_lock() -> None:
    service = CsvDemoWorkspace(CsvDemoSettings(enabled=True, maximum_sessions=1))
    token = service.create_session()
    with pytest.raises(DemoWorkspaceBusy):
        service.create_session()
    async with service.lease(token):
        with pytest.raises(DemoWorkspaceBusy):
            async with service.lease(token):
                pass
        with pytest.raises(DemoWorkspaceBusy):
            service.clear(token)
    service.get(token).expires_at = 0
    with pytest.raises(DemoSessionExpired):
        service.get(token)
    assert service.create_session() != token


def connector_and_plan(
    raw: bytes | None = None,
) -> tuple[CsvDemoConnector, StructuredQueryPlan, AccessContext]:
    dataset = parse_csv(sample() if raw is None else raw, maximum_bytes=100000, maximum_rows=1000)
    connector = CsvDemoConnector(dataset=dataset, connector_id="demo", tenant_id="tenant", user_id="user")
    plan = StructuredQueryPlan(
        query_id=uuid4(),
        decision_id=uuid4(),
        plan_hash="hash",
        tenant_id="tenant",
        connector_id="demo",
        metric_id="MOBILE_ACTIVATIONS",
        semantic_version="2.0",
        value_type=MetricValueType.INTEGER,
        aggregation=MetricAggregation.SUM,
        unit="COUNT",
        dimensions=["REGION"],
        filters=[],
        comparison=ComparisonSpec(),
        time_window=TimeWindow(
            preset=TimePreset.CUSTOM,
            grain=TimeGrain.MONTH,
            anchor_date=date(2026, 8, 1),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            timezone="UTC",
            calendar="GREGORIAN",
        ),
    )
    access = AccessContext(
        tenant_id="tenant", user_id="user", regions={"NORTHEAST"}, permitted_actions={"READ_AGGREGATED_DATA"}
    )
    return connector, plan, access


async def test_connector_access_capabilities_and_no_silent_truncation() -> None:
    raw = sample() + b"2026-07-01,WEST,RETAIL,10\n"
    connector, plan, access = connector_and_plan(raw)
    await connector.initialize()
    assert (await connector.test_connection())[0]
    assert (await connector.discover_catalog(access))[0]["metric_ids"] == ["MOBILE_ACTIVATIONS"]
    assert (await connector.estimate_cost(plan))["billable_bytes"] == 0
    assert (await connector.get_freshness()).status == "AVAILABLE"
    assert await connector.cancel_query("unknown") is False
    with pytest.raises(ConnectorValidationError):
        await connector.discover_catalog(access.model_copy(update={"user_id": "another"}))
    with pytest.raises(ConnectorValidationError):
        await connector.execute_read_only(plan, access.model_copy(update={"regions": {"UNKNOWN"}}))
    with pytest.raises(ConnectorValidationError, match="too large"):
        await connector.execute_read_only(
            plan.model_copy(update={"row_limit": 1}),
            access.model_copy(update={"regions": {"NORTHEAST", "WEST"}}),
        )
    with pytest.raises(SourceNotReadyError, match="No CSV"):
        await connector.execute_read_only(plan, access.model_copy(update={"regions": {"CENTRAL"}}))


async def test_parallel_sessions_have_independent_state() -> None:
    service = CsvDemoWorkspace(CsvDemoSettings(enabled=True))
    a, b = service.create_session(), service.create_session()
    await asyncio.gather(
        service.upload(service.get(a), sample(amount=1)), service.upload(service.get(b), sample(amount=2))
    )
    assert service.get(a).dataset != service.get(b).dataset


def test_optional_built_frontend_mount(tmp_path: Path) -> None:
    app = FastAPI()
    with pytest.raises(ValueError, match="built React"):
        install_web_assets(app, tmp_path)
    assets = Path(__file__).parent / "fixtures" / "web"
    install_web_assets(app, assets)
    with TestClient(app) as client:
        assert "Workspace asset" in client.get("/workspace/").text
        assert client.get("/workspace/not-found.js").status_code == 404

    csv_app = create_app(
        Settings(
            database_path=tmp_path / "sessions.db",
            ollama_enabled=False,
            ollama_required=False,
            web_directory=assets,
        ),
        csv_settings=CsvDemoSettings(enabled=True),
    )
    with TestClient(csv_app) as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/workspace/"


async def test_connector_rejects_invalid_plan_scopes_and_filters() -> None:
    connector, plan, access = connector_and_plan()
    for update in (
        {"tenant_id": "different"},
        {"connector_id": "internal"},
        {"row_limit": 101},
        {"dimensions": ["TECHNOLOGY"]},
        {"filters": [QueryFilter(dimension_id="REGION", operator="IN", values=["WEST"])]},
        {"filters": [QueryFilter(dimension_id="TECHNOLOGY", operator="IN", values=["LTE"])]},
    ):
        with pytest.raises(ConnectorValidationError):
            await connector.execute_read_only(plan.model_copy(update=update), access)


async def test_group_with_missing_days_is_not_certified() -> None:
    connector, plan, access = connector_and_plan(sample() + b"2026-07-01,WEST,RETAIL,10\n")
    with pytest.raises(SourceNotReadyError, match="missing days"):
        await connector.execute_read_only(
            plan,
            access.model_copy(update={"regions": {"NORTHEAST", "WEST"}}),
        )


async def test_csv_comparisons_are_checked_before_composition() -> None:
    from talk2data.domain.models import ComparisonType

    raw = sample(start=date(2026, 5, 31), days=31, amount=50) + sample(amount=100).split(b"\n", 1)[1]
    connector, plan, access = connector_and_plan(raw)
    plan = plan.model_copy(
        update={
            "comparison": ComparisonSpec(comparison_type=ComparisonType.PRIOR_PERIOD),
        }
    )
    receipt = await connector.execute_read_only(plan, access)
    assert receipt.result_rows[0]["value"] == 3100
    assert receipt.result_rows[0]["comparison_value"] == 1550
    assert receipt.result_rows[0]["percent_change"] == 1.0
    assert receipt.comparison_start == date(2026, 5, 31)


def test_packaged_sample_answers_expected_question(csv_client: TestClient) -> None:
    headers = new_session(csv_client)
    sample_file = Path(__file__).parents[1] / "apps/web/public/samples/mobile-activations.csv"
    source = upload(csv_client, headers, sample_file.read_bytes())
    result = ask(csv_client, headers, source["source_fingerprint"]).json()
    assert result["status"] == "ANSWERED"
    assert len(result["receipt"]["result_rows"]) == 4
    assert sum(row["value"] for row in result["receipt"]["result_rows"]) == 24676
