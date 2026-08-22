# ADR 0002: Use Ollama for local inference and Hermes for bounded workflows

- Status: Accepted
- Date: 2026-08-17

## Context

Talk2Data requires local model inference, structured question interpretation, cross-session agent workflows, and strict policy controls.

## Decision

Use Ollama as the local LLM inference server. Use Ollama structured output for the question parser at temperature zero. Use Hermes Agent through its authenticated local API server for later bounded multi-agent investigations.

Ollama and Hermes are not sources of truth. Model output is untrusted and validated against deterministic contracts.

## Consequences

- Development can run without cloud-model credentials.
- The model can be replaced without changing the semantic and policy architecture.
- Hermes receives only approved Talk2Data tools and evidence.
- Production memory and skill promotion require explicit controls and evaluation.
