from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "examples/canvas/ai-studio"


def validate() -> None:
    required = (
        "README.md",
        "index.html",
        "client.mjs",
        "model.mjs",
        "server.mjs",
        "server.test.mjs",
        "package.json",
        "package-lock.json",
    )
    missing = [name for name in required if not (DIRECTORY / name).is_file()]
    if missing:
        raise SystemExit("AI Studio preview is missing: " + ", ".join(missing))
    html = (DIRECTORY / "index.html").read_text()
    server = (DIRECTORY / "server.mjs").read_text()
    client = (DIRECTORY / "client.mjs").read_text()
    for marker in ("api_key", "apikey", "gemini_api_key", "authorization: bearer"):
        if marker in (html + client).lower():
            raise SystemExit(f"Browser assets contain forbidden credential marker: {marker}")
    contracts = (
        "127.0.0.1",
        "maximumRequestBytes",
        "maximumResponseBytes",
        "AbortSignal.timeout",
        "allowedOrigins",
        "inFlight",
        "1024",
        "no-store",
    )
    for contract in contracts:
        if contract not in server:
            raise SystemExit(f"Preview server is missing security contract {contract}")
    if 'src="/client.mjs"' not in html or "<script>" in html.lower():
        raise SystemExit("Preview must use the external same-origin client module")


if __name__ == "__main__":
    validate()
    print("AI Studio preview validation passed: 8 security contracts are present.")
