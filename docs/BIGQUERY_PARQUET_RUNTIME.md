# BigQuery-first runtime without mandatory Cloud Run or Cloud SQL

## Decision

Talk2Data supports three independent operating profiles. Cloud Run and Cloud SQL are not
prerequisites for the internal product.

| Profile | Analytical source | Application state | Infrastructure requirement | Intended use |
| --- | --- | --- | --- | --- |
| Direct BigQuery | Approved BigQuery views queried for each question | Local SQLite or memory | Python host, organizational OIDC and BigQuery ADC | Small team, freshest results |
| Materialized Parquet | Hash-pinned local snapshot extracted from approved BigQuery views | Local SQLite or memory | Python host, local private disk; BigQuery access only during refresh | Read-mostly teams, demos with approved extracts, lower latency/cost |
| Managed scale-out | Direct BigQuery plus shared PostgreSQL | Cloud SQL PostgreSQL | Optional Cloud Run/IAP/Cloud SQL bundle | Multiple API/worker replicas and stronger managed durability |

CSV remains a fourth, isolated demonstration profile. It is not promoted into the internal
catalog and is not an automatic fallback for either BigQuery or Parquet.

## Why this boundary

A user who can run read-only BigQuery jobs should be able to activate the analytical product
without permission to provision Cloud Run, networks or Cloud SQL. The application-state choice
is independent of the analytical-source choice:

- `shared_state` omitted: use local SQLite paths (or memory for short-lived evaluation);
- `shared_state` present: use PostgreSQL and distributed workers;
- `analytics_mode: bigquery`: execute every governed plan against BigQuery;
- `analytics_mode: parquet`: execute against an operator-created local snapshot.

The same approved domain pack, physical mapping, signed identity, entitlement checks, metric
definitions and result certification apply to both internal analytical modes.

## Minimal direct-BigQuery activation

1. Install `.[internal]` and build the internal React workspace.
2. Copy `examples/internal/runtime.example.json` to a private absolute path.
3. Set `analytics_mode` to `bigquery`; keep `shared_state` absent.
4. Set absolute local `state_database_path` and `governance_database_path` values.
5. Configure the approved catalog, definitions and entitlements outside the repository.
6. Authenticate Application Default Credentials with a principal limited to BigQuery job
   creation and read access to the approved views.
7. Provide the organizational OIDC issuer/JWKS/audience and start `talk2data.internal_main`.

No Terraform apply, VPC, Cloud Run service or Cloud SQL instance is involved in this profile.
One process owns each SQLite file; do not horizontally scale it.

## Materialized-Parquet activation

Start from `examples/internal/runtime.parquet.example.json`. The `bigquery` block is consumed by
the refresh command; the running API ignores it when `analytics_mode` is `parquet`.

Refresh while ADC is available:

```bash
python -m talk2data.operations.materialize_snapshot \
  --config /private/talk2data/runtime.parquet.json
```

Then start the API normally:

```bash
export T2D_INTERNAL_CONFIG_FILE=/private/talk2data/runtime.parquet.json
uvicorn talk2data.internal_main:app --host 127.0.0.1 --port 8000
```

After refresh, BigQuery credentials may be removed from the API process. The API does not create
a Google client in Parquet mode. A scheduler may invoke the refresh command, but failed refreshes
never replace the last valid file.

## Snapshot contract

For each approved mapping, the refresh tool:

1. validates the approved BigQuery view schema;
2. creates a parameterized tenant-scoped `SELECT` only;
3. performs a dry run and rejects unknown references, locations or byte estimates;
4. enforces `maximum_bytes_billed` and `maximum_rows`;
5. writes Zstandard-compressed Parquet to a temporary file;
6. computes SHA-256 and writes a strict manifest;
7. atomically replaces the previous snapshot and manifest.

The API fails closed if the file is missing, stale, symlinked, modified, mapped to a different
catalog fingerprint, or has a row count different from the manifest. Runtime queries are
parameterized DuckDB reads with the same tenant, region, business-unit, classification, metric,
dimension, date, completeness and result-limit checks as direct BigQuery.

Every receipt uses `source_kind: parquet_snapshot`, includes the file fingerprint, and warns that
the result reflects a materialized snapshot. It never emits a BigQuery job receipt for a local
query.

## Security and governance constraints

- Store snapshots, manifests, SQLite databases, private catalogs and entitlement files on an
  access-controlled encrypted filesystem outside the repository.
- Treat Parquet as classified data at the highest classification present in the extracted view.
- Do not place snapshots in browser assets, Git, shared user folders or the CSV demo volume.
- Run refresh with a dedicated least-privilege principal when possible; the API itself should not
  retain BigQuery credentials in Parquet mode.
- Retain source job IDs and byte counts from manifests in operational evidence.
- Set `maximum_age_seconds` to the business freshness SLA; stale snapshots stop startup.
- A snapshot is a reproducible local artifact, not BigQuery time travel. Archive it only under an
  approved retention and encryption policy.

## When managed GCP services are justified

Adopt the optional `infra/gcp` bundle only when the product needs concurrent replicas, durable
distributed queues, centralized definition/grant state, managed backups, IAP ingress and formal
platform operations. Those are scaling and operations capabilities, not requirements for
BigQuery authorization or analytical correctness.
