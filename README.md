# Talk2Data Conversational Intelligence

Talk2Data is a governed, local-first conversational intelligence platform for asking business questions across enterprise data, organizational knowledge, and approved external evidence.

The first development slice implements the platform control plane for **question admissibility**. Before any data or memory retrieval occurs, Talk2Data determines whether a question:

- belongs to the tenant's business domain,
- has an approved internal business anchor,
- is analytically meaningful,
- is allowed for the user's role and clearance,
- requires internal data, organizational knowledge, or approved external context,
- can be answered from available sources, or
- must be clarified, denied, or rejected.

The AI interpretation layer uses **Ollama running locally**. The final decision remains deterministic and policy-driven: model-proposed metric, entity, or domain identifiers are accepted only when they exist in the governed Tenant Domain Pack.

## Current capabilities

- FastAPI service with versioned HTTP contracts.
- Local Ollama structured-output interpreter with deterministic fallback.
- Telecom demonstration Tenant Domain Pack.
- Domain-anchor, external-adjacency, exclusion, and analytic-validity checks.
- RBAC/ABAC-ready access context and policy gate.
- Durable SQLite session and decision-receipt history.
- Hermes Agent gateway adapter and health integration.
- Universal data-connector contracts for later BigQuery, Teradata, SQL Server, PostgreSQL, Snowflake, Databricks, REST, and custom adapters.
- Evidence, memory, and context-coverage contracts for later implementation.
- CI, type checking, linting, tests, and security scaffolding.

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
    ├── deterministic semantic checks
    ├── role/classification policy checks
    └── Ollama structured interpretation
    │
    ▼
Decision receipt
    ├── ACCEPT_INTERNAL
    ├── ACCEPT_KNOWLEDGE
    ├── ACCEPT_EXTERNAL_AUGMENTED
    ├── CLARIFY
    ├── VALID_NO_SOURCE
    ├── OUT_OF_DOMAIN
    ├── INVALID_ANALYTIC_REQUEST
    ├── DENY
    ├── CONFLICTING_DEFINITIONS
    └── SOURCE_NOT_READY
```

See [`docs/architecture.md`](docs/architecture.md) for the full target architecture and staged evolution.

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

### 4. Evaluate a question

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

Talk2Data never delegates authorization or certified data execution to Hermes. Hermes receives only approved tools and typed evidence after the policy and semantic gates have completed.

## Quality checks

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=talk2data --cov-report=term-missing
```

## Repository safety

This repository is public. Commit only synthetic examples and configuration templates. Never commit credentials, internal database names, private schemas, production Domain Packs, proprietary Obsidian vault content, or customer data.
