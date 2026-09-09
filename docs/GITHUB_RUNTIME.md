# GitHub-native Talk2Data workspace

Talk2Data uses GitHub for its public product showcase, source of truth, isolated evaluation
workspace, automated tests and package evidence.

## Launch

Open the public showcase and select **Run the CSV workspace**:

```text
https://yashumani.github.io/talk2data-conversational-intelligence/
```

Or open the exact `main` branch directly:

```text
https://codespaces.new/yashumani/talk2data-conversational-intelligence?ref=main&quickstart=1
```

## Default Codespaces profile

The default Codespace intentionally starts the smallest working product:

```text
Codespace
  -> Docker-in-Docker
  -> isolated CSV Compose profile
  -> FastAPI service and durable demo state
  -> React CSV workspace
  -> business-definition governance
  -> bounded conversation and agent progress
  -> deterministic query and result verification
  -> evidence table, definitions and receipt
```

No GCP project, database credential, Claude key, Ollama process or model download is required.
Port `8000` is forwarded privately and opens `/workspace/` when readiness passes.

Follow startup inside the Codespace:

```bash
tail -f .talk2data/codespaces-startup.log
```

Inspect the stack:

```bash
docker compose \
  -f docker-compose.csv-demo.yml \
  -f .devcontainer/docker-compose.codespaces.yml \
  ps
```

Restart it with `bash .devcontainer/start.sh`. The primary routes are:

```text
GET    /workspace/
GET    /docs
GET    /health/ready
POST   /v1/demo/csv/sessions
POST   /v1/demo/csv/upload
POST   /v1/demo/csv/conversations
POST   /v1/demo/csv/runs
GET    /v1/demo/csv/runs/{run_id}
GET    /v1/demo/csv/runs/{run_id}/events
DELETE /v1/demo/csv/sessions/current
```

Use only the checked-in synthetic sample or explicitly approved demonstration data. The strict
CSV contract and acceptance sequence are in [`CSV_WORKSPACE.md`](CSV_WORKSPACE.md).

## Optional reference Ollama/PostgreSQL profile

The older `/demo` reference application and local Ollama pipeline remain available, but they are
not the Codespaces default and are not prerequisites for CSV, direct BigQuery or Parquet use:

```bash
T2D_OLLAMA_MODEL=qwen3:0.6b docker compose up -d --build
```

The PostgreSQL reference data connector can be added with `docker-compose.postgres.yml`; see
[`POSTGRESQL_CONNECTOR.md`](POSTGRESQL_CONNECTOR.md). A separate live-Ollama workflow retains the
real local-model regression.

## Enterprise profiles

Codespaces is an evaluation environment, not an always-on server. Direct BigQuery and Parquet
activation use private runtime configuration and organizational identity outside the public repo;
see [`BIGQUERY_PARQUET_RUNTIME.md`](BIGQUERY_PARQUET_RUNTIME.md). Cloud Run and Cloud SQL are an
optional scale-out profile described in [`SHARED_INTERNAL_RUNTIME.md`](SHARED_INTERNAL_RUNTIME.md).

## Public-data boundary

The repository contains synthetic, employer-neutral telecom data only. Never add production
credentials, private schemas, customer or employee data, internal Domain Packs, entitlements,
acceptance output or proprietary organizational memory to this public repository.
