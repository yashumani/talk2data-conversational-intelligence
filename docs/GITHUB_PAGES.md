# GitHub Pages deployment

Talk2Data publishes a static demonstration interface to:

```text
https://yashumani.github.io/talk2data-conversational-intelligence/
```

## Hosting boundary

GitHub Pages hosts only static HTML, CSS, and JavaScript. It cannot run:

- the FastAPI service
- Ollama or model files
- SQLite or enterprise data connectors
- Hermes agents
- Unified AI Brain retrieval

The published interface connects to an approved Talk2Data API over HTTPS. The API remains responsible for authentication, authorization, Ollama interpretation, deterministic query execution, receipts, and answer verification.

## Deployment workflow

`.github/workflows/pages.yml`:

1. Configures GitHub Pages for a GitHub Actions publishing source.
2. Writes `site/config.js` from the optional repository variable `T2D_PUBLIC_API_BASE_URL`.
3. Validates the static site.
4. Uploads the `site/` directory as the Pages artifact.
5. Deploys through the protected `github-pages` environment.

The current demonstration branch is `feat/github-pages-demo`. Retarget the workflow trigger to `main` after the stacked application pull requests are merged.

## Connecting a backend

The site resolves the API base URL in this order:

1. `?api=https://approved-api.example.com`
2. The browser's saved setting
3. `window.T2D_PUBLIC_API_BASE_URL` generated from the repository variable
4. Blank, which leaves the interface in static-only mode

To configure the repository variable:

```text
Settings → Secrets and variables → Actions → Variables
Name: T2D_PUBLIC_API_BASE_URL
Value: https://approved-talk2data-api.example.com
```

The backend must:

- use HTTPS when called from the Pages site
- allow the origin `https://yashumani.github.io`
- expose `GET /health/ready`
- expose `POST /v1/chat/demo`
- keep credentials and source-system secrets outside the browser

## Enabling Pages

The workflow uses `actions/configure-pages` with enablement requested. When the repository's workflow token cannot change Pages settings, select **GitHub Actions** once under:

```text
Settings → Pages → Build and deployment → Source
```

A repository administrator can alternatively add a `PAGES_ADMIN_TOKEN` Actions secret with Pages and administration write permissions, allowing the workflow to perform first-time enablement.

## Accuracy statement

The static site does not calculate business metrics or fabricate AI answers. It displays live responses returned by the governed backend. When no backend is connected, the UI remains visibly in `Static UI` mode and does not simulate a certified answer.
