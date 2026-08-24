# Governed PostgreSQL reference connector

Talk2Data can execute the same governed Business Query IR through either the bundled synthetic
SQLite adapter or a read-only PostgreSQL source. The PostgreSQL adapter is a reference contract for
enterprise SQL platforms; it is not an unrestricted natural-language-to-SQL endpoint.

## Start the local PostgreSQL profile

```bash
T2D_OLLAMA_MODEL=qwen3:0.6b \
  docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build
```

The override starts PostgreSQL 16, creates the reference schema, seeds employer-neutral telecom
facts, and switches the Talk2Data API to `T2D_DATA_BACKEND=postgresql`.

Open:

```text
Chat:      http://127.0.0.1:8000/demo
API docs:  http://127.0.0.1:8000/docs
Readiness: http://127.0.0.1:8000/health/ready
```

## Configuration

```text
T2D_DATA_BACKEND=postgresql
T2D_POSTGRES_DSN=postgresql://user:password@host:5432/database
T2D_POSTGRES_SCHEMA=talk2data
T2D_POSTGRES_TABLE=metric_facts
T2D_POSTGRES_MAXIMUM_ROWS=1000
T2D_POSTGRES_QUERY_TIMEOUT_SECONDS=60
T2D_POSTGRES_CONNECT_TIMEOUT_SECONDS=10
```

The DSN is represented as a secret setting and is never returned by connector, health, catalog,
receipt, or chat APIs. In production, inject it through a secret manager or deployment environment;
do not commit it to a repository.

## Reference table contract

The configured table or governed view must expose these columns:

```text
fact_date
period_end
metric_id
amount
numerator
denominator
plan_id
market_id
region_id
channel_id
store_id
cell_site_id
hour_id
technology_id
```

Each row declares its certified period with `fact_date` and `period_end`. Additive metrics use
`amount`. Ratio metrics use `numerator` and `denominator`; Talk2Data computes
`SUM(numerator) / SUM(denominator)` and never sums pre-calculated percentages.

A production tenant can provide a governed view with this contract over its certified warehouse
objects. This keeps physical source schemas out of model context and lets source owners preserve
their own row-level security, masking, quality, and freshness controls.

## Security properties

The adapter enforces:

- simple allowlisted schema, table, column, metric, and dimension identifiers;
- bound parameters for dates, metric IDs, dimension values, access scope, and row limits;
- `REPEATABLE READ` plus `READ ONLY` for every execution transaction;
- PostgreSQL statement and lock timeouts;
- connector row limits;
- metric/dimension semantic validation before source access;
- tenant and action validation before execution;
- region scope pushdown when a governed regional scope is present;
- source coverage validation for both current and comparison periods;
- deterministic SQL and result hashes in each query receipt;
- cancellation through PostgreSQL's connection cancellation mechanism.

The language model never receives the DSN and never generates the executed SQL.

## Connector APIs

```text
POST /v1/connectors/list
POST /v1/connectors/catalog
POST /v1/connectors/freshness
POST /v1/connectors/test
```

Listing, catalog, and freshness calls require data-read permission. Connection testing requires the
`TALK2DATA_ADMIN` role. Responses expose governed connector state but never credentials.

## Validation

The dedicated GitHub Actions workflow starts a real PostgreSQL 16 service, creates an isolated
reference schema, executes a complete chat question through the PostgreSQL connector, verifies the
result and receipt, and validates the Docker Compose override.
