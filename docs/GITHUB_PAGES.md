# GitHub Pages product showcase

Talk2Data publishes its static product showcase to:

```text
https://yashumani.github.io/talk2data-conversational-intelligence/
```

## What Pages does

The page is an honest, browser-only product tour and runtime launcher. It presents the current
repository architecture rather than treating an older PostgreSQL/Ollama example as the primary
enterprise design:

- the runnable CSV demonstration, which requires neither GCP nor a model credential;
- direct read-only BigQuery plus local SQLite state;
- a governed BigQuery-to-Parquet snapshot queried locally with DuckDB;
- optional Cloud Run, Cloud SQL and distributed workers for managed scale-out;
- the bounded semantic resolver, planner, executor, verifier and answer-composer stages.

The interactive preview contains four fixed scenarios calculated from the checked-in synthetic
CSV acceptance fixture. Every preview is visibly labeled as a fixture and `preview: true`; it is
not a live request or a production receipt. An unrecognized question abstains instead of creating
a number.

## Hosting boundary

GitHub Pages hosts only static HTML, CSS and JavaScript. It cannot run FastAPI, React server APIs,
SQLite, BigQuery, Parquet/DuckDB execution, Claude, Ollama or durable workers. Credentials,
connection strings, source data and private semantic configuration must never be placed in the
Pages artifact or browser configuration.

The primary **Run the CSV workspace** action opens the exact `main` revision in GitHub Codespaces,
where the real React and Python demonstration runs. The activation center links to the direct
BigQuery, Parquet and optional managed-profile runbooks. Its lower reference generator remains
available for the existing PostgreSQL/Ollama package API and is explicitly labeled as such.

## Optional public evaluation API

The product tour can connect to an intentionally public Talk2Data evaluation API over HTTPS. The
API base URL is resolved in this order:

1. `?api=https://approved-api.example.com`
2. the browser's saved setting;
3. `window.T2D_PUBLIC_API_BASE_URL`, generated from the repository variable;
4. blank, which keeps the safe fixture preview active.

To configure the optional repository variable:

```text
Settings → Secrets and variables → Actions → Variables
Name: T2D_PUBLIC_API_BASE_URL
Value: https://approved-talk2data-api.example.com
```

That backend must use HTTPS, allow origin `https://yashumani.github.io`, return ready from
`GET /health/ready`, expose `POST /v1/chat/demo`, and keep all credentials outside the browser.
Readiness is provider-neutral; the page does not require Ollama. The signed internal BigQuery API
uses organizational identity and `/v1/internal/*`, so it is deliberately not connected from this
public page.

## Deployment and verification

`.github/workflows/pages.yml` builds on `main` and Cycle PR branches, but deploys only the exact
`main` ref. It writes the optional public API URL, runs `scripts/validate_pages_site.py`, and
uploads the `site/` directory without rewriting source after validation. Separate concurrency by
event/ref prevents a PR build from canceling a production deployment.

`.github/workflows/verify-live-pages.yml` starts only after a successful Pages deployment (or an
explicit manual run), eliminating the former PR-versus-live race. It verifies the product-tour,
data-profile, fixture-label and `main` launch markers at the public URL.

Local validation:

```bash
python scripts/validate_pages_site.py
node --check site/app.js
node --check site/setup/app.js
python scripts/validate_workflows.py
```

Repository validation proves the static contract. A live release review must also open the public
URL, exercise every fixed preview including the abstention, confirm the activation-center links,
check browser console errors, and inspect desktop/mobile/keyboard/screen-reader behavior. That
browser work validates Pages only; it does not close the internal React workspace or private
enterprise acceptance gates.

## First-time Pages enablement

If Pages has not been enabled for the repository, an administrator must select **GitHub Actions**
once under `Settings → Pages → Build and deployment → Source`. The workflow does not request or
consume an administration token.
