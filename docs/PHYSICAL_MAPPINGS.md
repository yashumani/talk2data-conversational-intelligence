# Tenant physical mappings

Talk2Data keeps business meaning separate from warehouse implementation.

The Tenant Domain Pack defines governed concepts such as `POSTPAID_CHURN`, `PLAN`, and `REGION`.
A Tenant Physical Mapping Pack binds those concepts to an approved database object and its physical
columns. The language model never sees or generates these physical identifiers.

## Runtime path

```text
Business question
  -> governed metric and dimensions
  -> Business Query IR
  -> approved physical mapping version
  -> parameterized read-only connector query
  -> result verification
  -> receipt with mapping version and SHA-256 hash
```

## Example

```yaml
tenant_id: demo-telecom
version: "2026.08.2"
status: APPROVED
effective_from: 2026-08-23T00:00:00Z
connectors:
  - connector_id: telecom_semantic_warehouse
    connector_type: POSTGRESQL
    schema_name: analytics
    table_name: customer_churn_monthly
    secret_ref: env://T2D_POSTGRES_DSN
    fact_date_column: reporting_month
    period_end_column: reporting_month_end
    metric_id_column: metric_code
    dimensions:
      PLAN: rate_plan_code
      REGION: sales_region_code
    scope_value_allowlists:
      REGION: [NORTHEAST, SOUTHEAST, CENTRAL, WEST]
    scope_value_mappings:
      REGION:
        NORTH_AMERICA: [NORTHEAST, SOUTHEAST, CENTRAL, WEST]
        NORTHEAST: [NORTHEAST]
    metrics:
      - metric_id: POSTPAID_CHURN
        source_value: POSTPAID_CHURN
        aggregation: RATIO
        numerator_column: disconnect_count
        denominator_column: average_subscriber_base
        allowed_dimensions: [PLAN, REGION]
```

## Accuracy rules

- Every available semantic metric must have an approved physical mapping.
- The semantic and physical aggregation must match.
- The physical mapping must cover every allowed semantic dimension.
- Ratio metrics require separate numerator and denominator columns.
- Sum metrics require an amount column.
- This slice rejects unsupported formulas instead of approximating them.
- Schema, table, and column names must be simple SQL identifiers.
- Mapping changes produce a new deterministic hash and should use a new version.
- Public mapping views and hashes canonicalize sets, dictionaries, dates, and enums before serialization.
- PostgreSQL receipts pin both the mapping version and mapping hash used for execution.

## Access-scope mapping

An authorization scope is not assumed to be identical to a database value. For example, an identity
provider may grant `NORTH_AMERICA`, while the database stores four operating regions.

`scope_value_mappings` explicitly expands the authorized value into approved physical values. An
unknown scope is rejected with `REGION_SCOPE_UNMAPPED`; it never becomes an unrestricted query.
A query filter must also remain inside the resolved physical scope.

## Secrets

Mapping files contain references only:

```yaml
secret_ref: env://T2D_POSTGRES_DSN
```

They cannot contain a DSN, password, or embedded credential. The current provider resolves `env://`
references at runtime. Errors are sanitized and do not reveal either the environment-variable name or
its value.

An explicit `T2D_POSTGRES_DSN` setting can override the mapped reference for local testing. Future
providers can implement the same resolver contract for GitHub Codespaces secrets, Docker secrets,
cloud secret managers, Vault, or Kubernetes.

## External tenant packs

Packaged synthetic mappings are used by default. A deployment can mount an approved directory and
set:

```text
T2D_PHYSICAL_MAPPING_DIRECTORY=/run/talk2data/physical-mappings
```

Only one approved pack may be active per tenant in the current runtime. The service validates the
pack against the tenant Domain Pack before any connector starts.

## Administration API

```text
POST /v1/physical-mappings/list
POST /v1/physical-mappings/connector
```

Both routes require `TALK2DATA_ADMIN`. Responses include approved physical metadata and mapping
hashes but omit `secret_ref` and the underlying secret name.

The readiness endpoint also reports the loaded mapping tenant and each connector's mapping identity:

```text
GET /health/ready
```
