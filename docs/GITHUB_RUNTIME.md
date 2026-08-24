# GitHub-native Talk2Data runtime

Talk2Data uses GitHub for the control center, source of truth, complete evaluation runtime, testing,
and packaging.

## Launch

Open the deployed control center:

```text
https://yashumani.github.io/talk2data-conversational-intelligence/
```

Then select **Run Talk2Data now**, or open the Codespaces link directly:

```text
https://codespaces.new/yashumani/talk2data-conversational-intelligence?ref=main&quickstart=1
```

GitHub creates or resumes a Codespace from the permanent `main` runtime.

## What starts automatically

The dev container executes this sequence:

```text
Codespace
  -> Docker-in-Docker runtime
  -> Ollama service
  -> qwen3:0.6b model pull
  -> Talk2Data FastAPI service
  -> synthetic telecom SQLite data
  -> question admissibility
  -> governed Business Query IR
  -> parameterized query execution
  -> result-sense verification
  -> certified claims and query receipt
```

Port `8000` is forwarded privately and opens in the browser when the application becomes ready.

The working routes include:

```text
GET  /demo
GET  /docs
GET  /health/ready
POST /v1/connectors/list
POST /v1/connectors/catalog
POST /v1/connectors/freshness
POST /v1/connectors/test
POST /v1/chat/demo
POST /v1/questions/evaluate
POST /v1/query-plans/compile
POST /v1/semantics/metrics/resolve
```

## First startup

The first startup downloads Docker images and the compact local model, so it can take several
minutes. Follow the startup log inside the Codespace:

```bash
tail -f .talk2data/codespaces-startup.log
```

Check the stack:

```bash
docker compose \
  -f docker-compose.yml \
  -f .devcontainer/docker-compose.codespaces.yml \
  ps
```

Restart the full stack:

```bash
bash .devcontainer/start.sh
```

## PostgreSQL execution profile

The default Codespaces profile uses the synthetic SQLite connector to keep startup small. The same
runtime can execute through the PostgreSQL reference adapter:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.postgres.yml \
  up -d --build
```

See [`POSTGRESQL_CONNECTOR.md`](POSTGRESQL_CONNECTOR.md).

## Runtime boundary

GitHub Pages is the durable public control center. GitHub Codespaces is the complete isolated
evaluation and development environment. A Codespace can stop after inactivity, so it is not the
permanent production server.

The same governed Docker stack can later run continuously on:

- a developer workstation;
- an on-premises Linux server;
- an enterprise VM;
- a Kubernetes platform;
- a private cloud account.

GitHub Actions certifies the Docker/Ollama pipeline and the real PostgreSQL connector path before a
change is promoted.

## Current public-data boundary

The repository contains only synthetic, employer-neutral telecom data. Do not add production
credentials, private schemas, customer data, employee data, internal Domain Packs, or proprietary
organizational memory to this public repository.

The Unified AI Brain integration remains a separate service boundary and is not required for the
current data-execution path.
