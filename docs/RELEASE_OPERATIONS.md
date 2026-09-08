# Cycle 6.1: operational recovery and release evidence

Updated: 2026-09-08. Cycle 6 is the enterprise release cycle. Following the user's instruction
to work **one milestone at a time**, this increment completes its first milestone: recoverability,
controlled retention, bounded internal HTTP handling and enforceable release evidence checks.
It does not complete the enterprise release or introduce a production database/worker platform.

## Delivery sequence and definition of done

| Milestone | Scope | Acceptance and status |
| --- | --- | --- |
| 6.1 Operational recovery and readiness | Offline validated backups/restores, retention preview/CAS/audit, safe request telemetry and evidence evaluator | Implemented here; whole-package tests, >95% independent coverage and actual container restore acceptance are required |
| 6.2 Production state, jobs and deployment | Cloud SQL/PostgreSQL application state and governance, distributed job ownership/fencing/cancellation, approved infrastructure and authenticated internal UI | Not implemented; retain the single-worker reference restriction until these contracts are tested |
| 6.3 Final enterprise acceptance | Private activation, protected promotion, live provider/cloud checks, business/security/platform owner approval, browser/accessibility, load/cost/SLO and disaster recovery | Open; no production promotion or enterprise-ready claim |

These are sub-milestones of the original sixth cycle, not extra delivery cycles or waivers.
Cycle 4's **LA-1 remains open**, with real Claude acceptance unconfigured. **DG-1 remains deferred**
under the user's GCP/SSO placeholder decision, but must pass before private production activation.
Neither a skipped live job nor a green configuration-only job counts as acceptance.

## Modules and trust boundaries

| Module | Responsibility |
| --- | --- |
| `operations/database.py` | Offline worker lock, read-only database access, schema/record/event/definition integrity checks |
| `operations/backup.py` | New backup bundle, digests/manifest, separate restore destination, safe CLI failures |
| `operations/retention.py` | Read-only preview, exact-state plan hash, transactional deletion and audit |
| `operations/http.py` | Internal request body/deadline/capacity limits, generated request IDs and content-free outcome records |
| `operations/release.py` | Candidate/evidence schemas, receipt-file verification, required gates and fail-closed CLI status |
| `docker-compose.csv-recovery.yml` | Acceptance-only startup against a newly restored CSV database |

The maintenance tools are local operator commands, not HTTP endpoints or agent tools. They
require access to the private database directory and never accept a browser-selected file path.
They do not connect GCP, send data to Claude, alter entitlement files, or deploy the application.
CSV and the internal application retain separate configuration, identities, stores and connectors.

## Backup and restore procedure

1. Schedule an approved maintenance window, stop the single application worker, and prevent new
   ingress. If definitions use a separate file, stop every writer of that file as well.
2. Create a bundle in a new restricted directory. The command acquires the same exclusive worker
   lock as the application. A live worker, relative/missing source, symlinked source or existing
   destination causes a failure; no application history is reset to work around an error.
3. Validate SQLite integrity/foreign keys and the current schema. Check conversation identity,
   revision/history consistency, run identity/status, ordered event sequences and final status.
   Validate persisted definition revisions and recomputed snapshot hashes where present.
4. Copy through SQLite's backup API, validate the copy, and finalize it as a standalone database
   with SHA-256 digest and size. A separate definitions file can be included in the same bundle.
5. Restore into another **new** directory. Verify the manifest, source digests and restored bytes,
   then revalidate the restored databases. Failed partial copies are removed. Existing production
   files and the backup bundle are never overwritten by the restore command.
6. Start a quarantined application on the restored paths and perform authorized acceptance.
   Review current entitlements and reconcile definition withdrawals/publications that occurred
   after the backup before reopening ingress. An old backup is not current authorization evidence.

The implementation uses the [SQLite backup API](https://www.sqlite.org/backup.html) instead of
copying a live database file and guessing whether its WAL is complete. This particular application
requires offline operation to keep its workspace and any separate governance file coherent.

```bash
python -m talk2data.operations.backup create \
  --state /absolute/private/state.db \
  --destination /absolute/private/backups/reviewed-backup

python -m talk2data.operations.backup restore \
  --bundle /absolute/private/backups/reviewed-backup \
  --destination /absolute/private/restored-copy
```

When `governance_database_path` is separate from `state_database_path`, add
`--definitions /absolute/private/definitions.db` to creation. When both use the same file, omit
that option: the state copy already includes definitions. Restored filenames are `state.sqlite3`
and, when separately supplied, `definitions.sqlite3`. Update the quarantined runtime configuration
to those exact paths; neither command changes the running deployment configuration for you.

Directories use mode 0700 and files 0600 where POSIX modes apply. The manifest contains only
version, creation time, digests and sizes; it contains no original paths, capabilities, questions
or source rows. The database files themselves contain retained data and require an approved
private backup location. Digests detect corruption, not a malicious rewrite of both manifest and
backup. Encryption, immutable/offsite copies, managed retention, owner approval and authenticated
backup provenance remain production platform responsibilities.

A restored CSV session retains its original expiry and requires the original capability.
Expired sessions are not revived. Completed run records and events are retained; uncertain
in-flight work becomes `INTERRUPTED` on startup and is never automatically dispatched again.
The commands do not claim a cloud query had no cost or that a historical BigQuery dataset is
reproducible merely because an old answer was restored.

## Controlled internal retention

Retention is separate from backup and is **preview-only by default**. It operates offline on
internal conversation state. CSV checkpoints or CSV governance namespaces cause rejection;
the demo continues using its fixed session expiry and explicit clear operation.

An eligible conversation has no active run and its latest activity is strictly before the
explicit timezone-aware cutoff. The operation deletes the conversation and its runs/events
together. It preserves current/recent/active conversations and governance history. It does not
delete arbitrary individual answers or silently reset a conversation's revision.

```bash
python -m talk2data.operations.retention \
  --state /absolute/private/state.db \
  --before 2026-08-01T00:00:00+00:00
```

Review the returned counts and `plan_hash` under the organization's retention policy, retain a
verified backup where policy permits, then explicitly apply that exact preview:

```bash
python -m talk2data.operations.retention \
  --state /absolute/private/state.db \
  --before 2026-08-01T00:00:00+00:00 \
  --apply-plan EXACT_REVIEWED_PLAN_HASH
```

The hash binds the cutoff and current persisted conversation/run/event state, plus governance
state when colocated. Any intervening change invalidates the plan. Deletions and the retention
audit row commit in one transaction; an audit failure rolls back deletion. The audit records
operation ID, time, plan hash and removed counts, without question text or raw identities.
The output excludes conversation IDs and data values.

Deletion removes live records. SQLite free pages, WAL, prior backups and storage snapshots may
retain bytes. This is not a secure-erasure implementation or an enterprise backup-expiry policy.
Do not use it to destroy records under a legal/business hold; hold-aware retention is not supplied
by this reference implementation. Production retention policy and approval remain a release gate.

## Internal HTTP limits and observability

The internal runtime now accepts a separate `http_operations` configuration block:

| Setting | Default | Meaning |
| --- | --- | --- |
| `maximum_body_bytes` | 65536 | Reject oversized bodies, including chunked transfers, before application processing |
| `body_timeout_seconds` | 5 | Bound the time allowed to receive the body |
| `maximum_inflight` | 128 | Per-worker HTTP concurrency ceiling; reject excess requests with 503 |

Invalid content lengths/framing return 400, excessive size 413, and body deadline exhaustion
408. The body is coalesced within the byte limit rather than retaining an unbounded number of
tiny chunks. Existing signed identity checks, run concurrency, provider budgets and connector
limits remain independent. These controls do not replace a production ingress rate limit or
distributed per-tenant admission policy.

Every HTTP request gets a server-generated request ID. Responses prohibit caching and add
`X-Content-Type-Options: nosniff`. Outcome records contain only the request ID, known method,
registered route template, status, duration and completion/disconnection/error outcome. Unknown
paths are labeled `UNMATCHED`. No raw URL/query string, request body, token, question, exception
message, source row or result is serialized into these operational records.

The internal container disables Uvicorn's ordinary access log so a second logger does not
reintroduce raw paths/query strings. For a custom startup command, also use `--no-access-log`.
Review ingress/proxy logging independently before private deployment. JSON records are suitable
for a structured log collector; see [Cloud Logging's structured logging model](https://docs.cloud.google.com/logging/docs/structured-logging).
No cloud sink, alerting destination, dashboard or SLO has been activated by this increment.

Telemetry is best effort and cannot replace the transactional run/governance journal or
retention audit. A failed telemetry sink does not change an already delivered application
response. Counters/limits are process-local; multi-instance coordination remains milestone 6.2.

## Release evidence contract

The evaluator requires independent candidate values for the exact 40-character source commit,
immutable image digest and private configuration digest. Evidence cannot qualify another build,
mutable tag or configuration. Each gate has one evidence record containing status, acceptance
method, the same three candidate identifiers, observation time, owner, relative receipt filename
and SHA-256 digest. Evidence must be no older than seven days and cannot be future-dated.

Receipt files are read from an explicit approved directory. Absolute paths, traversal, symlinks,
missing/oversized files, digest changes, malformed receipts and mismatched metadata fail closed.
The receipt is the JSON evidence record excluding `artifact_digest` and `evidence_reference`.
Native test reports and review provenance should be retained alongside the canonical receipts.
The checker validates receipt integrity and agreement; it does **not** authenticate a reviewer's
identity or prove a human-supplied claim is true. Protected promotion must independently verify
the producing workflow, artifact provenance and authorized owner approvals in milestone 6.3.

| Gate | Required acceptance method |
| --- | --- |
| `quality`, `csv_restart` | Automated validation |
| `production_state`, `distributed_workers`, `backup_restore`, `load_and_cost`, `browser_accessibility` | Live acceptance on the candidate environment |
| `LA-1`, `DG-1` | Real provider and real GCP/SSO acceptance respectively |
| `business_acceptance`, `security_approval`, `operations_approval` | Named owner review |

All gates are mandatory for enterprise release. `open`, `failed`, `skipped` and `deferred`
remain blocking. Recording-based tests cannot replace live acceptance. Missing files cannot
be replaced by a string saying an artifact exists. A successful result is called
`EVIDENCE_COMPLETE`, **not deployment authorized**; `deployment_authorized` always remains false.
This CLI does not merge, deploy, provision cloud infrastructure or waive any gate.

```bash
python -m talk2data.operations.release \
  --candidate /absolute/private/candidate.json \
  --manifest /absolute/private/evidence.json \
  --evidence-directory /absolute/private/receipts
```

Exit 0 means evidence records/files satisfy the contract, exit 1 means blocked gates, and exit 2
means invalid/unavailable input. Public examples deliberately contain zero-value candidate
placeholders and **no evidence**, so evaluation must report `BLOCKED`. CI verifies that behavior
and retains the blocked report. That CI step proves fail-closed behavior; it is not a release pass.

## Executable acceptance and stopping point

Unit/integration coverage includes live-worker refusal, real SQLite backup/restore, corrupt
schema/record/event/definition rejection, exact CSV answer restoration, copy corruption,
stale retention plans, active-run protection and rollback when audit insertion fails. HTTP
tests verify byte/time/concurrency limits, SSE receive compatibility, privacy, failure cleanup
and server-owned request IDs. Release tests exercise every gate, candidate binding, freshness,
receipt files and safe CLI error handling. All production modules remain in the coverage gates.

The existing packaged CSV workflow now performs both restart and backup recovery acceptance:
complete a synthetic question, stop the real container, create/restore a verified bundle,
start the container on the separate restored copy and run the 31-check durable HTTP verifier.
It checks exact totals, definitions, saved result, request identity, event replay, scope isolation,
replacement behavior and clear. No private capability checkpoint or database backup is uploaded;
only sanitized reports/manifests become artifacts. CI removes its own synthetic volume afterward.

The small synthetic recovery measurement is not a production RPO/RTO, throughput, availability,
load or cost certification. Named owners must set those targets and validate the real production
state/job deployment. Cloud SQL's managed [backup and recovery](https://docs.cloud.google.com/sql/docs/postgres/backup-recovery/backups)
capabilities will require a separate tested adapter/procedure; this SQLite CLI is not that adapter.

Stop this increment once its code, independent 96% coverage gates, existing regressions and
actual container restore acceptance pass and a reviewable PR records the evidence. The next
implementation milestone is **6.2**, not an enterprise launch. No existing production deployment
or private data is changed during this synthetic acceptance.
