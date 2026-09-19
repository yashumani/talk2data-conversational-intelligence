from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FORBIDDEN = (
    "fetch(",
    "XMLHttpRequest",
    "WebSocket",
    "localStorage",
    "sessionStorage",
    "/v1/",
    "apiBase",
    "api_key",
)
ARTIFACT_FORBIDDEN = ("/v1/", "apiBase", "api_key", "localStorage", "sessionStorage")


def files_under(path: Path) -> list[Path]:
    return sorted(item for item in path.rglob("*") if item.is_file())


def validate_source() -> None:
    html = (ROOT / "apps/web/pages/index.html").read_text()
    if "connect-src 'none'" not in html:
        raise SystemExit("Dedicated Pages entry must disable all network connections")
    if (ROOT / "site/release.json").exists():
        raise SystemExit("Generated site/release.json must not exist in the source profile")
    gallery_sources = [
        ROOT / "apps/web/pages/index.html",
        *files_under(ROOT / "apps/web/src/gallery"),
        *files_under(ROOT / "apps/web/src/visualizations"),
    ]
    source = "\n".join(path.read_text(errors="replace") for path in gallery_sources)
    for marker in SOURCE_FORBIDDEN:
        if marker.lower() in source.lower():
            raise SystemExit(f"Pages source contains forbidden marker: {marker}")


def validate_release(source_sha: str) -> None:
    site = ROOT / "site"
    receipt = json.loads((site / "release.json").read_text())
    if receipt != {"source_sha": source_sha, "version": (ROOT / "VERSION").read_text().strip()}:
        raise SystemExit("Pages release receipt does not exactly match candidate SHA and version")
    if not (site / "licenses/LICENSE").is_file() or not (site / "licenses/THIRD_PARTY_NOTICES.md").is_file():
        raise SystemExit("Pages release must include license notices")
    workspace = site / "workspace"
    if not (workspace / "index.html").is_file():
        raise SystemExit("Dedicated Pages workspace build is missing")
    texts = []
    for path in files_under(workspace):
        if path.suffix in {".html", ".js", ".css", ".json"}:
            texts.append(path.read_text(errors="replace"))
    combined = "\n".join(texts)
    # React DOM contains a same-origin preload fallback that spells `fetch`. The enforced CSP
    # blocks connections; source validation above separately rejects network-client code owned
    # by this gallery. The compiled scan focuses on application API and persistence markers.
    for marker in ARTIFACT_FORBIDDEN:
        if marker.lower() in combined.lower():
            raise SystemExit(f"Compiled Pages artifact contains forbidden marker: {marker}")
    javascript = b"".join(path.read_bytes() for path in files_under(workspace) if path.suffix == ".js")
    if len(javascript) > 1_000_000 or len(gzip.compress(javascript, mtime=0)) > 350_000:
        raise SystemExit("Compiled Pages JavaScript exceeds the release budget")
    if len(re.findall(r"Static visualization gallery", combined)) != 1:
        raise SystemExit("Dedicated gallery sentinel must occur exactly once")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("source", "release"), default="source")
    parser.add_argument("--source-sha")
    args = parser.parse_args()
    if args.profile == "source":
        validate_source()
        print("GitHub Pages static source validation passed (no network client).")
    else:
        if args.source_sha is None:
            raise SystemExit("--source-sha is required for the release profile")
        validate_release(args.source_sha)
        print("GitHub Pages exact-SHA release validation passed.")
