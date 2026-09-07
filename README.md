# Talk2Data Conversational Intelligence

Talk2Data is a governed, local-first conversational intelligence platform for asking business
questions across enterprise data, organizational knowledge, and approved external evidence.

A language model interprets the wording of a question. Deterministic services define the metrics,
authorize access, compile the Business Query IR, execute read-only source queries, validate the
result, and release only receipt-backed claims.

## Use the application

### New modular CSV workspace

An optional React/TypeScript workspace now supports isolated CSV demonstrations with the
existing governed Python query pipeline. CSV uploads never change the configured data
backend or connect to BigQuery. The feature is disabled by default.

Start the optional local demonstration with Docker Compose:

```bash
docker compose -f docker-compose.csv-demo.yml up --build --wait --wait-timeout 120
```

Open [the React workspace](http://127.0.0.1:8000/workspace/). The standalone demo includes
the UI and Python service; no cloud credentials or model service are needed.

See the [CSV workspace runbook](docs/CSV_WORKSPACE.md) and the
[consolidated product orchestration plan](docs/PRODUCT_ORCHESTRATION_PLAN.md).
The CSV increment supports a strict Mobile Activations template. Use only synthetic or
explicitly approved demonstration data.

### Internal identity and BigQuery — Cycle 2

The separate private API now implements signed identity verification, server-owned tenant and
data permissions, approved BigQuery mappings, parameterized read-only queries, cost limits,
cancellation and cloud job receipts. It has its own container and configuration; CSV remains
independent. See the [internal BigQuery runbook](docs/INTERNAL_BIGQUERY.md).

Cycle 2 is complete on the approved connection-placeholder boundary. GCP/SSO activation and
live acceptance are deferred; CSV imports are the working optional data connection. See the
[connection placeholders](examples/internal/README.md). Claude, live definition publication
and durable multi-agent execution remain subsequent cycles in the agreed plan.

### Existing application

Public GitHub control center:

```text
https://yashumani.github.io/talk2data-conversational-intelligence/
```

Complete GitHub Codespaces runtime:

```text
https://codespaces.new/yashumani/talk2data-conversational-intelligence?ref=main&quickstart=1
```

The Codespace starts Docker, Ollama, the compact `qwen3:0.6b` model, FastAPI, synthetic telecom
data, session persistence, query execution, verification, and the browser chat. Port `8000` opens
privately after the runtime becomes ready.

```text
/demo         working browser chat
/docs         interactive OpenAPI explorer
/health/ready component readiness
```

Codespaces is a complete evaluation and development environment, not a permanent production host.
The same Docker application can run continuously on a workstation, server, VM, or container
platform controlled by the tenant.

## Current capabilities

- FastAPI service with versioned HTTP contracts.
- Local Ollama structured-output interpreter with deterministic fallback.
- Telecom Tenant Domain Pack with governed vocabulary, metrics, dimensions, aliases, exclusions,
  and approved external adjacencies.
- Question admissibility for domain fit, ambiguity, analytical validity, authorization, source
  readiness, and external-context eligibility.
- RBAC/ABAC-ready access context and classification checks.
- Versioned metric definitions with aggregation, additivity, units, ranges, time grain, source, and
  classification metadata.
- Deterministic Business Query IR with filters, reporting periods, comparisons, access scope,
  semantic snapshot hash, and canonical plan hash.
- Runtime connector registry.
- Parameterized, read-only synthetic SQLite connector.
- Parameterized, read-only PostgreSQL reference connector.
- Connector descriptor, catalog, freshness, health, and readiness APIs.
- Source coverage, row limit, timeout, access-scope, result-sense, and claim-verification controls.
- Deterministic SQL hashes, result hashes, query receipts, and certified numerical claims.
- Durable SQLite session history with tenant and user isolation.
- Hermes Agent gateway boundary for later bounded multi-agent investigations.
- GitHub Pages, Codespaces, Actions, CodeQL, and Docker deployment contracts.

## Architecture

```text
User question
    │
    ▼
Identity and access context
    │
    ▼
Question admissibility
    ├── tenant Domain Pack
    ├── business-sense checks
    ├── role and classification policy
    └── Ollama language interpretation
    │
    ├── clarify / deny / reject / no source
    │
    ▼
Semantic registry
    │
    ▼
Business Query IR
    │
    ▼
Governed connector registry
    ├── synthetic SQLite
    └── PostgreSQL reference adapter
    │
    ▼
Read-only parameterized execution
    │
    ▼
Source and result-sense verification
    │
    ▼
Certified claims and query receipt
```

The model cannot create a metric definition, authorize access, receive source credentials, generate
unrestricted SQL, calculate the certified result, or introduce unsupported numeric claims.

## Local development with synthetic SQLite

### 1. Start Ollama

```bash
ollama pull qwen3:8b
ollama serve
```

### 2. Install the application

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
```

### 3. Start FastAPI

```bash
uvicorn talk2data.main:app --reload
```

Open `http://127.0.0.1:8000/demo`.

## Docker with synthetic SQLite

```bash
T2D_OLLAMA_MODEL=qwen3:0.6b docker compose up --build
```

The Docker Compose stack starts Ollama, pulls the configured model, and starts Talk2Data.

## Docker with PostgreSQL

```bash
T2D_OLLAMA_MODEL=qwen3:0.6b \
  docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build
```

The override starts PostgreSQL 16, creates the governed reference metric-fact schema, seeds
employer-neutral telecom facts, and switches the source runtime to PostgreSQL.

See [`docs/POSTGRESQL_CONNECTOR.md`](docs/POSTGRESQL_CONNECTOR.md) for the table contract, security
properties, APIs, and production configuration.

## PostgreSQL production configuration

```text
T2D_DATA_BACKEND=postgresql
T2D_POSTGRES_DSN=postgresql://user:password@host:5432/database
T2D_POSTGRES_SCHEMA=talk2data
T2D_POSTGRES_TABLE=metric_facts
T2D_POSTGRES_MAXIMUM_ROWS=1000
T2D_POSTGRES_QUERY_TIMEOUT_SECONDS=60
T2D_POSTGRES_CONNECT_TIMEOUT_SECONDS=10
```

Store the DSN in a deployment secret or secret manager. Never commit credentials. The configured
table can be a governed database view over certified warehouse objects.

## Connector APIs

```text
POST /v1/connectors/list
POST /v1/connectors/catalog
POST /v1/connectors/freshness
POST /v1/connectors/test
```

Listing, catalog, and freshness requests require data-read permission. Connection testing requires
the `TALK2DATA_ADMIN` role. No endpoint returns a DSN or credential.

## Example governed chat request

```bash
curl -X POST http://127.0.0.1:8000/v1/chat/demo \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "What was postpaid churn by plan last month?",
    "as_of": "2026-08-17T12:00:00Z",
    "use_llm": true,
    "include_debug": true,
    "access_context": {
      "tenant_id": "demo-telecom",
      "user_id": "local-developer",
      "roles": ["BI_MANAGER"],
      "departments": ["BUSINESS_INTELLIGENCE"],
      "regions": ["NORTH_AMERICA"],
      "business_units": ["CONSUMER"],
      "classification_clearance": "CONFIDENTIAL",
      "permitted_actions": [
        "ASK_BUSINESS_QUESTIONS",
        "READ_AGGREGATED_DATA"
      ]
    }
  }'
```

A successful response includes the interpretation mode, admissibility decision, Business Query IR,
verified claims, source coverage, result hash, SQL hash, and query receipt.

## Accuracy behavior

Talk2Data abstains rather than guessing when:

- the question does not belong to the tenant domain;
- the metric or dimension is ambiguous;
- the user lacks permission;
- the source is unavailable or does not cover the requested period;
- the requested analytical operation violates the metric contract;
- the result contains invalid, duplicate, non-finite, or out-of-range values;
- the question asks for causal or organizational context that has not been supplied by the Unified
  AI Brain integration.

## Hermes Agent integration

Hermes is the bounded agent runtime for later multi-step investigations. Ollama remains the local
model provider. Talk2Data never delegates authorization, semantic definitions, or certified data
execution to Hermes. Hermes will receive only approved tools and typed evidence after policy and
semantic gates complete.

## Quality checks

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=talk2data --cov-report=term-missing --cov-report=json:coverage.json
python scripts/check_coverage.py
npm --prefix apps/web test
npm --prefix apps/web run build
```

CI requires **96% line and 96% branch coverage independently** across the entire Python
package. No connector or domain model is omitted. React CI requires at least 96% of lines,
branches, functions, and statements across all application TypeScript, including components,
hooks, and the entry point. Coverage reports are retained as workflow artifacts.

A separate GitHub Actions workflow starts a real PostgreSQL service and runs the full PostgreSQL
chat and receipt path. The full Docker/Ollama pipeline is also smoke-tested on GitHub-hosted runners.
The canonical [product plan](docs/PRODUCT_ORCHESTRATION_PLAN.md#13-verification-and-benchmark-strategy)
maps the original requirements to tests and enterprise release criteria. Passing coverage does
not mean Claude, BigQuery, live semantic publication, or durable agents are implemented.

## Documentation

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/semantic-registry.md`](docs/semantic-registry.md)
- [`docs/POSTGRESQL_CONNECTOR.md`](docs/POSTGRESQL_CONNECTOR.md)
- [`docs/GITHUB_RUNTIME.md`](docs/GITHUB_RUNTIME.md)
- [`docs/roadmap.md`](docs/roadmap.md)

## Repository safety

This repository is public. Commit only synthetic examples and configuration templates. Never commit
credentials, internal database names, proprietary schemas, production Domain Packs, private Obsidian
content, customer data, employee data, or organizational memory.
