# ADR 0001: Begin as a modular monolith

- Status: Accepted
- Date: 2026-08-17

## Context

The target architecture contains policy, semantic, session, memory, evidence, connector, orchestration, and verification capabilities. Deploying each capability as a separate service immediately would create operational complexity before workload and isolation requirements are known.

## Decision

Build the Talk2Data control plane as a Python modular monolith with explicit module boundaries and versioned contracts. Existing Unified AI Brain and anomaly repositories remain independent systems accessed through APIs.

## Consequences

- Local development and integration testing remain simple.
- Contracts are available for later extraction.
- Direct cross-module database coupling is prohibited.
- Components will be extracted only when scale, security, or ownership requires it.
