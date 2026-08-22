# Universal Data Connector Contract

Talk2Data connects to enterprise sources through a controlled connector gateway, never through unrestricted model-generated SQL.

## Required connector operations

- `test_connection`
- `discover_catalog`
- `introspect_schema`
- `validate_plan`
- `estimate_cost`
- `execute_read_only`
- `get_freshness`
- `cancel_query`

## Required controls

- Read-only credentials and transactions by default
- Parameterized filters
- Allowlisted projects, catalogs, schemas, views, and procedures
- Row and byte limits
- Query timeout and cancellation
- Cost estimation where supported
- Row-, column-, and classification-policy pushdown
- Result hashing and source snapshots
- Freshness and data-quality metadata
- No credentials in prompts, logs, sessions, or Hermes memory

## Planned adapters

1. PostgreSQL reference adapter
2. BigQuery
3. SQL Server
4. Teradata
5. Snowflake
6. Databricks SQL
7. MySQL
8. REST and GraphQL
9. Custom JDBC/ODBC-compatible enterprise systems through a gateway adapter

Connector availability does not automatically make a source queryable. A metric must also be registered in the semantic layer and authorized for the user.
