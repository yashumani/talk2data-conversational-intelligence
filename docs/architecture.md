# Talk2Data Target Architecture

## Product boundary

Talk2Data is the conversational control plane. It does not replace the semantic warehouse, Unified AI Brain, anomaly service, or source systems. It coordinates them through governed contracts.

The platform is designed as a **closed-domain, open-evidence system**:

- Every accepted question must map to an approved internal business anchor.
- Supporting evidence may come from authorized internal knowledge or approved external sources.
- Language models may interpret and reason, but they do not authorize access or create certified data facts.

## Correctness gates

```text
Question correctness
    Does the request belong to the business, make analytical sense, and pass policy?

Result correctness
    Is the source fresh, the query reproducible, the aggregation valid, and the result plausible?

Response correctness
    Is every factual claim supported, authorized, accurately worded, and traceable?
```

This initial slice implements the first gate.

## Logical layers

```text
Experience tier
  Web chat, mobile, embedded BI, Teams/Slack adapters

Access and policy tier
  Authentication, tenant resolution, RBAC, ABAC, relationship policy,
  classification, DLP, rate limits, and audit context

Question control tier
  Question admissibility, Tenant Domain Pack, semantic resolution,
  analytical type checking, ambiguity handling, Business Query IR

Orchestration tier
  Bounded Hermes workflows, tool routing, step/cost/time limits,
  human approval gates, retry and stop policies

Evidence tier
  Query receipts, source snapshots, memory evidence, external evidence,
  approved claim compiler, contradiction tracking

Data tier
  Semantic service, deterministic query compiler, connector gateway,
  quality and freshness gates, result-sense validation

Memory tier
  Session episodes, investigations, temporal business graph,
  Obsidian governance, hybrid retrieval, Context Coverage Receipts

External intelligence tier
  Governed feeds, sanitized live research, source trust,
  corroboration, entity resolution, temporal alignment

Verification tier
  Numerical reconciliation, claim/evidence matching, policy recheck,
  output DLP, unsupported-claim rejection

Operations tier
  Audit, observability, evaluations, cost controls, retention,
  model/prompt/skill versions, security scanning
```

## Runtime request flow

```text
User request
    ↓
Authenticated AccessContext
    ↓
Question Admissibility Engine
    ├── deterministic domain matching
    ├── local Ollama structured interpretation
    ├── policy and classification checks
    ├── analytic operation validation
    └── source-availability check
    ↓
QuestionDecision receipt
    ↓
Business Query IR / memory retrieval plan / rejection path
    ↓
Hermes bounded workflow
    ↓
Governed tools only
    ├── semantic data MCP
    ├── Unified AI Brain MCP/API
    ├── external intelligence gateway
    └── anomaly API (later)
    ↓
Evidence ledger and approved claims
    ↓
Verifier
    ↓
User-facing response and audit receipt
```

## LLM and agent boundary

### Ollama

Ollama is the local inference service. In the first slice, it proposes a structured interpretation of a question. The proposal is untrusted and cannot introduce metric, entity, dimension, or domain identifiers absent from the Tenant Domain Pack.

Development defaults to `qwen3:8b`, but the model is configuration, not architecture. Model changes must run the evaluation suite.

### Hermes Agent

Hermes is the bounded workflow runtime for multi-step investigations. It is accessed through its authenticated local API server. It will receive only a small Talk2Data-owned tool surface and typed artifacts.

Hermes must not:

- connect directly to production databases,
- hold database credentials,
- make authorization decisions,
- turn its built-in memory into organizational truth,
- autonomously promote production skills or memory,
- generate certified data claims without receipts.

## Tenant Domain Pack

The Domain Pack is the business type system. It is versioned and tenant-specific. It contains:

- industry and business domains,
- metrics and governed aliases,
- entities and dimensions,
- classifications,
- source availability,
- approved external adjacencies,
- explicit exclusions,
- default calendar, currency, and terminology.

Every decision records the Domain Pack version used.

## Memory evolution

### L0: active working context

Current-turn selections and references. Short-lived.

### L1: immutable episodes

Messages, tool calls, query receipts, source snapshots, and policy decisions.

### L2: investigations

Question, plan, evidence, hypotheses, findings, recommendations, final response, and audit lineage.

### L3: temporal business graph

Versioned entities, decisions, facts, and relationships with effective dates and source provenance. Graphiti is the planned runtime graph adapter.

### L4: search indexes

Keyword, vector, temporal, metric, entity, and graph indexes derived from canonical episodes.

### L5: procedural memory

Approved Hermes skills and investigation procedures. Production changes require evaluation and promotion.

### L6: human governance

Obsidian-compatible Markdown for reviewable definitions, decisions, corrections, and approvals. Obsidian is an authoring surface, not the runtime authorization database.

### L7: audit ledger

Immutable access, version, evidence, and answer lineage.

## Universal data connector architecture

```text
Hermes Data Agent
    ↓ typed tool call
Talk2Data Data MCP/API
    ↓
Policy + Semantic + Query Gateway
    ↓
Connector Registry
    ├── BigQuery
    ├── Teradata
    ├── SQL Server
    ├── PostgreSQL / MySQL
    ├── Snowflake
    ├── Databricks
    ├── REST / GraphQL
    └── custom enterprise adapters
```

Every connector implements the same read-only contract:

- connection health,
- catalog discovery,
- schema introspection,
- plan validation,
- cost estimation,
- parameterized read-only execution,
- freshness and quality metadata,
- cancellation.

Credentials stay in the connector gateway and never enter the model context.

## Deployment evolution

The code begins as a modular monolith for operational simplicity. Logical boundaries are enforced through modules and typed contracts. Components may be extracted when scaling or isolation requires it:

- query execution workers,
- policy service,
- memory indexing workers,
- Graphiti adapter,
- external research gateway,
- evidence and audit service,
- asynchronous Hermes investigation workers.

## Non-negotiable invariants

1. No internal numeric claim without a reproducible query receipt.
2. No model-proposed identifier without Domain Pack validation.
3. No unauthorized content may enter model context.
4. No external claim may be silently represented as internal truth.
5. No stale data may be presented as current without visible coverage.
6. No historical definition may be overwritten without temporal lineage.
7. No persona may expand a user's permissions.
8. No free-form agent swarm may bypass the bounded workflow and typed-artifact contract.
