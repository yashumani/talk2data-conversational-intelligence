from __future__ import annotations

import json
import re
from pathlib import Path

SITE = Path("site")
REQUIRED = [
    SITE / "index.html",
    SITE / "app.js",
    SITE / "config.js",
    SITE / ".nojekyll",
    SITE / "demo" / "index.html",
]


def main() -> int:
    missing = [str(path) for path in REQUIRED if not path.exists()]
    if missing:
        raise SystemExit("Missing GitHub Pages assets: " + ", ".join(missing))

    html = (SITE / "index.html").read_text(encoding="utf-8")
    script = (SITE / "app.js").read_text(encoding="utf-8")
    config = (SITE / "config.js").read_text(encoding="utf-8")

    for marker in (
        "Talk2Data",
        "Verification panel",
        "Pages hosts the interface",
        "./config.js",
        "./app.js",
    ):
        if marker not in html:
            raise SystemExit(f"Required page marker is missing: {marker!r}")

    if 'fetch("/v1/' in script or "fetch('/v1/" in script:
        raise SystemExit("Static client must use the configured API base URL.")
    if "`${apiBase}/v1/chat/demo`" not in script:
        raise SystemExit("Static client is missing the governed chat endpoint.")
    if "`${apiBase}/health/ready`" not in script:
        raise SystemExit("Static client is missing the runtime readiness check.")

    match = re.fullmatch(
        r"window\.T2D_PUBLIC_API_BASE_URL = (.+);\n?",
        config,
    )
    if match is None:
        raise SystemExit("config.js does not match the expected assignment format.")
    value = json.loads(match.group(1))
    if not isinstance(value, str):
        raise SystemExit("The public API base URL must be a string.")

    print("GitHub Pages static site validation passed.")
    print(f"Configured public API: {value or 'not set'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
