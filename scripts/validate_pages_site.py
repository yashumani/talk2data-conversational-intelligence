from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path

SITE = Path("site")
SETUP = SITE / "setup"
REQUIRED = [
    SITE / "index.html",
    SITE / "app.js",
    SITE / "config.js",
    SITE / ".nojekyll",
    SITE / "demo" / "index.html",
    SETUP / "index.html",
    SETUP / "styles.css",
    SETUP / "app.js",
    SETUP / "templates" / "telecom-domain-pack.yaml",
]

CODESPACES_URL = (
    "https://codespaces.new/yashumani/talk2data-conversational-intelligence"
    "?ref=feat%2Fgithub-native-runtime&quickstart=1"
)


def main() -> int:
    missing = [str(path) for path in REQUIRED if not path.exists()]
    if missing:
        raise SystemExit("Missing GitHub Pages assets: " + ", ".join(missing))

    html = (SITE / "index.html").read_text(encoding="utf-8")
    normalized_html = unescape(html)
    script = (SITE / "app.js").read_text(encoding="utf-8")
    config = (SITE / "config.js").read_text(encoding="utf-8")

    for marker in (
        "Talk2Data",
        "Verification panel",
        "Complete runtime",
        "Run Talk2Data now",
        CODESPACES_URL,
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
    if "browserPrincipal()" not in script:
        raise SystemExit("The public client must isolate its synthetic browser principal.")

    setup_html = (SETUP / "index.html").read_text(encoding="utf-8")
    setup_script = (SETUP / "app.js").read_text(encoding="utf-8")
    for marker in (
        "GitHub-first tenant generator",
        "Credential-free builder",
        "Download runtime package",
        "Semantic-to-physical mapping",
        "Secret environment variable",
    ):
        if marker not in setup_html:
            raise SystemExit(f"Required setup marker is missing: {marker!r}")
    for marker in (
        "makeZip(files)",
        "env://",
        "checksums.json",
        "docker-compose.yml",
        "telecom-domain-pack.yaml",
        "ghcr.io/yashumani/talk2data-conversational-intelligence:main",
    ):
        if marker not in setup_script:
            raise SystemExit(f"Required setup implementation marker is missing: {marker!r}")
    if 'type="password"' in setup_html.lower():
        raise SystemExit("The public setup wizard must not collect database passwords.")
    if "postgresql://" in setup_script:
        raise SystemExit("The public setup wizard must not embed a database DSN.")

    match = re.fullmatch(
        r"window\.T2D_PUBLIC_API_BASE_URL = (.+);\n?",
        config,
    )
    if match is None:
        raise SystemExit("config.js does not match the expected assignment format.")
    value = json.loads(match.group(1))
    if not isinstance(value, str):
        raise SystemExit("The public API base URL must be a string.")

    print("GitHub Pages runtime launcher and setup generator validation passed.")
    print(f"Configured public API: {value or 'not set'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
