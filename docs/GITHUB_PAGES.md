# GitHub Pages static visualization gallery

> **Candidate status:** the dedicated gallery is implemented and locally verified, but the
> public URL is not evidence of this candidate until its `release.json` identifies the exact
> reviewed SHA. See the [public alpha checklist](PUBLIC_ALPHA_RELEASE_CHECKLIST.md).

The community alpha publishes a static, synthetic visualization gallery. It shows all 15 accepted
Batch 1 renderers and the finite 61-item queue for Batches 2–8. It is a contributor-facing catalog,
not the Talk2Data application UI and not a data or model service.

## Enforced hosting boundary

- The entry point is `apps/web/pages/index.html`; the dedicated code lives under
  `apps/web/src/gallery/` and `apps/web/src/visualizations/`.
- The page's Content Security Policy sets `connect-src 'none'` and disables objects, forms,
  framing, and base-URI changes.
- Gallery-owned source is rejected if it contains a fetch/XHR/WebSocket client, browser storage,
  API path, runtime base URL, or API-key marker.
- The compiled artifact is rejected if it contains application API, credential, or persistence
  markers, exceeds 1 MB of JavaScript or 350 KB gzip, lacks license notices, or has a mismatched
  source receipt.
- Every chart uses deterministic synthetic values. No production/customer data, credentials,
  private schema, runtime configuration, or model call belongs in the artifact.

ECharts and React may contain generic browser implementation code internally; the page's CSP
still forbids connections, while source validation independently rejects network code written for
the gallery. This distinction avoids mistaking a dependency string for an application API client.

## Build and validate locally

Run source validation before generating the ignored release receipt:

```bash
python scripts/validate_pages_site.py --profile source
(cd apps/web && npm ci --ignore-scripts && npm run build:pages)
python scripts/prepare_pages_release.py --source-sha 0123456789abcdef0123456789abcdef01234567
python scripts/validate_pages_site.py --profile release \
  --source-sha 0123456789abcdef0123456789abcdef01234567
```

The sample SHA is only a local validation value. Hosted CI supplies `GITHUB_SHA`; maintainers must
never edit the receipt manually or present a locally generated receipt as deployment evidence.

## Deployment flow

`.github/workflows/pages.yml` builds and validates pull requests without deploying them. A push to
`main` may deploy only the artifact built in that workflow run. The workflow stamps the exact
source SHA and version, includes `LICENSE` and `THIRD_PARTY_NOTICES.md`, uploads `site/`, and uses
GitHub's OIDC-backed Pages deployment with minimal permissions.

The repository owner must enable GitHub Actions as the Pages source and protect the `github-pages`
environment. After deployment, verify all of the following against the public URL:

1. `/release.json` exactly matches the reviewed `main` SHA and `0.7.0-alpha.1`.
2. `/workspace/` loads without console, CSP, or network-request failures.
3. All 15 accepted cards render and the queue shows 61 non-interactive reserved types.
4. Keyboard focus, zoom, contrast, screen-reader names, mobile layout, and reduced-motion behavior
   are manually reviewed.
5. License notices are reachable and no legacy launcher or configurable API endpoint is exposed.

The intended URL after a verified deployment is:

```text
https://yashumani.github.io/talk2data-conversational-intelligence/
```

A reachable URL alone is not acceptance; only the matching receipt and hosted workflow evidence
bind it to this candidate.
