# Public alpha release checklist

**Current decision: GO for the scoped `0.7.0-alpha.2` community release.** The protected merge,
exact-SHA Pages deployment, browser acceptance, image publications, SBOMs, and signed provenance
all completed successfully. This release adds Batch 2 and replaces the public delivery tracker
with an end-user visualization studio. It does not approve an Internet-facing runtime, production
data, or a production SLA.

## Candidate identity

- Version: `0.7.0-alpha.2` (`0.7.0a2` for Python)
- Baseline: `a31848bf5262c03c4fe3bb5a9d2b293a01682e9b`
- Release source SHA: [`57a82ee98a3f1733a825881df5ee6296d7035e03`](https://github.com/yashumani/talk2data-conversational-intelligence/commit/57a82ee98a3f1733a825881df5ee6296d7035e03)
- Release pull request: [#57](https://github.com/yashumani/talk2data-conversational-intelligence/pull/57)
- Release: [`v0.7.0-alpha.2`](https://github.com/yashumani/talk2data-conversational-intelligence/releases/tag/v0.7.0-alpha.2), an explicitly marked prerelease targeting the source SHA above
- Release receipt: the deployed `release.json` records the exact release source SHA and version
  `0.7.0-alpha.2`

## Eight workstreams

| # | Workstream | Repository state | Recorded release evidence |
| ---: | --- | --- | --- |
| 1 | License, DCO, versioning | Implemented | Hosted DCO and exact-version validation required for the alpha.2 candidate |
| 2 | CI and supported runtimes | Implemented | Python 3.11–3.13, PostgreSQL, web, container, CodeQL, and security checks required on the candidate SHA |
| 3 | Community operations | Implemented | Solo-maintainer review policy, private vulnerability reporting, and confidential conduct intake recorded |
| 4 | Visualization scope | 44 targets, 76 product types, eight batches | 25 accepted types are product-visible; 51 backlog types remain contributor-only |
| 5 | Batches 1–2 | 25 accepted; 51 in contributor backlog | 135 web tests pass locally with greater than 97% statement, branch, function, and line coverage |
| 6 | Static Pages release | Network-disabled visualization studio | Exact-SHA deployment, receipt, artifact, search/filter, accessibility, responsive, and no-tracking-copy evidence required |
| 7 | Runtime/provider safety | Request/response bounds, deadlines, exact origins, status-only readiness | Public boundary remains source, synthetic CSV, and static Pages; no Internet-facing runtime is approved |
| 8 | Supply chain and repository protection | Pinned workflows, security gates, SBOM/provenance design | Both exact-SHA images carry BuildKit SBOM attestations and signed SLSA provenance; internal digest receipt retained |

## Mandatory hosted checks

- [x] The alpha.2 candidate branch exists remotely and its reviewable pull request is merged to `main`.
- [x] Every alpha.2 candidate commit has an author-matching DCO sign-off.
- [x] Python matrix passes on 3.11, 3.12, and 3.13 with the PostgreSQL state tests enabled.
- [x] Web tests, 96% line/branch threshold, all builds, and production/full npm audits pass.
- [x] Docker builds execute successfully for public and internal images.
- [x] CodeQL, dependency review, secret scanning, image vulnerability scan, SBOM, and provenance
      jobs complete. The blocking image scan has no fixable high/critical finding; every unfixed
      base-image high/critical SARIF finding has an explicit release-owner disposition.
- [x] Pages artifact is built from the alpha.2 release SHA, stamped once, deployed from `main`, and the
      public `release.json` matches the deployed SHA and version.

## Mandatory owner settings

- [x] Protect `main`; disallow force pushes and deletion.
- [x] Require pull requests, resolved conversations, a current branch, and the documented stable
      required-check names. Review approval is not required while the repository has one maintainer;
      enable independent CODEOWNERS review before adding another maintainer.

### Stable required-check names

Configure branch protection with these exact GitHub check names. Names are intentionally unique
across workflows so one workflow cannot satisfy another workflow's gate:

- `DCO sign-off`
- `Python quality (3.11)`, `Python quality (3.12)`, and `Python quality (3.13)`
- `Web test and build`
- `CodeQL analysis` and GitHub code scanning's `CodeQL`
- `Dependency review`, `Secret scan`, and `Container security`
- `Pages artifact`
- `CSV demo acceptance`
- `GitHub CSV workspace`
- `PostgreSQL integration`
- `Internal runtime package`
- `Runtime image validation` and `Internal image validation`
- [x] Enable private vulnerability reporting.
- [x] Protect publication environments and restrict deployment to approved branches/tags.
- [x] Disable all remote workflow registrations absent from the candidate tree, including legacy
      self-mutating and external-publishing workflows.
- [x] Record a confidential Code of Conduct intake channel, authorized responders, retention, and
      escalation path without publishing the maintainer's private account email.

### Owner-setting evidence (2026-09-19)

| Control | Recorded state |
| --- | --- |
| `main` branch rule | Classic protection rule `83423121`; pull request required; no approval requirement in documented solo-maintainer mode; branch must be current; conversations must be resolved; administrators cannot bypass |
| History protection | Force pushes and branch deletion disabled |
| Required checks | All 17 stable names listed above are configured as mandatory |
| Vulnerability intake | GitHub private vulnerability reporting enabled |
| Conduct intake | The same private GitHub form accepts titles prefixed `[CONDUCT]`; `@yashumani` is the sole responder; retention and external escalation are defined in `CODE_OF_CONDUCT.md` |
| Publication boundary | `github-pages` environment restricted to `main` |
| Obsolete automation | All 16 workflow registrations listed below disabled in GitHub Actions |

Disabled registrations: `runtime-image.yml`, `export-source.yml`,
`demo-final-certification.yml`, `finalize-demo-slice.yml`, `fix-onboarding-quality.yml`,
`format-physical-mappings.yml`, `harden-physical-mappings.yml`,
`format-business-query-ir-once.yml`, `harden-business-query-ir-once.yml`,
`harden-business-query-ir-retry.yml`, `format-onboarding-branch.yml`, `mypy-fix-once.yml`,
`fix-pages-ci-once.yml`, `format-once.yml`, `report-demo-certification.yml`, and
`publish-huggingface-space.yml`.

These settings close the repository-owner configuration gates for a solo-maintainer alpha. The
post-merge evidence below closes the hosted publication gates without waiving the documented
runtime boundary or accepted base-image risk.

## `0.7.0-alpha.2` exact-SHA release evidence (2026-09-20)

| Evidence | Verified result |
| --- | --- |
| Release source | Merge commit [`57a82ee98a3f1733a825881df5ee6296d7035e03`](https://github.com/yashumani/talk2data-conversational-intelligence/commit/57a82ee98a3f1733a825881df5ee6296d7035e03), from reviewed PR [#57](https://github.com/yashumani/talk2data-conversational-intelligence/pull/57) |
| Protected checks | All 26 PR check runs completed successfully or were intentionally skipped by their workflow conditions; all 17 required checks passed, including DCO, Python 3.11–3.13, web, CodeQL, dependency/security, Pages, CSV, PostgreSQL, package, and both image validators |
| Pages workflow | [Run 35490495618](https://github.com/yashumani/talk2data-conversational-intelligence/actions/runs/35490495618) succeeded for the release SHA, including both artifact and deployment jobs |
| Pages artifact | `github-pages`, artifact `10599181637`, SHA-256 `8edadad6181aba8a1c97fff59784b7155ae2728554efdfdceedee5f634741378` |
| Public receipt | The deployed artifact's `release.json` reports source SHA `57a82ee98a3f1733a825881df5ee6296d7035e03` and version `0.7.0-alpha.2` |
| Hosted studio review | `/workspace/` rendered 25 accessible named charts; `comparison` returned six charts; the Distribution purpose filter returned six charts and exposed selected state; the polite live count updated; no delivery batch/status/backlog copy or application console error was observed |
| Public image | `ghcr.io/yashumani/talk2data-conversational-intelligence:sha-57a82ee98a3f1733a825881df5ee6296d7035e03`, digest `sha256:5128bc283591ded9d2c6fc1398dd855fbc961643461622015cccfed057f20688` ([run 35490704520](https://github.com/yashumani/talk2data-conversational-intelligence/actions/runs/35490704520)) |
| Public SBOM/provenance | BuildKit generated and pushed the SBOM attestation; signed SLSA provenance [attestation 48718465](https://github.com/yashumani/talk2data-conversational-intelligence/attestations/48718465) binds the digest, workflow, `main`, and release SHA |
| Internal image | `ghcr.io/yashumani/talk2data-internal:sha-57a82ee98a3f1733a825881df5ee6296d7035e03`, digest `sha256:a8ff166c6eb324c6c4634000a28b0470f21f64e2d00c11282728fe3fb596665b` ([run 35490721034](https://github.com/yashumani/talk2data-conversational-intelligence/actions/runs/35490721034)) |
| Internal SBOM/provenance | BuildKit generated and pushed the SBOM attestation; signed SLSA provenance [attestation 48718449](https://github.com/yashumani/talk2data-conversational-intelligence/attestations/48718449) binds the digest, workflow, `main`, and release SHA |
| Internal receipt | Artifact `internal-image-receipt-57a82ee98a3f1733a825881df5ee6296d7035e03` (`10598677872`), artifact SHA-256 `311730729303ca71bbf3cdde4b71e080cf960728085b94f1b95f8696a550aedd` |
| Release | [`v0.7.0-alpha.2`](https://github.com/yashumani/talk2data-conversational-intelligence/releases/tag/v0.7.0-alpha.2) is an explicitly marked prerelease targeting the exact source SHA |

## Previous `0.7.0-alpha.1` exact-SHA release evidence (2026-09-20)

| Evidence | Verified result |
| --- | --- |
| Release source | Merge commit [`a31848bf5262c03c4fe3bb5a9d2b293a01682e9b`](https://github.com/yashumani/talk2data-conversational-intelligence/commit/a31848bf5262c03c4fe3bb5a9d2b293a01682e9b) |
| Merge-triggered checks | All 11 push workflows completed successfully, including CI, React, PostgreSQL, CodeQL, security, CSV acceptance, Pages, and both image validators |
| Pages workflow | [Run 35488413083](https://github.com/yashumani/talk2data-conversational-intelligence/actions/runs/35488413083) succeeded for the release SHA |
| Pages artifact | `github-pages`, artifact `10598153550`, SHA-256 `e2bb300ef1d00ed0e8b55c77d2e443a94b100926e070970c7b454fcfe973bdf0` |
| Public receipt | `release.json` reports source SHA `a31848bf5262c03c4fe3bb5a9d2b293a01682e9b` and version `0.7.0-alpha.1` |
| Hosted gallery review | `/workspace/` rendered 15 accessible named charts; Enter activated the queue control and rendered 61 reserved types; `aria-pressed` and the polite live result count tracked both views; no application console error or desktop horizontal overflow was observed |
| Public image | `ghcr.io/yashumani/talk2data-conversational-intelligence:sha-a31848bf5262c03c4fe3bb5a9d2b293a01682e9b`, digest `sha256:6b070b878dde944e731a68d33dc02a94a405ad2110f12ada0c1f016dddb6092c` ([run 35488573547](https://github.com/yashumani/talk2data-conversational-intelligence/actions/runs/35488573547)) |
| Public SBOM/provenance | BuildKit generated and pushed the SBOM attestation; signed SLSA provenance [attestation 48714507](https://github.com/yashumani/talk2data-conversational-intelligence/attestations/48714507) binds the digest, workflow, `main`, and release SHA |
| Internal image | `ghcr.io/yashumani/talk2data-internal:sha-a31848bf5262c03c4fe3bb5a9d2b293a01682e9b`, digest `sha256:79a04020c84b1841b5486fd0bea8a68d1124b6dd7619b58d37a8fce1063023b9` ([run 35488581633](https://github.com/yashumani/talk2data-conversational-intelligence/actions/runs/35488581633)) |
| Internal SBOM/provenance | BuildKit generated and pushed the SBOM attestation; signed SLSA provenance [attestation 48714553](https://github.com/yashumani/talk2data-conversational-intelligence/attestations/48714553) binds the digest, workflow, `main`, and release SHA |
| Internal receipt | Artifact `internal-image-receipt-a31848bf5262c03c4fe3bb5a9d2b293a01682e9b` (`10597544686`), artifact SHA-256 `71139634d1b6e59ebaafb8f08e6ca480642b8c745c87dea37c793a8bea91e106` |

The browser review is a release smoke test, not a claim of formal WCAG certification. Future chart
batches require their own keyboard, responsive-layout, contrast, and assistive-technology review.

## Base-image advisory disposition

The release owner accepts the currently unfixed Debian 13 base-image High advisories for
community-alpha releases **only within the boundary below**, provided the alpha.2 hosted scan
confirms the same no-fix-available disposition. They are unresolved upstream findings,
not false positives, and remain visible in GitHub code scanning. This acceptance is not permission
to expose either container as a public runtime or claim production readiness.

Risk is constrained because the public deliverable is source plus a network-disabled static Pages
gallery; it does not deploy the flagged runtime image. CI continues to fail on any fixable
High/Critical container finding, keep full SARIF visibility for unfixed findings, and rebuild the
images on dependency or base-image changes. Reassess this exception when an upstream fixed package
or replacement base becomes available and before any Internet-facing runtime deployment. Therefore,
the present unfixed advisories are recorded risks, not a community-alpha release showstopper.

## Public boundary

The public alpha is the source repository, contributor workflow, synthetic CSV evaluation path,
and static visualization gallery. It is **not** a public data API, model proxy, hosted BigQuery
service, or production SLA. Pages must contain no runtime URL, credential, API client, WebSocket,
browser storage, or customer data.

## Release decision

`0.7.0-alpha.2` is **GO** for the scoped community alpha and supersedes `0.7.0-alpha.1`. Its
protected merge, exact-SHA Pages receipt, immutable artifact, browser acceptance, image digests,
SBOMs, and signed provenance are recorded above. This decision authorizes public source,
contribution, the synthetic CSV path, and the static visualization studio only; it does not
authorize a public runtime deployment.
