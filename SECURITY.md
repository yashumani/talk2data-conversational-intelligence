# Security Policy

## Reporting a vulnerability

Do not open a public issue for suspected vulnerabilities, exposed credentials, cross-tenant leakage,
authorization bypasses, prompt-injection paths, or data-loss risks. Use GitHub's private
**Report a vulnerability** flow; private vulnerability reporting is enabled for this repository.
Include reproducible evidence without real customer or employee data.

Do not send secrets in the initial report. State the affected version, impact, and a safe synthetic
reproduction. Maintainers will acknowledge reports on a best-effort basis; the alpha has no formal
response SLA. Coordinated disclosure timing is agreed privately after triage.

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

GitHub Pages is a static synthetic visualization gallery and must not call a data API or model
provider. Any public synthetic API deployment is a separate operator decision and must enforce
exact origins, bounded request and response sizes, total deadlines, per-instance rate/concurrency
limits, status-only readiness, packaged demo authority, and disabled external models. Distributed
ingress protection, privacy, budgets, and real-provider cancellation remain deployment-owner gates.
