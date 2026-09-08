# Cycle 3: live business-definition governance

Cycle 3 supplies the definition lifecycle and its executable CSV demonstration. Cycle 2 is
complete with unconfigured GCP/BigQuery placeholders (PR #20); real cloud and SSO activation
remains deferred release gate DG-1. This increment requires no GCP account or provider key.
Cycle 4's [Claude and bounded orchestration](CLAUDE_ORCHESTRATION.md) builds on these snapshots.

## What can change

| Field | Lifecycle |
| --- | --- |
| Existing metric/dimension name, business definition, owner and aliases | Draft → submit → approve or reject → publish |
| Definition version | Increments for the edited record when published |
| Effective time | UTC-aware; publication cannot be backdated; optional future scheduling |
| Formula, aggregation, unit, ID, classifications, access scope, physical columns and semantic calculation version | Locked by the edit schema; change only through a coordinated contract/mapping migration and benchmark |
| Published snapshot | Immutable; can be withdrawn, never edited in place |

This is business-definition metadata authoring for registered metrics and dimensions. It is
not a formula editor, arbitrary CSV-schema importer, or approval of actual company metrics.
A new description must accurately describe the existing calculation. The human reviewer owns
that judgment; deterministic schema and name-collision checks cannot establish business truth.
Bundled owners and definitions are synthetic examples.

## Try it with CSV

Start the independent [CSV workspace](CSV_WORKSPACE.md), import the supplied template, and
ask for mobile activations by region last month with the date anchor 2026-08-01.

1. Inspect the answer's cited metric, dimension definitions and source/semantic fingerprints.
2. In **Manage business definitions**, choose a metric or dimension and **Propose change**.
   Enter its meaning, business owner, aliases and reason; optionally choose an effective UTC time.
3. **Save draft** does not change the active definitions. Add a note and **Submit for review**.
4. Add a review note and **Approve definition**, or reject the draft. Rejected drafts are terminal;
   create a new proposal to correct one.
5. Add a publication note and **Publish definition**. The active publication changes immediately
   unless scheduled for the future. Use **Refresh state** to see a scheduled activation or a change
   made by another client. API reads always resolve current server state.
6. Ask again: the request includes both the selected CSV fingerprint and the displayed definition
   snapshot. A stale snapshot returns 409 and asks for refresh. Previous answers keep their citations.
7. **Saved answers** retains the latest four successful runs. A rerun uses its original CSV,
   question, date anchor and definition snapshot, with a new execution receipt. Replacing the
   selected CSV does not silently replace the data used by a saved run, or vice versa.
8. Under **Publication history and withdrawal**, enter a reason and withdraw the current
   publication. New queries using it and saved runs pinned to it are blocked. Publish a reviewed
   correction to resume current queries; withdrawal never selects an older publication automatically.

The CSV workflow is explicitly **DEMO_SINGLE_USER**. Its session owner can exercise all review
steps under their actual demo identity. It never impersonates a second reviewer and cannot
publish to the internal registry. Only Mobile Activations is executable from CSV; editing other
packaged definitions does not add new CSV metric support.

A failed save keeps the editor open. A successful operation fetches authoritative server state.
Concurrent operations are blocked per CSV session; optimistic revisions also reject stale
draft reviews/publications. If the mutation succeeds but refresh fails, refresh before retrying
to avoid creating a duplicate draft. Durable mutation idempotency belongs to Cycle 5.

## Services and dependency boundaries

| Module | Responsibility |
| --- | --- |
| `domain/governance.py` | Strict edit/action models, draft state, snapshot, event and citation contracts |
| `services/definition_store.py` | SQLite persistence and compare-and-swap revision writes |
| `services/definition_governance.py` | Server-owned authorization, review transitions, effective snapshots, publication and withdrawal |
| `services/semantic_context.py` | Copies the exact metric and requested/filter dimension definitions into the answer |
| `services/semantic.py` | Query-semantic fingerprint includes relevant dimensions as well as the metric |
| `services/csv_workspace.py` | Per-session definition namespace, immutable upload references, four retained runs |
| `internal/runtime.py` | Private query pinning and pre-release revocation check |
| `api/routes/csv_definitions.py`, `internal/definitions.py` | Separate demonstration and verified-identity HTTP contracts |
| React definition editor/review/panel and history panel | Focused authoring, review and reproducibility UI; no warehouse configuration |

The application remains a modular Python monolith with separate public-demo and private
deployment compositions. No source-driver, cloud credential or SQL logic enters the React
entry point. Both profiles reuse the governance service with different, server-selected identity
policies and storage namespaces.

## Atomic publication and live resolution

The definition store has one revisioned stream per tenant/workspace. A transition reads a
validated state and writes only if its revision is still current. SQLite commits the revised
draft, immutable full-pack snapshot and ordered publication event in one transaction. A
competing writer receives a conflict; it cannot silently overwrite the winner.

Each snapshot ID is a SHA-256 hash of the canonical full pack, including owners, descriptions
and dimension definitions. Reads verify payload structure, stream revision and snapshot hashes.
These detect inconsistency; they are not cryptographic protection from an attacker who controls
the database. Protect database access through the private deployment boundary.

Each query reads the current eligible publication and constructs a fresh registry/compiler
from its own copy. There is no process-lifetime semantic cache in these paths. An in-flight
publication does not change the query's pin. Before returning its response, the service checks
that its pinned snapshot has not been withdrawn. Withdrawal blocks release of an affected
result. Definition citations are attached to the answer and the snapshot ID to the receipt.

Effective time is the maximum of requested time, publication time and the preceding publication's
effective time. Ties resolve by publication sequence. Publishing into the future does not affect
current queries early. A new draft must target the latest published head, including a scheduled
head; the API exposes snapshot history for that purpose. The demo editor targets the currently
effective publication, so wait for a scheduled head to activate before proposing the next UI edit.

Publication and withdrawal events carry monotonic sequence, snapshot ID, actor, time and reason.
Drafts retain the author, reviewer, submission/review/publication notes and final publication link.
Events are read through the state API. SSE, durable delivery, search-index consumers and
conversation replay are Cycle 5 work; no embedding index is needed for correctness here.

## Internal identity and persistence

The private API uses the existing verified signed-token identity and private entitlement map.
Every operation requires the correct tenant and `READ_AGGREGATED_DATA`. Additional actions:

| Operation | Server-owned grant |
| --- | --- |
| Create or submit | `EDIT_DEFINITIONS`; only the author can submit |
| Approve or reject | `REVIEW_DEFINITIONS`; reviewer must differ from author |
| Publish an approved draft | `PUBLISH_DEFINITIONS` |
| Withdraw a snapshot | `REVOKE_DEFINITIONS` |

Managing a publication requires classification clearance for its complete pack. Ordinary readers
receive only permitted metric/dimension metadata and cannot inspect review records or mutate
definitions. The browser and token claims cannot invent server grants. Revise grants in the
approved private entitlement file and follow the existing restart procedure for security changes.

Set optional `governance_database_path` in the private runtime JSON to an absolute approved
SQLite file path, for example `/var/lib/talk2data/definitions.db`. Supply a private writable
volume at that directory, owned by container UID/GID 10001 and restricted to the service.
The existing configuration and ADC mounts remain read-only; do not store this database in
either mount or in the public repository. The supplied Compose file does not provision a
persistent volume automatically. A private deployment override must provide it before use.

If the path is null/unset, definitions are in memory and lost on restart. Use this only for
ephemeral validation. A persisted store restores approved publications without overwriting them
with the bootstrap file. If the bootstrap contract changes, startup rejects it and requires an
approved migration; do not delete history as a workaround. Production backup, migration,
retention and recovery validation are required in Cycle 6.

Use one instance/worker for this increment's runtime query ownership. The SQLite store exercises
real concurrent-writer revision protection, but the application has no distributed job ownership
or durable conversation log yet. Do not deploy this as a horizontally scaled enterprise service
until the Cycle 5/6 gates pass.

## HTTP contracts

CSV paths are prefixed by `/v1/demo/csv` and require `X-Demo-Session`. Internal paths are
prefixed by `/v1/internal` and require verified identity. The private API has no CSV endpoints.

| Method and relative path | Behavior |
| --- | --- |
| CSV `GET /state`; internal `GET /definitions` | Active definitions, revision, authorized drafts/events/snapshot metadata |
| `POST /definitions/drafts` | Strict metadata edit with `base_snapshot_id`; returns 201 |
| `POST /definitions/drafts/{id}/{submit\|approve\|reject\|publish}` | `expected_revision` and nonblank `note`; transition returns updated draft |
| `POST /definitions/snapshots/{id}/revoke` | Expected stream revision and reason; returns 204 |
| `POST /chat` | Optional `definition_snapshot_id`; supplied ID must be current. React always supplies the visible pin |
| CSV `POST /history/{run_id}/rerun` | Executes the session's retained source and pin; no client-controlled replacements |

Definition errors use 403 for denied access, 404 for unknown records, 409 for conflicts,
withdrawn/not-yet-effective snapshots or unavailable history, and 422 for invalid input.
Responses prohibit caching. Existing routes continue supporting clients that omit a definition
snapshot: the server then resolves the current publication at request start.

## Capacity, retention and acceptance

CSV retains at most four successful runs, 64 drafts and 64 snapshots per session. Exceeding a
governance limit requires a fresh demo session; it does not silently evict approved history.
The same draft/snapshot limits apply to the current private store; archival/rotation needs an
approved migration before these bounds are reached. Rejected requests do not create saved runs.

Uploads, citations, saved data references and definitions disappear on CSV session clear,
expiry pruning or process shutdown. They are never uploaded to BigQuery. With Cycle 4's opt-in
Claude configuration, questions and approved definition metadata may be sent to the provider;
CSV rows, results and saved data references are excluded. Successful runs also retain the
validated interpretation so historical reproduction requires no new model call.
There is no durable internal query rerun endpoint in this cycle: BigQuery data reproducibility
also needs retained source snapshots and Cycle 5's durable run records.

Acceptance includes real SQLite persistence and competing writers, signed-token/two-person
private API tests, complete CSV draft-to-publication and history/revocation tests, publication
during a query, React interaction tests, and the installed package's HTTP acceptance script.
Independent Python line/branch and React line/branch/function/statement coverage floors remain
96% without production-module exclusions. Exact measurements and CI runs are recorded on
the Cycle 3 PR. Browser/visual, live GCP/SSO, actual business-owner and Claude acceptance are
not implied by these tests.
