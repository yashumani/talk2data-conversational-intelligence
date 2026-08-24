# Development Roadmap

## Stage 1 — Platform foundation and question admissibility

Status: complete on `main`.

Delivered:

- FastAPI application scaffold
- Tenant Domain Pack
- Ollama structured interpretation
- deterministic domain and semantic validation
- policy and classification harness
- admissibility decisions and receipts
- durable session history
- Hermes API adapter boundary
- connector, memory, and evidence contracts
- tests, CI, and CodeQL

Acceptance outcome: Talk2Data classifies a request before enterprise data or organizational memory
is accessed.

## Stage 2 — Business Query IR and semantic registry

Status: complete on `main`.

Delivered:

- versioned metric semantics, aggregation, additivity, units, ranges, and source references
- governed dimensions, values, aliases, calendars, currency, and timezone
- authorized semantic resolution
- deterministic Business Query IR
- semantic snapshot and canonical plan hashes
- session and admissibility-decision lineage
- dimension, filter, time, source, classification, and multi-metric controls

Acceptance outcome: every accepted single-metric request compiles into a deterministic source-neutral
plan.

## Stage 3 — Universal data connector gateway

Status: in progress.

Delivered:

- runtime connector registry
- parameterized read-only synthetic SQLite adapter
- governed PostgreSQL reference adapter
- connector descriptor, catalog, freshness, test, and readiness APIs
- identifier allowlists and parameter binding
- repeatable-read, read-only PostgreSQL transactions
- explicit certified source-period boundaries
- source coverage validation
- row limits, statement timeouts, lock timeouts, and cancellation
- policy scope pushdown
- deterministic SQL hashes, result hashes, and query receipts
- local PostgreSQL Docker profile
- real PostgreSQL GitHub Actions integration test

Next:

- tenant-configurable semantic-to-physical mappings
- PostgreSQL cost estimation policy
- secrets-manager provider interfaces
- BigQuery reference adapter
- SQL Server and Teradata adapters
- Snowflake, Databricks, REST, GraphQL, and custom gateway adapters

Acceptance outcome: an approved Business Query IR executes through a governed adapter and returns a
reproducible receipt.

## Stage 4 — Certified answer and result-sense engine

Status: initial implementation complete for the current metric contracts.

Delivered:

- query receipts and source snapshots
- source-coverage gates
- aggregation, finiteness, range, row-count, uniqueness, and comparison checks
- deterministic claim compiler
- verified numerical answers
- abstention paths

Next:

- denominator reconciliation
- join-cardinality controls for multi-table adapters
- configurable plausibility rules
- source-specific quality incident integration
- human-review escalation for failed certification

## Stage 5 — Secure memory fabric

- immutable episode store
- investigation store
- typed memory objects
- temporal validity and supersession
- hybrid indexes
- Graphiti adapter
- Obsidian-compatible governed ingestion
- Context Coverage Receipts
- contradiction detection
- retention and deletion policies

Acceptance outcome: cross-session context can be retrieved securely without relying on one vector
index or stale chat summaries.

## Stage 6 — Unified AI Brain integration

- versioned client and authentication
- Domain Pack synchronization
- authorized knowledge retrieval
- entity and metric timelines
- prior investigations
- coverage and ingestion watermarks

Acceptance outcome: Talk2Data connects certified data changes to approved internal business context.

## Stage 7 — Hermes bounded agent workflows

- Question Adjudicator
- Semantic Planner
- Data Agent
- Knowledge Agent
- External Context Agent
- Business Analyst
- Verifier
- Response Composer
- step, cost, timeout, retry, and approval controls

Acceptance outcome: complex questions run as auditable workflows exchanging typed artifacts, not
unrestricted agent chat.

## Stage 8 — External intelligence

- governed external-source registry
- sanitized research gateway
- trust and corroboration rules
- source snapshots
- entity and temporal alignment
- internal/external evidence separation

Acceptance outcome: external evidence expands explanations while the product remains anchored to the
tenant's business domain.

## Stage 9 — Conversational product experience

Status: executable GitHub-native control center and Codespaces runtime available.

Next:

- session and investigation navigation
- richer source and freshness presentation
- role-aware personas
- saved investigations
- guided tenant-project generation and installable runtime bundles

## Stage 10 — Production hardening

- enterprise identity and SSO
- policy-service extraction where required
- audit export
- DLP and prompt-injection controls
- tenant-isolation tests
- load, latency, and failure testing
- model evaluations and change gates
- backup, restore, and incident procedures
- container registry, releases, deployment, and observability

Acceptance outcome: the platform is ready for controlled enterprise use.
