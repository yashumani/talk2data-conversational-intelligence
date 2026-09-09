# Run the isolated React + CSV demonstration

This is an optional, single-worker demonstration. It does not connect BigQuery or internal data.
It defaults to rules-only; Claude interpretation can be enabled through its own private configuration
as described in [the Cycle 4 runbook](CLAUDE_ORCHESTRATION.md). CSV rows and query results remain local;
opt-in Claude receives questions and approved definition metadata. Existing `/demo` behavior and
existing backend selection remain available.
See the [product orchestration plan](PRODUCT_ORCHESTRATION_PLAN.md) for the full release scope.

## Requirements

Use Python 3.11+ and Node.js 24+. Run commands from the repository root unless stated otherwise.
Use synthetic or explicitly approved demonstration data. This anonymous feature is not a
production authentication or secure sensitive-file-upload service.

## Start the packaged demonstration

With Docker and Docker Compose installed, run this standalone configuration from the repository root:

```bash
docker compose -f docker-compose.csv-demo.yml up --build --wait --wait-timeout 120
```

Open [the workspace](http://127.0.0.1:8000/workspace/). This builds the React assets and Python
service into one image and starts one API worker. The demo binds only to the local machine,
persists CSV workspace state on its own named volume, uses a separate temporary synthetic SQLite runtime, and needs
no model service, cloud connection, provider key, or host `.env` file. Do not combine this
standalone file with an internal deployment override.

Verify the installed package with Python 3.11+ (standard library only):

```bash
python scripts/csv_workspace_smoke.py
```

The check retrieves the built assets and synthetic template over HTTP, independently sums
July's 24,676 activations, verifies source-bound answers and definition versions, checks
definition publication, stale-definition rejection, historical reproduction and withdrawal,
session isolation, invalid uploads, stale-source rejection and missing-day abstention, then
clears its two temporary sessions. It does not exercise a browser or claim visual acceptance.

Cycle 5 adds a second acceptance check across an actual API restart. Keep its capability
checkpoint outside the repository and do not share or upload that file:

```bash
python scripts/durable_csv_smoke.py prepare --checkpoint-file /tmp/talk2data-durable-checkpoint.json
docker compose -f docker-compose.csv-demo.yml restart api
python scripts/durable_csv_smoke.py verify --checkpoint-file /tmp/talk2data-durable-checkpoint.json
```

The verifier waits for readiness, restores the same source/answer/run, resumes stored events,
checks idempotency and source isolation, then clears its sessions and removes the checkpoint.
The release workflow runs both checks against the built container. Its artifacts contain only
sanitized check reports. Restarting the API keeps the volume; the following cleanup removes it.

Cycle 6.1 adds actual backup recovery to this workflow: stop the worker, create a verified
bundle, restore to a separate directory and start on that copy using
`docker-compose.csv-recovery.yml`. The same HTTP verifier checks the restored source, definitions,
answers and request identity. See [release operations](RELEASE_OPERATIONS.md) for the commands,
offline restriction and remaining production recovery gates. Backup data/capability files are
never CI artifacts.

Stop and remove the demo when finished:

```bash
docker compose -f docker-compose.csv-demo.yml down --volumes
```

The ordinary runtime image includes the workspace assets, while CSV stays disabled unless
explicitly enabled. Internal BigQuery placeholders are complete; real activation and validation
remain deferred to DG-1 in a separate deployment.

## Build and run one server

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
npm --prefix apps/web ci --ignore-scripts
npm --prefix apps/web test
npm --prefix apps/web run build
export T2D_CSV_DEMO_ENABLED=true
export T2D_OLLAMA_ENABLED=false
export T2D_OLLAMA_REQUIRED=false
export T2D_WEB_DIRECTORY=apps/web/dist
python -m uvicorn talk2data.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Open [the workspace](http://127.0.0.1:8000/workspace/). Select **Start CSV demo**, download the
synthetic template, and upload it. The UI chooses a date anchor one day after the source
coverage ends. For the supplied file, the anchor is 2026-08-01, and “last month” means July 2026.

Try:

- What were mobile activations by region last month?
- What were mobile activations by channel last month?
- What were mobile activations in Northeast yesterday?

Inspect the business definition, version, result rows, file fingerprint, and receipt.
Replace the file with another valid template to invalidate the previous result, then ask again.
Use **Clear data and end session** when finished.

The conversation panel shows accepted questions, specialist progress, cancellation and saved
answers. Refresh or **Resume existing run** recovers accepted work without submitting another
query. A process restart preserves terminal answers when storage is configured and marks
unfinished work **INTERRUPTED**. Make an explicit new request to try interrupted work again.
Saved history does not supply automatic model memory; keep each question self-contained.

In **Manage business definitions**, choose a metric or dimension, propose its business meaning,
owner and aliases, and supply a reason. Save, submit, approve and publish with review notes.
The demo labels this as a single-user exercise; it cannot approve internal definitions.
New questions use the current effective publication. **Saved answers** can reproduce the latest
four successful runs using their original CSV and definitions, even after a replacement upload.
See [definition governance](DEFINITION_GOVERNANCE.md) for scheduling and withdrawal behavior.

The built workspace is served only when `T2D_WEB_DIRECTORY` points to an existing build.
This does not alter the existing root redirect or automatically publish GitHub Pages.

## Optional frontend development server

Run the Python API as above, then in a second terminal:

```bash
npm --prefix apps/web run dev
```

Open [the development workspace](http://127.0.0.1:5173/workspace/). Its development proxy
forwards only the CSV API path to the local Python API. For a different local API address,
set `T2D_API_ORIGIN` in `apps/web/.env.local`. Do not put provider keys or cloud connection
details in Vite environment variables. No browser-side BigQuery client is required.

## Independent configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `T2D_CSV_DEMO_ENABLED` | false | Enable only the optional CSV endpoints |
| `T2D_CSV_DEMO_MAXIMUM_BYTES` | 2000000 | Maximum raw upload size |
| `T2D_CSV_DEMO_MAXIMUM_ROWS` | 20000 | Maximum accepted data rows |
| `T2D_CSV_DEMO_MAXIMUM_SESSIONS` | 16 | Workspace capacity, including persisted unexpired sessions |
| `T2D_CSV_DEMO_SESSION_TTL_SECONDS` | 1800 | Fixed demo-session lifetime |
| `T2D_CSV_DEMO_STATE_DATABASE_PATH` | unset | Optional absolute private SQLite path; unset means memory only |
| `T2D_WEB_DIRECTORY` | unset | Optional built frontend directory |

These settings do not modify `T2D_DATA_BACKEND`, PostgreSQL settings, or the separate BigQuery
settings. The CSV workspace uses packaged public definitions and its own isolated run store.
It never queries the ordinary runtime connector registry.

Keep one API worker per database; a file lock rejects a second worker on the same file.
The Compose profile sets the state path and mounts `csv-workspace-state` automatically. For a
local Python server, set an absolute path to enable equivalent persistence; when unset, state
is still lost on restart. Expired sessions become inaccessible and are pruned during subsequent
operations; restarting does not extend their original expiry. Expiry/clear is not a secure-erasure
guarantee. Browsers keep the capability and any pending question/request binding in session
storage, not the uploaded CSV. See [the persistence runbook](DURABLE_CONVERSATIONS.md).
Keep the server on loopback unless an approved demo ingress supplies HTTPS, limits, and access control.

## CSV format

```csv
date,region,channel,activations
2026-07-01,NORTHEAST,RETAIL,100
2026-07-01,NORTHEAST,DIGITAL,75
```

Supply every requested day for each returned group; this two-row example alone cannot answer
a complete-month question. Use the downloadable file for a complete synthetic demonstration.
Optional columns are `market`, `store`, and `plan`. Do not upload passwords, personal data,
SQL, business-definition files, formulas, or unrelated spreadsheet exports.

Only Mobile Activations is supported in this CSV increment. The existing seeded demo may
support other metrics; the CSV workspace never falls back to it. Ratio metrics and arbitrary
CSV schemas require approved mappings and are explicitly left to later work.

## Validation commands

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest --cov=talk2data --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=96
python scripts/check_coverage.py
npm --prefix apps/web test
npm --prefix apps/web run build
npm --prefix apps/web audit --audit-level=high
```

Live Ollama/PostgreSQL tests require their separately documented service configuration.
Python line and branch coverage must each reach 96%. Frontend lines, statements, functions,
and branches must each reach 96%. React flow tests run in an in-memory renderer and check
session restore/expiry, uploads, question submission, error recovery, evidence matching,
refresh, clearing, overlapping-operation prevention, lost acknowledgments, SSE parsing,
idempotent recovery, cancellation and saved history. They do not provide browser or visual QA.
Real BigQuery/Claude, browser end-to-end, load and enterprise identity acceptance are not proved
by these local checks. The separate Claude benchmark and its LA-1 gate are documented in the
[provider runbook](CLAUDE_ORCHESTRATION.md#verification-and-live-gate-la-1).

## Expected errors

- **404:** CSV feature is off or the API proxy is not reaching this backend.
- **401:** Session expired or is unknown. Start a new session and upload again.
- **409:** Another operation is running, capacity is reached, or a source/definition revision changed;
  a requested saved run may also be unavailable or its definitions withdrawn.
  Wait for the current operation or refresh the workspace state.
- **413:** Upload is too large.
- **415:** API callers must send the raw file with `Content-Type: text/csv`.
- **422:** Invalid template/request. Correct the named issue; rejected replacement uploads
  leave the previous accepted source untouched.
- **SOURCE_NOT_READY:** Required observations or comparison groups are missing. The service
  abstains and does not query another source.
- **INVALID:** Unsupported metric, dimension, scope, or result size. Narrow the question or
  use the supported template.
- **429:** The configured run concurrency, conversation capacity or Claude/session budget is exhausted.
- **502/503/504:** Invalid/unavailable/timed-out provider or exhausted execution budget; no
  alternate model/data connection or previous answer is substituted. Refine or retry explicitly.

HTTP retries are not redirected to other data connections. If an upload succeeds but the
following refresh fails, use **Refresh state** to recover the accepted backend state.
For durable runs, use **Resume existing run** after a lost acknowledgment or stream failure;
this reuses the original request identity. An old definition/source revision conflict requires
a state refresh and an explicit new question rather than silently rebinding the accepted run.
