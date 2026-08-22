# Development Roadmap

## Stage 1 — Platform foundation and question admissibility

Status: implemented in draft PR #1; CI and CodeQL passed.

Delivered:

- FastAPI application scaffold
- Tenant Domain Pack
- Ollama structured interpretation
- deterministic domain and semantic validation
- policy and classification harness
- admissibility decisions and receipts
- durable session history
- Hermes API adapter
- connector, memory, and evidence contracts
- tests and CI

Acceptance outcome: Talk2Data can classify a question as accepted, clarified, unavailable, out of domain, analytically invalid, denied, conflicting, or source-not-ready before touching enterprise data.

## Stage 2 — Business Query IR and semantic registry

Status: implemented in stacked draft PR #2; validation in progress.

Delivered:

- canonical metric, entity, dimension, time, comparison, and filter contracts
- versioned metric semantics, aggregation, additivity, units, and valid ranges
- tenant fiscal-calendar, timezone, and currency references
- governed dimension values and aliases
- authorized semantic metric-resolution API
- deterministic Business Query IR compiler
- semantic snapshot and canonical plan hashes
- invalid dimension, unavailable source, time-grain, and multi-metric controls
- audit lineage from every compiled IR to its originating session and admissibility decision
- classification revalidation for grouping dimensions and detected filter dimensions
- controlled rejection of invalid explicit calendar dates
- persisted query plans in tenant- and user-isolated sessions
- tests for stable plan compilation, semantic security, audit lineage, and filter authorization

Acceptance outcome: every accepted single-metric internal data question can compile into a deterministic, testable Business Query IR without executing a source.

## Stage 3 — Universal data connector gateway

Next priority:

- Connector registry implementation
- PostgreSQL reference adapter
- source-specific semantic mapping
- parameterized read-only query compilation
- source catalog, freshness, and quality APIs
- row limits, timeouts, cancellation, and cost controls
- policy pushdown and field/row enforcement
- deterministic query receipts and result hashes
- secrets-manager integration boundary
- BigQuery, SQL Server, Teradata, Snowflake, Databricks, REST, and custom adapters

Acceptance outcome: an approved Business Query IR can execute through a governed adapter and return a reproducible receipt.

## Stage 4 — Certified answer and result-sense engine

- Query receipts and source snapshots
- data-quality gates
- aggregation and denominator checks
- join-cardinality validation
- plausibility rules
- claim compiler
- numerical answer verifier
- abstention paths

Acceptance outcome: every internal number shown to a user is receipt-backed and verified.

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

Acceptance outcome: cross-session context can be retrieved securely without relying on one vector index or stale chat summaries.

## Stage 6 — Unified AI Brain integration

- versioned client and authentication
- Domain Pack synchronization
- authorized knowledge retrieval
- entity and metric timelines
- prior investigations
- coverage and ingestion watermarks

Acceptance outcome: Talk2Data can connect certified data changes to approved internal business context.

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

Acceptance outcome: complex questions run as auditable workflows exchanging typed artifacts, not unrestricted agent chat.

## Stage 8 — External intelligence

- governed external-source registry
- sanitized research gateway
- trust and corroboration rules
- source snapshots
- entity and temporal alignment
- internal/external evidence separation

Acceptance outcome: external evidence can expand explanations while the product remains anchored to the tenant's business domain.

## Stage 9 — Conversational product experience

- responsive chat interface
- session and investigation navigation
- visible source/freshness receipts
- expandable evidence
- role-aware presentation personas
- clarification and abstention UX
- saved investigations

Acceptance outcome: users receive one coherent answer with visible trust boundaries and reusable investigation history.

## Stage 10 — Production hardening

- enterprise identity and SSO
- policy-service extraction where required
- audit export
- DLP and prompt-injection controls
- tenant-isolation tests
- load, latency, and failure testing
- model evaluations and change gates
- backup, restore, and incident procedures
- deployment and observability

Acceptance outcome: the platform is ready for controlled enterprise use.
