# Changelog

All notable changes are documented here. Talk2Data follows Semantic Versioning; alpha releases
are evaluation candidates and do not imply a hosted production service.

## 0.7.0-alpha.2 — visualization studio

### Added

- Ten independently authored Batch 2 renderers for distribution, correlation, relationship, and
  ranking use cases, bringing the tested visualization library to 25 product types.
- End-user search and analytical-purpose filtering across the available visualization library.
- Plain-language selection guidance and chart-specific descriptions based on the question each
  visual form is best suited to answer.

### Changed

- Replaced the contributor-facing implementation tracker with a polished visualization studio
  that displays only usable chart experiences.
- Moved batch status, delivery counts, and the finite backlog out of the public interface and into
  contributor documentation and the machine-readable registry.
- Updated Python, web, preview, registry, and release metadata to `0.7.0-alpha.2` / `0.7.0a2`.

## 0.7.0-alpha.1 — community alpha candidate

### Added

- Apache-2.0 licensing, DCO contribution policy, governance, support, security, issue forms, and
  ownership rules for public collaboration.
- A finite, source-linked visualization inventory: 44 normalized Holtzy gallery targets mapped to
  76 product chart types in eight batches.
- Fifteen tested Batch 1 renderers using deterministic synthetic data and a dedicated static Pages
  gallery that contains no API client, credentials, browser storage, or runtime connection.
- A localhost-only AI Studio preview showing how a browser may call a model through a bounded
  server without placing API keys in HTML or client JavaScript.
- Public-runtime admission controls, response limits, deadline enforcement, exact-origin checks,
  and status-only readiness output for the synthetic public profile.
- Supply-chain gates for immutable actions, dependency review, CodeQL, secret scanning, container
  scanning, SBOM generation, provenance attestation, and exact-SHA release receipts.

### Changed

- Python package and web workspace versions are `0.7.0a1` and `0.7.0-alpha.1` respectively.
- The normal API is disabled by default until an operator explicitly selects a trusted profile.
- GitHub Pages is a static gallery only; it no longer accepts a configurable public API endpoint.

### Removed

- Self-mutating one-time workflows and automatic external publishing from the candidate tree.
