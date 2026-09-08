# Repository activation and final verification guide

Reviewed on 2026-09-08 against development candidate
`5605393130f0ae294548801bf3d0de6df276cc48` on
`feat/cycle-6-operations-readiness` before this documentation-only addition.

This is the single activation runbook for the repository. It does not treat implemented code,
passing synthetic tests, a configured cloud resource or an approved production release as the
same thing. Follow the phases in order. Do not mark the enterprise product active until every
item in the final checklist has evidence for the same source revision, internal image digest and
private configuration digest.

## Current verdict

The codebase is a strong, tested development candidate. The standalone CSV product can be
activated now without Claude or GCP. The internal enterprise product cannot yet be called fully
active because the stacked PRs are unmerged, real Claude gate LA-1 is open, real GCP/BigQuery/IAP
gate DG-1 is deferred, and production recovery, load, browser/accessibility, business and owner
acceptance evidence has not been supplied.

No source-code defect was found in this review. The remaining blockers are release integration,
private configuration, live environment proof and accountable approval. Two operational details
must not be missed: the enterprise image must be built from `Dockerfile.internal`, and the Cloud
SQL schema and initial grants must be bootstrapped before the API and worker can become ready.

## Activation profiles

| Profile | Purpose | Data connector | Identity | Current state |
| --- | --- | --- | --- | --- |
| CSV demonstration | Product demo and evaluation | Strict Mobile Activations CSV | Anonymous capability-scoped session | Runnable and locally reverified |
| Public reference runtime | Existing synthetic/local reference APIs | SQLite or reference PostgreSQL | Request access context | Implemented; not the enterprise BigQuery deployment |
| Private internal runtime | Enterprise product | Server-owned approved BigQuery mapping | Signed IAP JWT plus PostgreSQL entitlements | Implemented; private activation pending |

Never combine the CSV Compose profile with the private internal deployment. CSV configuration,
state and files do not select or initialize BigQuery. The internal request contract does not
accept a caller-selected source or a CSV fingerprint.

## Repository-wide scan performed

The review enumerated all **315 published files**, including hidden repository configuration.
Every file was included in automated readability/format parsing or a subsystem-specific check;
production paths also received static analysis, type checking, tests or targeted trust-boundary
inspection. This is broader than sampling files, but it is not a claim that automated tools can
prove every business definition or cloud policy correct.

| Area | Review performed | Result |
| --- | --- | --- |
| All 315 files | UTF-8, NUL, maximum-size, trailing-whitespace and symlink scan | Passed; no issue found |
| Structured files | All JSON, YAML and TOML parsed | Passed |
| Documentation | Local Markdown link targets checked | Passed; no broken local target |
| Python | Ruff, formatting, strict mypy over 109 source files, compile-all | Passed |
| Python tests without PostgreSQL | 810 collected; 783 passed, 27 skipped | All runnable tests passed |
| Python local coverage without PostgreSQL | 93.81% combined | Expectedly below 96%; shared-state tests were unavailable locally |
| Python CI with PostgreSQL 16 | 804 passed, 6 opt-in live checks skipped; 99.17% lines and 97.02% branches | Passed on reviewed source |
| React | 99 tests, TypeScript, CSV build and internal build | Passed |
| React coverage | 100% statements/lines/functions; 98.42% branches | Passed |
| Node dependencies | `npm audit --audit-level=high` | No vulnerability reported |
| Python environment | `pip check` | No broken requirement reported |
| CSV HTTP behavior | Real local FastAPI process and 36-check smoke suite | Passed; 736 rows and July total 24,676 |
| Workflow/configuration | 20 GitHub workflows, Codespaces, Pages and Hugging Face validators | Passed |
| Shell | Bash syntax for all repository shell scripts | Passed |
| Secret scan | Key/private-key patterns and connection strings reviewed | No committed real secret found; local test passwords are synthetic |
| Security analysis | CodeQL workflow on reviewed source | Passed |
| Containers | CSV package/restart/restore and internal fail-closed package workflows | Passed remotely; Docker was unavailable in this review workspace |
| Terraform | Terraform 1.13.5 initialization and validation workflow | Passed remotely; Terraform was unavailable in this review workspace |
| Live Claude | Configuration job succeeded; live job skipped | **LA-1 open** |
| Live BigQuery/IAP/GCP | Recording/synthetic contracts only | **DG-1 open/deferred** |
| Browser/accessibility | Component semantics tested; real browser acceptance absent | Open |

### Reproduce the full development validation

Use Python 3.11 or newer, Node 24 and Docker with Compose. A plain `pytest` run without the
disposable state database skips the PostgreSQL worker/state tests and will not reach the 96%
coverage gate. Start PostgreSQL and pass the same explicit test environment used by CI.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

docker run --name t2d-state-review --rm -d \
  -e POSTGRES_DB=state_acceptance \
  -e POSTGRES_USER=talk2data \
  -e POSTGRES_PASSWORD=synthetic-state-test \
  -p 127.0.0.1:5432:5432 postgres:16-alpine

T2D_RUN_STATE_TESTS=1 \
T2D_TEST_STATE_DSN=postgresql://talk2data:synthetic-state-test@127.0.0.1:5432/state_acceptance \
pytest --cov=talk2data --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=96

python scripts/check_coverage.py
ruff check .
ruff format --check .
mypy src
python scripts/validate_workflows.py

cd apps/web
npm ci --ignore-scripts
npm test
npm run build
npm run build:internal
npm audit --audit-level=high
cd ../..

docker stop t2d-state-review
```

Run the repository workflows as the authoritative container, PostgreSQL and Terraform checks.
The six live external-service tests must remain skipped unless their approved private inputs are
present; a skipped test is not acceptance.

## Phase 1 — integrate the reviewed source

PRs #22, #23 and #24 are a stacked chain and are all still draft/unmerged. Do not merge #24 into
its feature-branch base and assume the code reached `main`.

1. Review and mark PR #22 ready. Resolve its review requirements, require its checks, then merge
   it into `main`.
2. Retarget PR #23 from `feat/cycle-4-claude-orchestration` to `main`. Confirm the diff still
   contains only Cycle 5 work, rerun required checks, review and merge it.
3. Retarget PR #24 from `feat/cycle-5-durable-conversations` to `main`. Confirm the final diff,
   rerun required checks, review and merge it.
4. Require CI on the resulting `main` revision. Record that new 40-character source SHA. Evidence
   from `560539...` proves the reviewed development baseline but cannot certify a later merge SHA.
5. Create an immutable release tag only after the exact merged revision passes the required checks.

Recommended branch protection before merging:

- pull request required;
- required CI, React, CodeQL, package and infrastructure checks;
- conversation resolution required;
- no force pushes or branch deletion on `main`;
- distinct reviewers for business, security and operations release environments;
- self-review prevention on those environments.

The repository is currently public. Keep all real domain definitions, physical object names,
entitlements, acceptance results, credentials, state backups and private Terraform values outside
the repository and its build context.

## Phase 2 — activate the CSV product

This path requires no GCP, BigQuery or model key.

```bash
git clone https://github.com/yashumani/talk2data-conversational-intelligence.git
cd talk2data-conversational-intelligence
git checkout RELEASED_MAIN_SHA_OR_TAG
docker compose -f docker-compose.csv-demo.yml config --quiet
docker compose -f docker-compose.csv-demo.yml up --build --wait --wait-timeout 120
python scripts/csv_workspace_smoke.py
```

Open `http://127.0.0.1:8000/workspace/`, start the CSV session, download/upload the supplied
fixture and ask: `What were mobile activations by region last month?` with the supplied
2026-08-01 anchor. The regional values must total **24,676**.

CSV acceptance must also include restart and restore:

1. Run `scripts/durable_csv_smoke.py prepare` and retain its private checkpoint only for the test.
2. Restart the API container.
3. Run `scripts/durable_csv_smoke.py verify` against the same private checkpoint.
4. Follow `RELEASE_OPERATIONS.md` to stop the writer, create a verified backup, restore into a
   new directory and verify the restored copy.
5. Remove the test checkpoint and synthetic volume when acceptance is complete.

The accepted CSV contract is deliberately narrow: required `date`, `region`, `channel` and
`activations`; optional `market`, `store` and `plan`. It is not an arbitrary spreadsheet agent.

## Phase 3 — close Claude gate LA-1

Claude is an optional, isolated interpretation service. It receives the question and approved
semantic catalog, not CSV rows, BigQuery results, credentials or executable SQL. Deterministic
services retain tool selection, authorization, query compilation, execution and verification.

Configure GitHub without committing values:

| Setting | Value |
| --- | --- |
| Repository secret `ANTHROPIC_API_KEY` | Approved Anthropic key |
| Repository variable `T2D_CLAUDE_MODEL` | Approved Claude model ID matching the configured structured-output contract |
| Repository variable `T2D_CLAUDE_ACCEPTANCE_APPROVED` | `true` only after synthetic benchmark egress/cost approval |

Run **Claude live acceptance** on the exact candidate. Require the `live` job—not only the
configuration job—to pass all nine cases, download the `claude-live-acceptance` artifact, and
record its source SHA, model, fixture digest, case statuses and usage. Provider failure does not
count as safe abstention. No GCP connection is needed for LA-1.

For internal production, place this block in both private runtime files after LA-1:

```json
{
  "claude": {
    "enabled": true,
    "model": "APPROVED_CLAUDE_MODEL",
    "secret_ref": "env://T2D_CLAUDE_API_KEY",
    "egress_approved": true,
    "allowed_tenants": ["APPROVED_TENANT"],
    "allowed_metric_ids": ["APPROVED_METRIC_IDS"],
    "maximum_classification": "APPROVED_MAXIMUM_CLASSIFICATION",
    "maximum_input_tokens": 8000,
    "maximum_output_tokens": 512,
    "maximum_prompt_bytes": 40000,
    "request_timeout_seconds": 25,
    "maximum_concurrent_requests": 4,
    "limits": {
      "deadline_seconds": 90,
      "maximum_steps": 6,
      "maximum_model_calls": 1,
      "maximum_total_tokens": 12000
    }
  }
}
```

Do not copy the fragment as a complete runtime file. Merge it into reviewed private copies of
`shared-api.example.json` and `shared-worker.example.json`.

## Phase 4 — prepare the enterprise inputs

Obtain named owners for platform, networking, identity, security, BigQuery data, business
definitions, operations and product acceptance. Record these approved values before provisioning:

- GCP project ID/number, region and billing account;
- existing VPC network and subnet IDs, private services access range and egress/NAT policy;
- Artifact Registry repository;
- approved GCS Terraform backend and state access policy;
- IAP audience and explicit organizational users/groups;
- approved BigQuery billing project, location, authorized view and dependencies;
- API and worker workload principals and least-privilege BigQuery grants;
- Cloud SQL database administrator and non-admin runtime database role;
- Claude secret, approved model and egress policy;
- business-owned domain packs, catalog mapping and entitlement bootstrap;
- latency, concurrency, availability, cost, retention, RPO and RTO targets.

Create private files outside the repository:

| File | Required content |
| --- | --- |
| API `runtime.json` | `process_role: api`, signed IAP settings, `/app/internal-web`, BigQuery limits, shared state and exact deployment revision |
| Worker `runtime.json` | Same trusted contracts, `process_role: worker`, `web_directory: null` |
| `domains/*.yaml` | Approved effective metric and dimension definitions |
| `catalog.json` | Exact approved `project.dataset.view`, allowed dependencies and physical columns |
| `entitlements.json` | Exact IAP subject-to-tenant/action/row/classification grants |
| `acceptance.json` | Business-owned questions, expected results, token sources and forbidden-access probes |

Validate these invariants before upload:

- every `AVAILABLE` metric in a domain pack has exactly one approved BigQuery binding;
- semantic version, aggregation, unit, currency, classification, dimensions and time grains match;
- mappings expose only simple identifiers and exact three-part view names;
- the API and worker configs contain the exact merged source SHA in `deployment_revision`;
- both use the exact IAP issuer, Google JWK URL, ES256 and approved audience;
- the state DSN is referenced only as `env://T2D_STATE_DSN`;
- Claude is enabled only for explicitly approved tenants, metric IDs and classification;
- example projects, identities, results and zero digests have all been replaced;
- private files and secrets are never committed or included in public artifacts.

## Phase 5 — prepare GCP

Authenticate an approved operator and set explicit working variables. Do not put secret values in
shell variables or command history.

```bash
export T2D_ACT_PROJECT='APPROVED_PROJECT_ID'
export T2D_ACT_REGION='APPROVED_REGION'
export T2D_ACT_REPOSITORY='APPROVED_ARTIFACT_REPOSITORY'
gcloud config set project "$T2D_ACT_PROJECT"
```

Enable the required services after billing and organization policy review:

```bash
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  servicenetworking.googleapis.com \
  compute.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  iap.googleapis.com \
  bigquery.googleapis.com
```

The supplied Terraform does **not** enable APIs, create the Artifact Registry repository, create
BigQuery views/IAM, create the runtime database role, create secret values or configure the remote
state bucket. Those are deliberate organization-owned prerequisites.

Create the approved BigQuery view in the same location as its source. Prefer an authorized view,
row/column policies or separate governed tables according to the data owner's threat model. Grant
the worker only query-job creation in the billing project and data/metadata access to the approved
view dataset. The API needs metadata access because it validates the view contract at startup; it
does not need general source-table access. Review inherited IAM, policy tags and VPC Service
Controls explicitly.

Direct Cloud Run IAP and the code's JWT validation must use the same audience. The IAP service
agent receives Cloud Run Invoker through Terraform; `iap_members` grants only named users/groups.
No `allUsers` binding is created.

The Cloud SQL Auth Proxy uses private IP. The Cloud Run services and any bootstrap operator must
have access to the same VPC. Because Cloud Run egress is `ALL_TRAFFIC`, provide approved NAT or
equivalent controlled egress for Google's IAP JWK endpoint and Anthropic. Confirm Google API and
BigQuery reachability under the organization's Private Google Access/VPC-SC policy.

## Phase 6 — build the correct immutable internal image

The existing `Publish Talk2Data runtime image` workflow builds `Dockerfile`, which is the public
runtime. It is **not** the image expected by the private Terraform deployment. Until a protected
internal-image publication workflow is added, build and push `Dockerfile.internal` from the exact
released revision through an approved build system:

```bash
export T2D_ACT_SHA="$(git rev-parse HEAD)"
export T2D_ACT_IMAGE="$T2D_ACT_REGION-docker.pkg.dev/$T2D_ACT_PROJECT/$T2D_ACT_REPOSITORY/talk2data-internal:$T2D_ACT_SHA"
test "$(git status --porcelain)" = ''
docker build -f Dockerfile.internal -t "$T2D_ACT_IMAGE" .
gcloud auth configure-docker "$T2D_ACT_REGION-docker.pkg.dev"
docker push "$T2D_ACT_IMAGE"
gcloud artifacts docker images list \
  "$T2D_ACT_REGION-docker.pkg.dev/$T2D_ACT_PROJECT/$T2D_ACT_REPOSITORY/talk2data-internal" \
  --include-tags
```

Record the full `sha256:` digest and use
`REGION-docker.pkg.dev/PROJECT/REPOSITORY/talk2data-internal@sha256:...` in Terraform. Never deploy
the mutable tag. Scan the pushed digest with the organization's container/security tooling and
retain its SBOM/provenance.

## Phase 7 — create private secrets

Create Secret Manager secrets and pin explicit versions for:

- API runtime JSON;
- worker runtime JSON;
- domain pack file(s);
- catalog JSON;
- entitlement bootstrap JSON;
- state DSN;
- Claude API key.

Suggested mount contract matching the example runtime paths:

| Terraform map key | Filename | Mount |
| --- | --- | --- |
| `domains` | approved tenant YAML filename | `/domains` |
| `catalog` | `catalog.json` | `/catalog` |
| `grants` | `entitlements.json` | `/grants` |

`runtime_secrets.api` and `runtime_secrets.worker` are separately mounted as
`/runtime/runtime.json`. The state and Claude secrets are injected as `T2D_STATE_DSN` and
`T2D_CLAUDE_API_KEY`. Use pinned numeric secret versions, not `latest`.

## Phase 8 — stage Cloud SQL before application rollout

`infra/gcp` creates regional PostgreSQL 16, a private address, backups/PITR, separate API/worker
service accounts, Cloud Run services, IAP bindings and secret access. It does not perform the SQL
migration. Both application roles call `database.check()` during startup, so an empty database
cannot become ready.

Use the approved GCS backend and a reviewed `terraform.tfvars`. Initialize and validate first:

```bash
terraform -chdir=infra/gcp init -input=false \
  -backend-config=/absolute/private/backend.hcl
terraform -chdir=infra/gcp fmt -check
terraform -chdir=infra/gcp validate
terraform -chdir=infra/gcp plan -input=false \
  -var-file=/absolute/private/terraform.tfvars \
  -out=/absolute/private/talk2data.plan
terraform -chdir=infra/gcp show /absolute/private/talk2data.plan
```

Have the platform/security owner review the concrete plan. Bootstrap in two controlled stages:

1. Apply only the network peering, Cloud SQL instance/database and prerequisites needed to reach
   the database. Terraform resource targeting is an exceptional bootstrap operation; record it
   and immediately follow with a complete plan/apply.
2. Create a non-admin PostgreSQL runtime login through the approved Cloud SQL administration
   procedure. Store its generated password only in Secret Manager.
3. From a VPC-reachable, approved operator environment, run a pinned Cloud SQL Auth Proxy and use
   an administrator DSN only for migration.
4. Run the packaged explicit migration command:

   ```bash
   # T2D_STATE_DSN must already be injected by the approved secret mechanism.
   test -n "${T2D_STATE_DSN:-}"
   python -m talk2data.operations.shared_state migrate \
     --config /absolute/private/shared-api.json
   ```

5. Grant the runtime role `CONNECT` on `talk2data_state`, `USAGE` on schema `public`, and only
   `SELECT`, `INSERT`, `UPDATE` and `DELETE` on the `t2d_*` tables. The migration contains no
   sequences. Do not run the application as the database administrator.
6. Create the runtime DSN secret using the Cloud SQL Unix socket
   `/cloudsql/PROJECT:REGION:INSTANCE`, database `talk2data_state`, the runtime role and its
   password. The application accepts an authenticated Cloud SQL socket or verified TLS; it
   rejects an unverified remote DSN.
7. Inject the runtime DSN in the secure operator environment and publish initial grants:

   ```bash
   # Replace the process environment with the runtime DSN through the secret mechanism.
   test -n "${T2D_STATE_DSN:-}"
   python -m talk2data.operations.shared_state publish-grants \
     --config /absolute/private/shared-api.json \
     --expected-revision 0

   python -m talk2data.operations.shared_state check \
     --config /absolute/private/shared-api.json
   ```

8. Upload/pin the final runtime, state-DSN and private-file secret versions. Recreate the final
   Terraform plan with the immutable internal image digest and exact versions.
9. Apply the complete reviewed plan without `-target`. A post-bootstrap plan must show no
   unexpected omitted resource or unsafe replacement.

Never paste a real DSN into a ticket, chat, source file, process list or retained terminal log.
The quoted DSNs above describe secret injection points, not a recommendation to type secrets
literally on a command line.

## Phase 9 — validate the deployed private runtime

Do not send production traffic immediately. Keep access restricted to the acceptance group.

1. Confirm API and worker revisions use the same source/configuration binding and expected secret
   versions; confirm the two services use different service accounts.
2. Confirm API liveness and readiness. The worker must report a healthy polling loop. Readiness
   proves startup contracts, not continuous BigQuery availability.
3. Sign in through IAP. Verify the server-resolved subject, tenant, permitted actions, regions,
   business units and classification at `/v1/internal/me`.
4. Verify an unlisted subject, tampered/expired token, duplicate identity header and direct
   unauthenticated request are denied.
5. Verify the definition page shows the exact approved publication and that separate-author
   review is enforced.
6. Submit business-owned positive and negative questions. Reconcile every returned group and
   total independently against BigQuery. Verify citations, source snapshot, job ID, bytes and
   result/SQL hashes.
7. Prove row, business-unit, classification, metric and dimension denial. Query the configured
   inaccessible probe and verify failure.
8. Exercise retry with the same client request ID, lost acknowledgement, event reconnect,
   cancellation, worker loss, expired lease, grant revocation and definition withdrawal.
9. Confirm no question, token, row, result or raw URL appears in application, ingress or proxy
   logs.
10. Run representative load within approved concurrency. Measure end-to-end latency, error rate,
    Claude tokens, BigQuery scanned/billed bytes and cancellation cost.
11. Restore Cloud SQL into a quarantined instance. Reconcile current grants and definition
    withdrawals before access. Demonstrate the owner-approved RPO/RTO.
12. Complete desktop/mobile, keyboard, screen-reader and supported-browser acceptance.

These steps close DG-1 only when they use the restricted real principal, real signed IAP, real
approved view and candidate image. Mock transports and synthetic tokens cannot close DG-1.

## Phase 10 — release evidence and owner approval

Create one candidate record containing the exact merged source SHA, immutable internal image
digest and private configuration SHA-256. Produce all 12 fresh receipts required by
`operations/release.py`:

- `quality` and `csv_restart` by automated validation;
- `production_state`, `distributed_workers`, `backup_restore`, `load_and_cost` and
  `browser_accessibility` by live acceptance;
- `LA-1` and `DG-1` by their real provider/environment methods;
- `business_acceptance`, `security_approval` and `operations_approval` by named owners.

Run the local fail-closed evaluator, then upload the flat JSON `candidate-evidence` artifact from
an authenticated workflow. From the exact `main` revision, run **Enterprise candidate review**.
Configure its three protected environments with distinct allowlisted reviewers. The initiator
cannot approve; the three roles cannot be the same person.

Finally run `talk2data.operations.promotion` with the protected reviewer policy. A successful
result is `REVIEWED_CANDIDATE` and still returns `deployment_authorized: false`. A human operator
must approve the concrete Terraform rollout/traffic change. No repository command automatically
merges code, grants cloud authority or moves production traffic.

## Review findings that should remain visible

| Finding | Impact | Required treatment |
| --- | --- | --- |
| PRs #22–#24 are draft and stacked | Final cycles are not on `main` | Review, retarget and merge in order |
| LA-1 live job is skipped | Claude is not provider-accepted | Configure and pass the nine-case live gate |
| DG-1 is deferred | BigQuery, IAP and GCP are not live-proven | Complete private deployment and restricted-principal acceptance |
| Internal image has no publication workflow | Public image workflow is the wrong artifact for Terraform | Add a protected pipeline or perform a controlled `Dockerfile.internal` build/push |
| SQL migration/grant bootstrap is outside Terraform | First application revision cannot initialize an empty database | Use the documented staged bootstrap before full rollout |
| Repository is public | Private contracts or evidence would be exposed if committed | Keep private material in Secret Manager/protected evidence storage |
| Python dependencies have ranges but no committed lock | Rebuilding later may resolve different transitive versions | Produce an approved lock/SBOM or rely on a scanned immutable digest and retained provenance |
| Terraform provider lock is not committed | Provider resolution can change within the allowed range | Generate/review a lock in the protected deployment workspace |
| Actions and base images use major/minor tags; Ollama uses `latest` | Supply-chain inputs are mutable | Pin production build inputs by digest/SHA under security policy |
| Browser/accessibility evidence is absent | Component tests do not prove real UX | Complete supported-device and assistive-technology acceptance |

The final three supply-chain items are enterprise hardening findings, not failures in the current
functional test suite. They should be resolved or formally risk-accepted before a production
release requiring reproducible builds.

## Definition of fully active

The repository is fully active only when every box below is true for one exact candidate:

- [ ] PRs #22, #23 and #24 are reviewed and their intended changes are on protected `main`.
- [ ] The merged SHA passes Python 3.11/3.12/3.13 with PostgreSQL and all independent 96% gates.
- [ ] React tests, both production builds, dependency audit, CodeQL, containers and Terraform pass.
- [ ] CSV restart and verified restore acceptance pass.
- [ ] LA-1 passes the real Claude nine-case benchmark.
- [ ] The internal image is built from `Dockerfile.internal`, scanned, pushed and pinned by digest.
- [ ] Private runtime, domain, catalog, entitlements and secrets are reviewed and pinned by version.
- [ ] Cloud SQL schema and grants are bootstrapped; API and workers share healthy fenced state.
- [ ] BigQuery/IAP/GCP gate DG-1 passes with real least-privilege identities and denial probes.
- [ ] Load/cost/SLO, failover, backup/restore, retention and RPO/RTO evidence is accepted.
- [ ] Browser, mobile, keyboard, screen-reader and supported-device acceptance passes.
- [ ] Business owners approve definitions and benchmark answers.
- [ ] Distinct security and operations owners approve the same candidate.
- [ ] All 12 evidence receipts are fresh, verified and candidate-bound.
- [ ] The protected operator explicitly approves the rollout and traffic decision.

Until then, describe the repository as a tested development candidate with an independently
runnable CSV demonstration—not as a fully activated enterprise production product.

## Primary implementation references

- `HANDOFF.md` — development handoff and current open gates
- `INTERNAL_BIGQUERY.md` — private identity, mapping and connector contract
- `CLAUDE_ORCHESTRATION.md` — provider isolation and LA-1
- `SHARED_INTERNAL_RUNTIME.md` — PostgreSQL, workers and Terraform topology
- `RELEASE_OPERATIONS.md` — recovery, retention and evidence rules
- `PROJECT_COMPLETION.md` — fixed completion boundary
- Google Cloud: <https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run>
- Google Cloud: <https://docs.cloud.google.com/sql/docs/postgres/connect-auth-proxy>
- Google Cloud: <https://docs.cloud.google.com/bigquery/docs/authorized-views>
- Google Cloud: <https://docs.cloud.google.com/artifact-registry/docs/docker/pushing-and-pulling>
