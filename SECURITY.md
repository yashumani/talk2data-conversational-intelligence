# Security Policy

## Reporting a vulnerability

Do not open a public issue for suspected vulnerabilities, exposed credentials, cross-tenant leakage, authorization bypasses, prompt-injection paths, or data-loss risks. Contact the repository owner privately and include reproducible evidence without real customer or employee data.

## Security boundaries

- Language-model output is untrusted input.
- Authorization is enforced by deterministic policy services, never by prompts.
- Model-proposed metric and entity identifiers are validated against a versioned Tenant Domain Pack.
- Data connectors are read-only by default and must not expose credentials to the model or Hermes runtime.
- Session retrieval is tenant- and user-scoped.
- External research must be sanitized before leaving the internal boundary.
- Production Hermes memory and skill writes require approval and evaluation.

## Public repository restrictions

Never commit real credentials, connection strings, production source names, customer data, employee data, proprietary schemas, internal URLs, or private knowledge-vault content.
