# Talk2Data Conversational Intelligence

Talk2Data is a governed, local-first conversational intelligence platform for asking business questions across enterprise data, organizational knowledge, and approved external evidence.

The platform currently implements two deterministic control stages before any enterprise source is executed:

1. **Question admissibility** determines whether a request belongs to the tenant's business domain, is analytically meaningful, is authorized, and has an eligible governed source.
2. **Business Query IR compilation** converts an accepted data question into a versioned, reproducible semantic plan containing the exact metric contract, dimensions, filters, time logic, comparison, access scope, source, and integrity hashes.

The natural-language interpretation layer uses **Ollama running locally**. Ollama may propose a structured interpretation, but it cannot create business definitions, authorize access, or execute data. Every proposed metric, entity, dimension, and domain identifier must already exist in the approved Tenant Domain Pack.

## Current capabilities

- FastAPI service with versioned HTTP contracts.
- Local Ollama structured-output interpreter with deterministic fallback.
- Telecom demonstration Tenant Domain Pack.
- Domain-anchor, external-adjacency, exclusion, and analytic-validity checks.
- RBAC/ABAC-ready access context and deterministic policy gate.
- Versioned metric definitions with aggregation, additivity, unit, range, time-grain, source, and classification metadata.
- Authorized semantic metric resolution with a deterministic semantic snapshot hash.
- Business Query IR compilation with governed dimensions, dimension-value filters, time windows, comparisons, connector identity, and access scope.
- Canonical plan hashing so equivalent questions produce the same plan under the same semantic and authorization context.
- Durable SQLite session history containing decisions and compiled query plans.
- Hermes Agent gateway adapter and health integration.
- Universal connector contracts for future BigQuery, Teradata, SQL Server, PostgreSQL, Snowflake, Databricks, REST, and custom adapters.
- Evidence, memory, and context-coverage contracts for later implementation.
- CI across Python 3.11, 3.12, and 3.13, plus linting, formatting, strict typing, coverage, and CodeQL.

## Architecture at a glance

```text
Chat client
    │
    ▼
AI access gateway
    │
    ▼
Question admissibility engine
    ├── Tenant Domain Pack
    ├── deterministic business-sense checks
    ├── role/classification policy checks
    └── local Ollama structured interpretation
    │
    ├── clarify / deny / reject / no source
    │
    ▼
Versioned semantic registry
    ├── metric contract
    ├── valid dimensions and values
    ├── calendar, currency, and timezone
    └── governed connector
    │
    ▼
Business Query IR compiler
    ├── metric and semantic version
    ├── dimensions and filters
    ├── time window and comparison
    ├── access scope
    ├── semantic snapshot hash
    └── canonical plan hash
    │
    ▼
Approved connector execution — next stage
```

See [`docs/architecture.md`](docs/architecture.md), [`docs/semantic-registry.md`](docs/semantic-registry.md), and [`docs/roadmap.md`](docs/roadmap.md).

## Local development

### 1. Install and start Ollama

```bash
ollama pull qwen3:8b
ollama serve
```

The model is configurable through `T2D_OLLAMA_MODEL`.

### 2. Create the Python environment

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
```

### 3. Run the API

```bash
uvicorn talk2data.main:app --reload
```

Open the generated API documentation at `http://127.0.0.1:8000/docs`.

## Evaluate question admissibility

```bash
curl -X POST http://127.0.0.1:8000/v1/questions/evaluate \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "Did restaurant foot traffic near our stores affect mobile activations?",
    "access_context": {
      "tenant_id": "demo-telecom",
      "user_id": "local-developer",
      "roles": ["BI_MANAGER"],
      "departments": ["SALES"],
      "regions": ["NORTH_AMERICA"],
      "business_units": ["CONSUMER"],
      "classification_clearance": "CONFIDENTIAL",
      "permitted_actions": [
        "ASK_BUSINESS_QUESTIONS",
        "READ_AGGREGATED_DATA",
        "READ_APPROVED_MEMORY",
        "USE_EXTERNAL_CONTEXT"
      ]
    },
    "use_llm": true
  }'
```

Expected verdict: `ACCEPT_EXTERNAL_AUGMENTED`.

## Compile a Business Query IR

```bash
curl -X POST http://127.0.0.1:8000/v1/query-plans/compile \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "What was postpaid churn by plan in the Northeast last month?",
    "as_of": "2026-08-17T12:00:00Z",
    "access_context": {
      "tenant_id": "demo-telecom",
      "user_id": "local-developer",
      "roles": ["BI_MANAGER"],
      "departments": ["SALES"],
      "regions": ["NORTH_AMERICA"],
      "business_units": ["CONSUMER"],
      "classification_clearance": "CONFIDENTIAL",
      "permitted_actions": [
        "ASK_BUSINESS_QUESTIONS",
        "READ_AGGREGATED_DATA",
        "READ_APPROVED_MEMORY",
        "USE_EXTERNAL_CONTEXT"
      ]
    },
    "use_llm": true
  }'
```

The response includes a `BusinessQueryIR` with `POSTPAID_CHURN` semantic version `2.0`, `PLAN` as a dimension, a governed `REGION=NORTHEAST` filter, the tenant fiscal calendar, the approved source connector, and deterministic semantic and plan hashes.

## Resolve a governed metric definition

```bash
curl -X POST http://127.0.0.1:8000/v1/semantics/metrics/resolve \
  -H 'Content-Type: application/json' \
  -d '{
    "metric_id": "POSTPAID_CHURN",
    "access_context": {
      "tenant_id": "demo-telecom",
      "user_id": "local-developer",
      "classification_clearance": "CONFIDENTIAL",
      "permitted_actions": ["READ_AGGREGATED_DATA"]
    }
  }'
```

## Docker development

```bash
cp .env.example .env
docker compose up --build
```

Pull the configured model into the Ollama container once:

```bash
docker compose exec ollama ollama pull qwen3:8b
```

## Hermes Agent integration

Hermes is the bounded agent runtime for later multi-step investigations. Ollama remains the local model provider. Configure Hermes to use `http://127.0.0.1:11434/v1`, enable its authenticated API server, and set the `T2D_HERMES_*` environment variables.

Talk2Data never delegates authorization, semantic definitions, or certified data execution to Hermes. Hermes receives only approved tools and typed evidence after the policy and semantic gates have completed.

## Quality checks

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=talk2data --cov-report=term-missing
```

## Repository safety

This repository is public. Commit only synthetic examples and configuration templates. Never commit credentials, internal database names, private schemas, production Domain Packs, proprietary Obsidian vault content, or customer data.
