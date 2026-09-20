# Governance

Talk2Data uses maintainer-led governance during the community alpha.

## Roles

- **Release owner:** decides whether a candidate may be tagged or deployed and owns the release
  evidence record.
- **Maintainers:** triage issues, review code, enforce boundaries, and approve roadmap changes.
- **CODEOWNERS:** review changes to security, runtime, workflow, contract, and release surfaces.
- **Contributors:** propose focused changes under the Apache-2.0 license and DCO.

## Decisions

Routine decisions are made in public issues and pull requests. Material changes to security,
governance, licensing, public runtime exposure, data-source boundaries, or the visualization
taxonomy require maintainer approval and a written rationale. Maintainers should prefer reversible,
evidence-backed decisions and record dissent when consensus is unavailable.

## Releases

Only the release owner may declare a release. A version file, merged pull request, passing local
tests, or deployed preview is not sufficient. Every mandatory item in
[the public alpha release checklist](docs/PUBLIC_ALPHA_RELEASE_CHECKLIST.md) must be satisfied for
the exact candidate SHA.

## Changes to governance

Governance changes use a pull request, CODEOWNERS review, and a seven-day public comment window
unless an urgent security correction requires faster action.
