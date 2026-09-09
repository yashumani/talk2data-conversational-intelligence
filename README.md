# Talk2Data Conversational Intelligence

Talk2Data is a governed, local-first conversational intelligence platform for asking business
questions across enterprise data, organizational knowledge, and approved external evidence.

A language model interprets the wording of a question. Deterministic services define the metrics,
authorize access, compile the Business Query IR, execute read-only source queries, validate the
result, and release only receipt-backed claims.

## Use the application

Start with the [product handoff](docs/HANDOFF.md) for the reviewed candidate, runnable CSV demo,
cycle status and remaining live acceptance inputs. The [final review](docs/FINAL_REVIEW.md)
records corrections, verification and the boundaries of the handoff.
Use the [repository activation guide](docs/REPOSITORY_ACTIVATION_GUIDE.md) for the complete
merge, validation, Claude, GCP/BigQuery/IAP, Cloud SQL bootstrap and release procedure.
For a BigQuery-first deployment that does not require Cloud Run or Cloud SQL, including the
optional governed Parquet acceleration path, see the
[BigQuery/Parquet runtime guide](docs/BIGQUERY_PARQUET_RUNTIME.md).
The [GitHub Pages showcase](https://yashumani.github.io/talk2data-conversational-intelligence/)
provides an interactive, explicitly non-live preview of the current UI and all four activation
profiles; its primary action launches the real CSV workspace in Codespaces.

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

### Internal identity, BigQuery and optional Parquet — Cycle 2

The separate private API now implements signed identity verification, server-owned tenant and
data permissions, approved BigQuery mappings, parameterized read-only queries, cost limits,
cancellation and cloud job receipts. It has its own container and configuration; CSV remains
independent. See the [internal BigQuery runbook](docs/INTERNAL_BIGQUERY.md).
Direct BigQuery can use local SQLite application state. An explicit operator command can also
materialize approved read-only results into hash-pinned Parquet for fast local queries; this mode
does not initialize BigQuery at API runtime. Cloud Run and Cloud SQL remain optional scale-out
components.

Cycle 2 is complete on the approved connection-placeholder boundary. GCP/SSO activation and
live acceptance are deferred; CSV imports are the working optional data connection. See the
[connection placeholders](examples/internal/README.md). These placeholders do not report a
healthy warehouse. CSV remains independently usable now.

### Live business definitions — Cycle 3

The CSV workspace now supports metric and dimension definition drafts, review, approval,
publication, effective dates and withdrawal. Answers cite their exact definitions; the latest
four successful CSV runs can be reproduced with their saved data and publication. The separate
internal API enforces server-owned permissions and a different author/reviewer. See
[the definition governance runbook](docs/DEFINITION_GOVERNANCE.md) for the workflow, storage and limits.

### Claude and bounded specialists — Cycle 4

An opt-in Claude interpreter now resolves questions against approved business definitions.
Five bounded specialist stages reuse the governed query and verification services. CSV and
internal configuration remain separate; CSV rows and query results are not sent to Claude.
Saved CSV answers reuse their validated interpretation without another model call.

See the [Claude configuration and orchestration runbook](docs/CLAUDE_ORCHESTRATION.md).
Local contract validation is implemented; the real-provider acceptance gate **LA-1 remains
open until the configured live benchmark passes**.

### Durable conversations and synchronization — Cycle 5

The React CSV workspace now saves conversation history, shows specialist progress, resumes
interrupted event connections and supports cancellation. Idempotent requests prevent lost
acknowledgments from creating duplicate runs. The separate internal API exposes the same run
contract under signed identity and server-owned source bindings.

The packaged CSV demonstration persists sources, definitions, completed answers and events
across container restarts on its own volume. Unfinished work becomes explicitly interrupted
and is never automatically queried again. Local Python configuration remains memory-only
unless a state database path is supplied. Keep one API worker per SQLite database.

See [durable conversations and restart acceptance](docs/DURABLE_CONVERSATIONS.md) for the
architecture, API, recovery rules and storage limits. This milestone proceeds at the user's
request while LA-1 remains open. Cycle 6 adds the shared internal runtime described below;
private activation and enterprise acceptance remain outstanding.

### Enterprise completion candidate — Cycle 6

The first milestone of Cycle 6 adds verified offline backup/restore, previewed internal retention
with transactional audit, bounded internal HTTP requests and telemetry that omits request content.
A release evidence checker rejects missing, stale, mismatched or unverified receipts; skipped
Claude tests and deferred GCP connections cannot qualify as live acceptance.

See [release operations and the remaining milestones](docs/RELEASE_OPERATIONS.md). The package
acceptance restores a synthetic workspace into a separate database and verifies its original
answers over HTTP. The consolidated candidate also adds shared PostgreSQL conversations,
definitions and grants, independently running workers with fenced completion, an isolated
signed internal React workspace, and private Cloud SQL/Cloud Run infrastructure.

The [shared internal runtime guide](docs/SHARED_INTERNAL_RUNTIME.md) explains setup, transaction
boundaries and operating limits. The [completion ledger](docs/PROJECT_COMPLETION.md) separates
implemented capabilities from pending live acceptance. Trusted release checks bind workflow
artifacts and three distinct owner approvals to the exact source, image and configuration.
**LA-1 remains open; DG-1 remains user-deferred. This is a development candidate, not a
production release.** Development integration does not imply a private deployment or owner approval.

### Existing application

Public GitHub product showcase:

```text
https://yashumani.github.io/talk2data-conversational-intelligence/
```

GitHub Codespaces CSV workspace:

```text
https://codespaces.new/yashumani/talk2data-conversational-intelligence?ref=main&quickstart=1
```

The Codespace starts the isolated CSV Compose profile, FastAPI, durable demo state and the React
workspace. It needs no GCP access or model download. Port `8000` opens privately after readiness.

```text
/workspace/   React CSV workspace
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
python scripts/dependencies.py install dev
cp .env.example .env
```

The installer verifies committed dependency hashes before installing. Use a clean virtual
environment; see [dependency maintenance](docs/BUILD_REPRODUCIBILITY.md) for supported profiles,
updates and the remaining image/infrastructure reproducibility boundaries.

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

Hermes remains an optional extension boundary for later multi-step investigations. Cycle 4 uses
the native bounded specialist runtime and an opt-in Claude adapter; existing local Ollama behavior
remains available. Authorization, semantic definitions and certified execution stay in deterministic
services. Any future Hermes adapter must receive approved tools and typed evidence after those gates.

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
maps the original requirements to tests and enterprise release criteria. Passing coverage
does not prove real Claude/GCP acceptance, production semantic approval or enterprise readiness.
Durable runs additionally require the transactional, scope/replay and actual restart acceptance
checks described in the Cycle 5 runbook.

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
