# Talk2Data Conversational Intelligence

Talk2Data is a governed, local-first conversational intelligence platform for asking business questions across enterprise data, organizational knowledge, and approved external evidence.

A language model interprets the wording of a question. Deterministic services define the metrics, authorize access, compile the Business Query IR, execute read-only source queries, validate results, and release only receipt-backed claims.

## Use Talk2Data

Public GitHub control center:

```text
https://yashumani.github.io/talk2data-conversational-intelligence/
```

Guided Data Source builder:

```text
https://yashumani.github.io/talk2data-conversational-intelligence/setup/
```

Complete GitHub Codespaces runtime:

```text
https://codespaces.new/yashumani/talk2data-conversational-intelligence?ref=main&quickstart=1
```

The Codespace starts Docker, Ollama, the compact `qwen3:0.6b` model, FastAPI, synthetic telecom data, session persistence, governed execution, verification, and the browser chat.

```text
/demo         working browser chat
/docs         interactive OpenAPI explorer
/health/ready component readiness
```

Codespaces is a complete evaluation and development environment, not a permanent production host. The same Docker runtime can run continuously on a workstation, server, VM, or container platform controlled by the tenant.

## Guided tenant generation

The browser builder creates a downloadable tenant package around the stable Talk2Data runtime. It collects:

- project and tenant identifiers;
- approved PostgreSQL schema, table, and column names;
- metric and dimension mappings;
- an environment-variable name for the database secret;
- local Ollama model and execution limits.

It does **not** request or store a database password or DSN.

The generated ZIP contains:

```text
.env.example
docker-compose.yml
README.md
checksums.json
config/talk2data.yaml
config/domain-packs/<tenant>.yaml
config/physical-mappings/<tenant>.yaml
scripts/start.sh
scripts/start.ps1
.github/workflows/validate.yml
.devcontainer/devcontainer.json   # optional
```

The package references the runtime image published from `main`:

```text
ghcr.io/yashumani/talk2data-conversational-intelligence:main
```

Administrator API equivalents are also available:

```text
POST /v1/onboarding/validate
POST /v1/onboarding/package
```

Both require `TALK2DATA_ADMIN`.

## Current capabilities

- FastAPI service with versioned HTTP contracts.
- Local Ollama structured-output interpretation with deterministic fallback.
- Telecom Tenant Domain Pack with governed vocabulary, metrics, dimensions, aliases, exclusions, and approved external adjacencies.
- Question admissibility for domain fit, ambiguity, analytical validity, authorization, source readiness, and external-context eligibility.
- RBAC/ABAC-ready access context and classification checks.
- Versioned metric definitions and deterministic Business Query IR.
- Runtime connector registry.
- Parameterized, read-only synthetic SQLite connector.
- Parameterized, read-only PostgreSQL connector.
- Versioned tenant semantic-to-physical mappings.
- Environment-only secret references.
- Connector catalog, freshness, health, mapping, and readiness APIs.
- Source coverage, row limit, timeout, policy-scope, result-sense, and claim-verification controls.
- Deterministic semantic, plan, SQL, result, and mapping hashes.
- Receipt-backed certified numerical claims.
- Durable session history with tenant and user isolation.
- Deterministic downloadable tenant runtime packages.
- GitHub Pages, Codespaces, Actions, CodeQL, Docker, and GHCR contracts.
- Hermes Agent gateway boundary for later bounded investigations.

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
    └── Ollama interpretation
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
Versioned physical mapping
    │
    ▼
Governed connector registry
    ├── synthetic SQLite
    └── PostgreSQL
    │
    ▼
Read-only parameterized execution
    │
    ▼
Source and result verification
    │
    ▼
Certified claims and query receipt
```

The model cannot create a metric definition, authorize access, receive source credentials, generate executable SQL, calculate a certified result, or introduce unsupported numeric claims.

## Run locally with synthetic data

```bash
ollama pull qwen3:8b
ollama serve

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
uvicorn talk2data.main:app --reload
```

Open `http://127.0.0.1:8000/demo`.

Docker alternative:

```bash
T2D_OLLAMA_MODEL=qwen3:0.6b docker compose up --build
```

## Run the PostgreSQL reference profile

```bash
T2D_OLLAMA_MODEL=qwen3:0.6b \
  docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build
```

The profile starts PostgreSQL 16, creates the governed reference schema, seeds employer-neutral telecom facts, and switches the runtime to PostgreSQL.

For a real tenant, use the Data Source builder or supply approved external directories:

```text
T2D_DATA_BACKEND=postgresql
T2D_DOMAIN_PACK_DIRECTORY=/config/domain-packs
T2D_PHYSICAL_MAPPING_DIRECTORY=/config/physical-mappings
T2D_POSTGRES_DSN=<resolved locally from a secret>
```

The physical mapping defines schemas, views, columns, metric discriminator values, dimensions, scope-value mappings, limits, and the `env://...` secret reference. Never commit the DSN.

## Connector and mapping APIs

```text
POST /v1/connectors/list
POST /v1/connectors/catalog
POST /v1/connectors/freshness
POST /v1/connectors/test
POST /v1/physical-mappings/list
POST /v1/physical-mappings/connector
```

Connection tests and mapping administration require `TALK2DATA_ADMIN`. No endpoint returns a secret value.

## Accuracy behavior

Talk2Data abstains rather than guessing when:

- the question does not belong to the tenant domain;
- a metric or dimension is ambiguous;
- the user lacks permission;
- the source is unavailable or does not cover the requested period;
- a requested analytical operation violates the metric contract;
- physical mappings conflict with semantic definitions;
- results contain invalid, duplicate, non-finite, or out-of-range values;
- causal or organizational context has not been supplied by the Unified AI Brain integration.

## Quality checks

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=talk2data --cov-report=term-missing
python scripts/validate_pages_site.py
```

Dedicated workflows test a real PostgreSQL service, the full Docker/Ollama path, the public Pages application, and the runtime container image.

## Documentation

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/semantic-registry.md`](docs/semantic-registry.md)
- [`docs/POSTGRESQL_CONNECTOR.md`](docs/POSTGRESQL_CONNECTOR.md)
- [`docs/PHYSICAL_MAPPINGS.md`](docs/PHYSICAL_MAPPINGS.md)
- [`docs/DATA_SOURCE_ONBOARDING.md`](docs/DATA_SOURCE_ONBOARDING.md)
- [`docs/GITHUB_RUNTIME.md`](docs/GITHUB_RUNTIME.md)
- [`docs/roadmap.md`](docs/roadmap.md)

## Repository safety

This repository is public. Commit only synthetic examples and configuration templates. Never commit credentials, internal database names, proprietary schemas, production Domain Packs, private Obsidian content, customer data, employee data, or organizational memory.
