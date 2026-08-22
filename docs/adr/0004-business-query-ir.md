# ADR 0004: Compile accepted data questions into Business Query IR

- Status: Accepted
- Date: 2026-08-17

## Context

Direct natural-language-to-SQL generation would allow model output to choose business definitions, joins, filters, and time logic. It would also make equivalent questions difficult to reconcile and would couple the chat experience to individual database dialects.

## Decision

Talk2Data will compile an admissible data question into a typed, source-neutral Business Query IR before any connector executes. The IR references a versioned metric contract and records dimensions, governed filters, symbolic time logic, comparison, connector identity, authorization scope, semantic snapshot hash, and canonical plan hash.

The local Ollama model may propose an interpretation, but the deterministic admissibility engine, policy layer, semantic registry, and compiler control the accepted plan.

## Consequences

- Equivalent questions can reconcile through a stable plan hash.
- Dashboard, chat, and future agent workflows can share one metric contract.
- Database dialect and physical schema remain behind connector adapters.
- Metric or Domain Pack changes are visible through semantic-version and snapshot-hash changes.
- Invalid metric/dimension combinations are rejected before execution.
- Fiscal periods remain symbolic until a governed calendar service resolves exact boundaries.
- Multi-metric investigations require an explicit higher-level workflow rather than an implicit SQL query.
