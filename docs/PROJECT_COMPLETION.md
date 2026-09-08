# Consolidated completion checkpoint

Updated 2026-09-08. The user authorized combining the remaining Cycle 5/6 work into one
completion effort. This replaces the previous one-sub-milestone-at-a-time stopping instruction.
The original product scope and six-cycle plan remain authoritative.

## Implementation versus accepted release

| Item | Implemented capability | Acceptance boundary |
| --- | --- | --- |
| Cycle 5 | Durable conversations, revisions, safe retries, cancellation, progress/replay, saved results and CSV restart recovery | Automated/package acceptance delivered in PR #23; formal acceptance/merge still depends on open Cycle 4 LA-1 |
| Cycle 6.1 | Verified reference backup/restore, controlled retention/audit, bounded HTTP, safe telemetry and receipt checks | Delivered in PR #24; reference recovery checks remain required |
| Cycle 6.2 | Shared PostgreSQL state, definitions and grants; independently claimable/fenced jobs; signed internal React workspace; private Cloud SQL/Cloud Run infrastructure | Actual PostgreSQL and application tests, UI coverage/build, container and Terraform validation required; private activation is DG-1 |
| Cycle 6.3 | Exact-candidate evidence checks, authenticated GitHub workflow/artifact provenance, three distinct authorized owner approvals and review workflow | Automation implemented; real acceptance evidence, private rollout and owner approvals remain open |

PR #24 is the consolidated completion candidate. PR #22 and #23 remain visible dependencies;
none is automatically merged by the release checker. Passing code checks establishes a tested
development candidate, not a completed enterprise production release.

## Fixed definition of done for this development handoff

- Existing CSV, internal identity, semantic governance, Claude contract and connector behavior passes.
- Actual PostgreSQL proves shared admission, independent process ownership, cancellation/fencing,
  event rollback, current definitions/grants and the signed API/worker path.
- Python lines and branches independently meet 96%; React lines, statements, functions and
  branches independently meet 96%, with all production modules included.
- Separate CSV/internal UI builds and real containers pass their applicable checks; Terraform
  validates without connecting GCP. Every skipped live job remains labeled unconfigured/skipped.
- Canonical documentation and the candidate PR record the exact tested source and honest open gates.

Once these conditions pass, stop adding implementation features. The remaining work follows
the activation/acceptance ledger below. No optional orchestration framework, new data connector,
CSV schema expansion or broader model memory is required to close this agreed development scope.

The current Python acceptance run passes **804 tests** with **99.17% line coverage** and
**97.02% branch coverage**; six external-service checks remain explicitly opt-in. React passes
**99 tests** with independent coverage floors enforced. The final PR records the exact commit,
coverage fractions, all required workflow links and the unchanged LA-1/DG-1 dispositions.

The user-requested final review corrected stale-result handling, conversation capacity recovery,
grouped internal evidence, malformed pending requests, provider secret injection and lease expiry
during database lock waits. See [FINAL_REVIEW.md](FINAL_REVIEW.md) for findings and verification,
and [HANDOFF.md](HANDOFF.md) for startup instructions and the concrete remaining acceptance inputs.

## Remaining enterprise acceptance

| Gate | Required concrete evidence | Current disposition |
| --- | --- | --- |
| LA-1 | Real Claude benchmark on the reviewed source with an approved model/key and synthetic egress | Open; not waived or deferred |
| DG-1 | Real restricted BigQuery principal/results, signed SSO/IAP, private ingress and approved project configuration | User-deferred placeholders; required before internal production activation |
| Production state and workers | Candidate image deployed privately; actual database restart/failover, worker loss, fencing and cancellation | Automated reference proof exists; live environment acceptance pending |
| Backup/restore and retention | Quarantined managed restore, reconciliation of grants/withdrawals, owner-approved holds/retention, demonstrated RPO/RTO | Reference SQLite recovery is tested; production policy/recovery pending |
| Load and cost | Approved concurrency, latency/error/SLO targets, representative load, warehouse/model ceilings and cancellation costs | Limits implemented; workload targets and live measurements pending |
| Business and UX | Owner-approved metric benchmark; browser, keyboard/accessibility and supported device acceptance | API/component proof exists; business and browser acceptance pending |
| Release approval | Named business, security and operations approvals of the exact source/image/configuration with trusted evidence | Workflow and verifier implemented; no approval is fabricated |

The existing `Claude live acceptance` workflow only runs its live job after its approved
configuration exists. Configure provider secrets through the approved secret manager/repository
settings, not through chat or source control. The previous GCP deferral remains in force; no
project, warehouse credential, SSO identity or company definition has been invented or activated.

## Trusted release evidence and review

`operations/release.py` verifies all 12 mandatory receipts and their files. The candidate binds
the exact source SHA, immutable image digest and private configuration digest. Deferred, skipped,
simulated, missing, stale and mismatched evidence cannot pass.

After actual acceptance, produce a `candidate-evidence` Actions artifact containing flat JSON:
`candidate.json`, `manifest.json`, and each bounded receipt named by that manifest. Keep raw
private configurations, data, database backups and credentials out of public artifacts. Run
`Enterprise candidate review` from the reviewed `main` revision with those exact identifiers.
It validates the files before exposing business/security/operations review checkpoints.

Configure the three named GitHub environments with authorized reviewers and self-review
prevention. Merely creating environment names is insufficient: `operations/promotion.py` checks
the authenticated review history and requires three distinct allowlisted users, none the run
initiator. Receipt owner identities must match those actual approvals. Supply the review policy
from the protected private operator configuration; never accept an allowlist from the artifact.

The verifier reads GitHub's authenticated run and artifact APIs through `gh`, requires the
expected workflow on `main`, exact source SHA, successful first attempt, one unexpired immutable
artifact, and the artifact ZIP digest recorded by GitHub. It rejects unsafe archive paths,
symlinks, duplicates and oversized content, then reruns the candidate and receipt checks.
A workflow re-run requires a new review workflow because old approvals must not silently apply.

```bash
python -m talk2data.operations.promotion \
  --repository APPROVED_OWNER/APPROVED_REPOSITORY \
  --run REVIEW_WORKFLOW_RUN_ID \
  --candidate /private/candidate.json \
  --review-policy /private/review-policy.json
```

A successful result is `REVIEWED_CANDIDATE`; `deployment_authorized` remains false. The operator
must still approve the concrete private Terraform plan/rollout. Neither CLI merges code, grants
cloud authority, changes production traffic, bypasses repository protection or approves its own
evidence. Provenance identifies the producing workflow and accountable owners; it does not
turn a self-written claim into a measured load test. Review native test records alongside receipts.

Reference: GitHub's [workflow review history](https://docs.github.com/en/rest/actions/workflow-runs#get-the-review-history-for-a-workflow-run)
and [immutable artifact metadata](https://docs.github.com/en/rest/actions/artifacts).
