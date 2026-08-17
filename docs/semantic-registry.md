# Semantic Registry and Business Query IR

## Purpose

Talk2Data must produce the same data meaning regardless of whether a request originates from chat, a dashboard, a scheduled investigation, or a future Hermes workflow. Natural-language interpretation therefore stops at a proposed business intent. The semantic registry and compiler—not the language model—decide the governed metric contract that may proceed toward execution.

## Metric contract

Each tenant metric records:

- stable metric ID and display name;
- business definition and semantic version;
- value type, aggregation, additivity, unit, and optional valid bounds;
- valid dimensions;
- supported and default time grain;
- default time window and comparison;
- data classification;
- governed source connector and source readiness.

A ratio such as `POSTPAID_CHURN` is explicitly non-additive. A sum such as `MOBILE_ACTIVATIONS` is additive. These properties travel with the compiled plan and are available to later query and result validators.

## Tenant-level semantics

The Domain Pack also owns:

- business domains and entities;
- governed dimension values and aliases;
- fiscal calendar identity;
- reporting currency;
- business timezone;
- source readiness;
- approved external adjacencies;
- explicit out-of-domain exclusions.

All IDs and cross-references are validated when the Domain Pack loads. Unknown metric dimensions, duplicate IDs, invalid ratio additivity, and broken external anchors stop application startup rather than becoming runtime ambiguity.

## Compilation sequence

```text
Natural-language question
        │
        ▼
Question admissibility decision
        │
        ├── not eligible → clarify / deny / reject / no source
        │
        ▼
Authorized semantic resolution
        │
        ├── metric version and classification
        ├── valid dimensions
        ├── source readiness
        └── semantic snapshot hash
        │
        ▼
Deterministic compiler
        ├── governed dimension-value filters
        ├── symbolic time window
        ├── comparison
        ├── access scope
        ├── connector ID
        └── canonical plan hash
        │
        ▼
Business Query IR
```

## Symbolic time windows

Talk2Data currently preserves tenant time logic symbolically instead of assuming Gregorian boundaries inside the chatbot. Examples include:

- `PREVIOUS_COMPLETE_DAY`;
- `PREVIOUS_COMPLETE_WEEK`;
- `PREVIOUS_COMPLETE_MONTH`;
- `PREVIOUS_COMPLETE_QUARTER`;
- `PREVIOUS_COMPLETE_YEAR`;
- rolling 30-day and 12-month windows;
- explicit closed ISO date ranges.

The IR records the tenant calendar, timezone, anchor date, and requested grain. The future connector/calendar layer will resolve exact boundaries and issue a query receipt. This prevents the chat layer from silently calculating fiscal periods with the wrong calendar.

## Access scope

The IR contains the authorized context that must be enforced again at execution:

- tenant and user;
- roles;
- departments;
- regions;
- business units;
- permitted actions;
- classification clearance.

The compiler does not convert those attributes directly into SQL predicates. It marks connector policy pushdown as required. Each source adapter must apply the policy using its governed resource mapping and must return the resulting policy decision in the query receipt.

## Integrity hashes

### Semantic snapshot hash

The semantic snapshot hash covers the tenant, Domain Pack version, calendar, currency, timezone, and complete metric contract. Any semantic change produces a different hash.

### Canonical plan hash

The plan hash covers the semantic snapshot, metric, dimensions, filters, time window, comparison, connector, access scope, and external-context requirement. The original wording is intentionally excluded. Semantically equivalent questions therefore produce the same plan hash under the same governed context.

The plan hash is not a database result hash. A later execution receipt will include the final source-specific query, source snapshot, policy decision, freshness, quality status, and result hash.

## Trust boundary

Ollama can help resolve language into candidate governed IDs. The compiler accepts only IDs that have already passed the admissibility and semantic checks. It does not ask Ollama to generate SQL, choose arbitrary tables, change metric formulas, or loosen authorization.

Hermes will later orchestrate multi-step investigations over approved tools. It will receive Business Query IR and evidence receipts, not unrestricted database credentials or a free-form SQL tool.
