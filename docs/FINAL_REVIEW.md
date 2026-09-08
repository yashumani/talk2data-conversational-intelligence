# Final development review

Review date: 2026-09-08. The original six-cycle requirements and completion stopping point
define the scope. The review began from `8a9873e0a5c0c9221ac48476cd413edbc8558068` and produced
the corrections below. Final CI results and the exact reviewed source are recorded in
[PR #24](https://github.com/yashumani/talk2data-conversational-intelligence/pull/24).

## Findings and corrections

| ID | Finding and impact | Correction | Regression evidence |
| --- | --- | --- | --- |
| FR-1 | The internal UI could retain a previous result when refreshing into an empty conversation or when selection failed | Clear the prior result/history before refresh or selection; clear the prior result before a new submission or saved-result fetch | Internal component flows cover empty history, failed selection and lost submission acknowledgement |
| FR-2 | Internal users could fill the bounded conversation store without a UI control to free capacity | Add explicit confirmation and removal of the selected conversation; preserve server rejection of active work | Removal, cancellation/pending guards, rejected deletion and confirmation tests |
| FR-3 | Internal answers omitted grouped receipt rows and the exact dimension definitions used by saved results | Render receipt data in a semantic table; show pinned metric/dimension definitions, owners/versions and an earlier-publication notice | Exact cell values, column headers, citation versions, publication changes and absent-evidence tests |
| FR-4 | An unreadable saved request or a definitive missing-conversation response could leave recovery stuck | Clear malformed saved requests and definitive 404 rejections while retaining the original request for ambiguous/429 failures | Corrupt storage self-recovery, definitive rejection and exact-request retry tests |
| FR-5 | Private Terraform injected a different environment name from the Claude adapter's default reference, preventing configured startup | Align injection to `T2D_CLAUDE_API_KEY`; keep the public repository secret name and secret values separate | Deployment-to-provider secret-resolution contract using a synthetic value and no provider calls |
| FR-6 | Lease validity was calculated in the row-locking SELECT; a database lock wait could outlast the evaluated expiry | Lock the row first and evaluate the database clock afterwards, before heartbeat, progress or terminal updates | Actual PostgreSQL tests hold a row lock across expiry and reject late heartbeat/progress/completion; expired work is interrupted without redispatch |

Corrections preserve the existing source, identity, semantic and release boundaries. They do
not add a new framework, provider, CSV schema or data connection. All six findings are corrected
and their regressions pass. No unresolved implementation finding remains within this reviewed scope.

## Review coverage

- **Requirements and composition:** original requirement ledger, thin entry points, isolated
  CSV/internal composition, typed tools and deterministic query authority.
- **Business meaning and answers:** current authorized definitions, immutable answer citations,
  definition withdrawal, independently calculated CSV totals, missing-data abstention and grouped evidence.
- **Identity and data isolation:** signed server-verified identity, server-owned grants, source/scope
  bindings, private UI configuration and separate CSV capability handling.
- **State and execution:** admission/replay identity, cancellation, event ordering, current grants,
  independent worker ownership, database-clock fencing and expiry during contention.
- **Release and operation:** explicit migration, secret references, private infrastructure contract,
  recovery/retention boundaries, immutable artifact provenance and real owner-review requirements.
- **User flows:** component coverage of upload/question/recovery behavior and signed internal
  conversations, returned data, confirmation, failed operations and access loss.

## Verification record

Python passes **804 tests**, with six explicitly opt-in service checks skipped. The full
Python 3.11/3.12/3.13 matrix includes actual PostgreSQL 16. Python line coverage is **99.17%
(7182/7242)** and branch coverage is **97.02% (1694/1746)**. Ruff, formatting, strict typing
across 109 source files and all 20 workflow syntax checks pass.

React passes **99 tests** with **100% line, statement and function coverage** and **98.42%
branch coverage (437/444)**. Both CSV and internal production builds pass. Coverage floors
remain independently enforced at 96%; no production source was excluded to reach them.

The independent synthetic HTTP exercise passes **36 CSV checks** and **31 durable restart
checks** against the built assets and a real loopback HTTP server, stopped and recreated on
the same state. It independently checks **736 fixture rows** and **24,676 July activations**.
The sanitized report is [acceptance/final-http.json](acceptance/final-http.json). It contains no
session capability, database, credential or private company data. This reference exercise is
not a production disaster-recovery measurement.

Required final CI includes the Python 3.11/3.12/3.13 matrix with actual PostgreSQL 16, separate
Python line/branch coverage checks, React/build/audit, internal packaging, the real CSV container
restart/backup/restore exercise, private Terraform validation, PostgreSQL connector regression,
CodeQL and the Docker/Ollama runtime. All nine required workflows pass on the corrected code.
Read their exact final-candidate results in PR #24; Claude configuration success is recorded
separately from the skipped live job.

## Explicit limitations and external dependencies

- The review browser returned `net::ERR_BLOCKED_BY_CLIENT` for the local demo URL. No live
  browser, visual, keyboard, accessibility or device acceptance is claimed. Component/HTTP
  tests and semantic table markup do not substitute for those checks.
- No approved local Claude key/configuration is available. GitHub's Claude configuration
  check reports `NOT_CONFIGURED`, and the live job is skipped. LA-1 stays open and unwaived.
- Real BigQuery, SSO/IAP and GCP activation remain user-deferred DG-1. Recording transports,
  disposable PostgreSQL, packaged synthetic data and Terraform validation are not cloud acceptance.
- Real production failover/recovery, retention policy, load/cost/SLO, business metrics and owner
  approvals remain pending. No business/security/operations approval was fabricated; the PR
  review records contained no submitted reviews or inline review threads at inspection.
- The CSV first scope supports Mobile Activations with its approved schema. Wider metric
  families, arbitrary CSV mapping, fiscal-calendar/ratio/join evaluation, connected external
  context and conversational model memory need their own approved business contracts.

The release evaluator correctly remains blocked until actual required evidence is supplied.
This handoff closes the development review and supplies the tested candidate; it does not
claim a launched enterprise product. Follow [HANDOFF.md](HANDOFF.md) for the exact activation
inputs, review sequence and practical demonstration instructions.
