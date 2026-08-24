# Physical Mapping Hardening

This slice treats tenant semantic-to-physical mappings as governed runtime contracts.

The hardening gate requires:

- deterministic mapping and connector hashes regardless of input set ordering;
- JSON-safe public mapping views with sorted scope values;
- no secret-reference names or credentials in public APIs;
- region-scope enforcement only for metrics that actually support the REGION dimension;
- regression tests for connectors that intentionally do not map REGION;
- successful Ruff, strict Mypy, Pytest, PostgreSQL integration, CodeQL, and full-runtime checks.

The implementation remains read-only. Models propose semantic intent only; they never receive connection secrets, select physical identifiers, or author executed SQL.
