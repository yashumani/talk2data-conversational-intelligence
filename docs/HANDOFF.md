# Talk2Data product handoff

Reviewed 2026-09-09. This is the tested development candidate for the agreed six-cycle
implementation. Production activation remains subject to the live acceptance items below.
The six-cycle source revision and CI evidence are recorded in
[PR #24](https://github.com/yashumani/talk2data-conversational-intelligence/pull/24).
The subsequent dependency/workflow hardening and its exact-source validation are recorded in
[PR #26](https://github.com/yashumani/talk2data-conversational-intelligence/pull/26).

## What you can run now

The standalone React + Python CSV demonstration runs without GCP or model credentials.
Use the integrated `main` branch:

```bash
git clone --branch main --single-branch https://github.com/yashumani/talk2data-conversational-intelligence.git
cd talk2data-conversational-intelligence
docker compose -f docker-compose.csv-demo.yml up --build --wait --wait-timeout 120
```

Open <http://127.0.0.1:8000/workspace/>. Select **Start CSV demo**, download the supplied
synthetic template and upload it. The supplied anchor is **2026-08-01**. Ask:

> What were mobile activations by region last month?

The returned regional values must sum to **24,676** for July 2026. Inspect the returned data,
source receipt and metric/dimension definitions. Refresh to recover the saved conversation.
Try the definition draft/review/publication exercise and inspect which publication each answer
used. The CSV review exercise cannot approve internal business definitions.

With Python 3.11+ installed, run the independent HTTP acceptance check from the same checkout:

```bash
python scripts/csv_workspace_smoke.py
```

The first accepted CSV contract is **Mobile Activations**, with required date, region,
channel and activations columns; market, store and plan are optional. It does not accept
arbitrary spreadsheet schemas or infer new metric formulas. Questions remain self-contained:
saved conversations do not add automatic conversational model memory. Detailed supported
formats, validation, expiry, recovery and cleanup are in [CSV_WORKSPACE.md](CSV_WORKSPACE.md).

## What has been delivered

| Cycle | Delivered capability | Acceptance status |
| --- | --- | --- |
| 1 | One product repository; thin React/Python entry points; separated services/tools; optional isolated CSV workspace | Accepted |
| 2 | Separate signed internal API and governed BigQuery connector/configuration | Complete on the user-approved placeholder boundary; actual GCP/SSO remains deferred |
| 3 | Live metric/dimension definition governance, immutable citations and saved CSV reproduction | Accepted |
| 4 | Claude adapter and bounded specialist orchestration with deterministic query and answer verification | Implementation complete; real Claude gate LA-1 still open |
| 5 | Durable conversation/run state, ordered progress, retries, cancellation and restart recovery | Implementation and automated acceptance complete; enterprise promotion still depends on applicable live gates |
| 6 | Reference recovery/retention, shared PostgreSQL state/grants/definitions, fenced workers, signed internal UI, private infrastructure and release review controls | Implementation complete; private activation and release acceptance still open |

The internal workspace has its own build/container and signed identity gateway. It presents
approved business definitions, saved conversations, grouped result data and the exact definitions
used by a saved answer. Explicit conversation removal frees capacity; active work must first stop.
CSV capabilities, files, settings and credentials do not select or initialize internal BigQuery.

The final review, corrections, evidence and limitations are in [FINAL_REVIEW.md](FINAL_REVIEW.md).

## What is required to close the live gates

**Immediate dependency: real Claude acceptance (LA-1).** Configure these existing GitHub
Actions inputs through the approved secret/configuration process:

| Kind | Name | Required value |
| --- | --- | --- |
| Repository secret | `ANTHROPIC_API_KEY` | Approved Claude API credential |
| Repository variable | `T2D_CLAUDE_MODEL` | Approved model supporting the configured structured-output contract |
| Repository variable | `T2D_CLAUDE_ACCEPTANCE_APPROVED` | `true`, after approving the synthetic benchmark egress |

Run **Claude live acceptance** on the reviewed completion branch. Require all nine benchmark
cases and retain the live artifact. A configuration-only success or skipped job does not pass
LA-1. No GCP connection is needed for this benchmark. The workflow injects the repository
secret as `T2D_CLAUDE_API_KEY`, matching the runtime's default secret reference and the private
Terraform deployment. See [CLAUDE_ORCHESTRATION.md](CLAUDE_ORCHESTRATION.md).

**Deferred GCP/SSO activation (DG-1).** Supply the approved project, region, private network,
restricted workload principals/views, SSO audience and private semantic/configuration files.
Review the concrete private infrastructure plan before applying it. Run the restricted-principal
BigQuery and real sign-in acceptance on the candidate image. The approved deferral remains
in effect; the CSV demonstration can be evaluated independently.

**Enterprise acceptance.** Business owners must approve metric definitions and benchmark
answers. The deployment needs actual private state/failover, backup/restore, retention,
load/cost/SLO, browser/keyboard/accessibility and supported-device evidence. Business, security
and operations owners must review the same source, image and configuration. These measurements
and approvals cannot be replaced by unit-test coverage or self-written receipts.

## Review and release procedure

1. Keep the integrated `main` revision intact and require its application, Pages and internal-image
   validation checks. Code integration does not waive LA-1, DG-1 or owner acceptance.
2. After the applicable live gates pass, build the immutable internal image through the protected
   `internal-image-publish` environment and retain its digest, SBOM, provenance and receipt.
3. Bind real acceptance receipts to that exact source, image and private configuration.
   Run the enterprise review and provenance verifier with the protected reviewer policy.
4. Activate the reviewed private deployment only after the environment gates and owners
   approve it. The receipt tools never merge, deploy, change permissions or approve their own claims.

No real provider connection, private cloud deployment or business-owner approval is inferred from
development integration. Full enterprise acceptance remains pending for the concrete reasons
above. There is no additional feature-development cycle proposed.

## Maintainer map

| Need | Primary guide |
| --- | --- |
| Original requirements and architecture | [PRODUCT_ORCHESTRATION_PLAN.md](PRODUCT_ORCHESTRATION_PLAN.md) |
| Metric/dimension lifecycle and approval | [DEFINITION_GOVERNANCE.md](DEFINITION_GOVERNANCE.md) |
| Internal connector and signed identity | [INTERNAL_BIGQUERY.md](INTERNAL_BIGQUERY.md) |
| Shared state, workers and private infrastructure | [SHARED_INTERNAL_RUNTIME.md](SHARED_INTERNAL_RUNTIME.md) |
| Conversation, retry and replay contracts | [DURABLE_CONVERSATIONS.md](DURABLE_CONVERSATIONS.md) |
| Backup, retention, evidence and release operations | [RELEASE_OPERATIONS.md](RELEASE_OPERATIONS.md) |
| Complete CSV and enterprise activation sequence | [REPOSITORY_ACTIVATION_GUIDE.md](REPOSITORY_ACTIVATION_GUIDE.md) |
| Locked installation, action pins and remaining build boundaries | [BUILD_REPRODUCIBILITY.md](BUILD_REPRODUCIBILITY.md) |
