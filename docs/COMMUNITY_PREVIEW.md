# Community preview

Talk2Data `0.7.0-alpha.2` is designed for public inspection and contribution, not unrestricted
production data processing.

## What visitors can use

- A polished visualization studio with 25 accepted synthetic renderers, search, and purpose-based
  filtering.
- A finite contributor backlog of 51 additional product types across six batches, documented in
  the implementation matrix rather than exposed in the end-user interface.
- A Codespaces/local CSV demonstration that is isolated from private BigQuery configuration.
- Contributor documentation, issue forms, governance, support, DCO, licensing, and security
  reporting guidance.

## What is intentionally unavailable

- GitHub Pages does not call a Talk2Data API or model provider.
- No API key belongs in HTML, browser JavaScript, Pages variables, or client storage.
- The repository does not contain employer data, private schemas, production source names, or
  cloud credentials.
- Private BigQuery/Parquet and shared PostgreSQL paths require operator-controlled identities and
  are not activated by the gallery.
- The alpha has no uptime, support, compatibility, or data-recovery SLA.

## Safe evaluation

Use only the bundled synthetic data. Run the CSV profile separately from internal profiles and
keep all ports private unless an operator has configured authentication, exact origins, ingress
limits, privacy controls, and a deployment-specific threat review.

The current release decision is recorded in
[the public alpha checklist](PUBLIC_ALPHA_RELEASE_CHECKLIST.md). If any mandatory owner or hosted
gate is open, the candidate remains a no-go even when local tests pass.
