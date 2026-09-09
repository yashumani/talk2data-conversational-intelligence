from __future__ import annotations

import csv
import json
import re
from collections import Counter
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

SITE = Path("site")
CSV_FIXTURE = Path("apps/web/public/samples/mobile-activations.csv")
REQUIRED = [
    SITE / "index.html",
    SITE / "app.js",
    SITE / "styles.css",
    SITE / "config.js",
    SITE / ".nojekyll",
    SITE / "demo" / "index.html",
    SITE / "setup" / "index.html",
    SITE / "setup" / "app.js",
    CSV_FIXTURE,
]

CODESPACES_URL = (
    "https://codespaces.new/yashumani/talk2data-conversational-intelligence?ref=main&quickstart=1"
)


def main() -> int:
    missing = [str(path) for path in REQUIRED if not path.exists()]
    if missing:
        raise SystemExit("Missing GitHub Pages assets: " + ", ".join(missing))

    html = (SITE / "index.html").read_text(encoding="utf-8")
    normalized_html = unescape(html)
    script = (SITE / "app.js").read_text(encoding="utf-8")
    styles = (SITE / "styles.css").read_text(encoding="utf-8")
    setup_html = (SITE / "setup" / "index.html").read_text(encoding="utf-8")
    setup_script = (SITE / "setup" / "app.js").read_text(encoding="utf-8")
    config = (SITE / "config.js").read_text(encoding="utf-8")

    for marker in (
        "Talk2Data",
        "Interactive product tour",
        "Data paths that match the codebase",
        "CSV workspace",
        "Direct BigQuery",
        "Parquet snapshot",
        "Managed GCP",
        "Fixture preview",
        CODESPACES_URL,
        "./styles.css",
        "./config.js",
        "./app.js",
    ):
        if marker not in normalized_html:
            raise SystemExit(f"Required page marker is missing: {marker!r}")

    if 'fetch("/v1/' in script or "fetch('/v1/" in script:
        raise SystemExit("Static client must use the configured API base URL.")
    if "`${apiBase}/v1/chat/demo`" not in script:
        raise SystemExit("Static client is missing the governed chat endpoint.")
    if "`${apiBase}/health/ready`" not in script:
        raise SystemExit("Static client is missing the runtime readiness check.")
    if 'data.status !== "ready"' not in script:
        raise SystemExit("Static client must use provider-neutral runtime readiness.")
    if "ollama?.status" in script:
        raise SystemExit("Static client must not require Ollama for every runtime profile.")
    if "browserPrincipal()" not in script:
        raise SystemExit("The public client must isolate its synthetic browser principal.")
    for marker in (
        "previewScenarios",
        "fetchWithTimeout",
        "validateBaseUrl",
        "Public runtime URLs must use HTTPS",
        "renderPendingEvidence",
        "renderFailedEvidence",
        "not a live receipt",
        "This static product tour does not calculate new answers",
        "No numeric claim released",
    ):
        if marker not in script:
            raise SystemExit(f"Static preview safety marker is missing: {marker!r}")
    for marker in (":focus-visible", "prefers-reduced-motion", "@media (max-width: 760px)"):
        if marker not in styles:
            raise SystemExit(f"Responsive/accessibility style marker is missing: {marker!r}")
    if "feat/github-native-runtime" in normalized_html:
        raise SystemExit("The checked-in Pages source must target main without deployment rewrites.")

    required_ids = {
        "main-content",
        "tour",
        "data-paths",
        "agents",
        "runtime",
        "runtime-detail",
        "source-icon",
        "source-title",
        "source-detail",
        "source-state",
        "examples",
        "chat",
        "form",
        "question",
        "send",
        "api-base",
        "connect",
        "ai",
        "decision",
        "claims",
        "receipt",
        "plan",
    }
    identifiers = re.findall(r'\bid="([^"]+)"', html)
    for identifier in required_ids:
        if identifiers.count(identifier) != 1:
            raise SystemExit(f"Page id must occur exactly once: {identifier!r}")

    with CSV_FIXTURE.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != 736:
        raise SystemExit("The Pages preview fixture must contain the accepted 736 rows.")
    months = sorted({row["date"][:7] for row in rows})
    if len(months) < 2:
        raise SystemExit("The Pages preview requires two complete comparison periods.")
    current, previous = months[-1], months[-2]
    totals: dict[str, Counter[str]] = {month: Counter() for month in (previous, current)}
    for row in rows:
        month = row["date"][:7]
        if month in totals:
            totals[month][row["region"]] += int(row["activations"])
    current_total = sum(totals[current].values())
    previous_total = sum(totals[previous].values())
    change = current_total - previous_total
    percentage = change / previous_total * 100
    preview_markers = [
        f"result_total: {current_total}",
        f"current_total: {current_total}",
        f"comparison_total: {previous_total}",
        f"+{change:,}, or +{percentage:.2f}%",
        *(f"{region.title()} {value:,}" for region, value in totals[current].items()),
    ]
    for marker in preview_markers:
        if marker not in script:
            raise SystemExit(f"The Pages preview is inconsistent with its CSV fixture: {marker!r}")

    for marker in (
        "Choose the smallest runtime that fits",
        "CSV demonstration",
        "Direct BigQuery",
        "BigQuery to Parquet",
        "Managed scale-out",
        "PostgreSQL and Ollama package generator",
        "Secret environment variable",
        "Validate package",
        "Download ZIP",
        "../config.js",
        "./app.js",
    ):
        if marker not in setup_html:
            raise SystemExit(f"Required setup marker is missing: {marker!r}")

    if 'type="password"' in setup_html.lower():
        raise SystemExit("The public setup wizard must never request a database password.")
    if "actual password" not in setup_html.lower() and "never a password" not in setup_html.lower():
        raise SystemExit("The setup wizard must explain the secret boundary.")
    for endpoint in (
        "`${apiBase}/health/ready`",
        "`${apiBase}/v1/runtime-packages/template`",
        "`${apiBase}/v1/runtime-packages/preview`",
        "`${apiBase}/v1/runtime-packages/download`",
    ):
        if endpoint not in setup_script:
            raise SystemExit(f"The setup wizard is missing endpoint {endpoint!r}.")
    if "browserPrincipal()" not in setup_script:
        raise SystemExit("The setup wizard must isolate its browser principal.")
    if "env://${elements.secretName.value.trim()}" not in setup_script:
        raise SystemExit("The setup wizard must convert the secret name into an env reference.")

    match = re.fullmatch(
        r"window\.T2D_PUBLIC_API_BASE_URL = (.+);\n?",
        config,
    )
    if match is None:
        raise SystemExit("config.js does not match the expected assignment format.")
    value = json.loads(match.group(1))
    if not isinstance(value, str):
        raise SystemExit("The public API base URL must be a string.")
    if value:
        public_api = urlsplit(value)
        if (
            public_api.scheme != "https"
            or not public_api.netloc
            or public_api.username is not None
            or public_api.password is not None
            or public_api.query
            or public_api.fragment
        ):
            raise SystemExit(
                "The configured public API base URL must be an HTTPS URL without credentials, "
                "a query, or a fragment."
            )

    print("GitHub Pages product showcase and setup validation passed.")
    print(f"Verified preview: {current_total:,} versus {previous_total:,} ({percentage:+.2f}%).")
    print(f"Configured public API: {value or 'not set'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
