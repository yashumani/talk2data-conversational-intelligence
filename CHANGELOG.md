# Changelog

All notable changes are documented here. Talk2Data follows Semantic Versioning; alpha releases
are evaluation candidates and do not imply a hosted production service.

## Unreleased

### Security

- Updated vite to 8.3.6, vitest and its coverage plugin to 5.1.0, and source-map-js to 1.2.2 to
  clear security advisories published after the alpha.2 release.
- Updated certifi to 2026.10.23, which removes root certificates found to be compromised.
- The runtime and internal images now apply Debian security updates at build time, which picks up
  the patched zlib.

### Fixed

- The GitHub CSV workspace check no longer fails on Ubuntu 26.04 runners, which do not pre-create
  a pip cache folder.
- The Hugging Face Space requirements can be installed again. They required huggingface_hub 1.x
  together with transformers 4.x, and every transformers 4.x release needs huggingface_hub below 1.0.
- The Hugging Face Space app starts again. It did not pass the `synthetic_data` argument that
  `DemoChatService` has required since PostgreSQL reference execution was added.

### Changed

- The Hugging Face Space and the live model smoke test now use transformers 5 (5.17.0 or later).
  The local model loader passes `dtype` instead of the deprecated `torch_dtype`.

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
