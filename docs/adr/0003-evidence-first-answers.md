# ADR 0003: Evidence precedes reasoning and response generation

- Status: Accepted
- Date: 2026-08-17

## Context

Language models can produce fluent but unsupported statements. Enterprise data answers require reproducibility and security.

## Decision

No certified data statement may enter a final response unless it is linked to an authorized, quality-approved, reproducible evidence receipt. Agents reason over approved claims and typed evidence rather than unrestricted source rows.

## Consequences

- The system may abstain more frequently.
- Every answer can be reconstructed and audited.
- Facts, hypotheses, and recommendations are represented separately.
- Result and response verification become mandatory production stages.
