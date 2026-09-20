from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REMOVED_WORKFLOWS = (
    "demo-final-certification.yml",
    "finalize-demo-slice.yml",
    "publish-huggingface-space.yml",
    "report-demo-certification.yml",
)


def validate() -> None:
    environment = (ROOT / ".env.example").read_text()
    required_environment = (
        "T2D_RUNTIME_PROFILE=disabled",
        "T2D_OLLAMA_ENABLED=false",
        "T2D_PUBLIC_MAXIMUM_REQUEST_BYTES=32768",
        "T2D_PUBLIC_MAXIMUM_RESPONSE_BYTES=262144",
        "T2D_PUBLIC_RESPONSE_TIMEOUT_SECONDS=20",
    )
    for marker in required_environment:
        if marker not in environment:
            raise SystemExit(f".env.example is missing fail-closed marker {marker}")

    for path in (
        "docker-compose.yml",
        "docker-compose.csv-demo.yml",
        ".devcontainer/docker-compose.codespaces.yml",
    ):
        if "T2D_RUNTIME_PROFILE" not in (ROOT / path).read_text():
            raise SystemExit(f"{path} must explicitly opt into a trusted runtime profile")

    workflow_dir = ROOT / ".github/workflows"
    for name in REMOVED_WORKFLOWS:
        if (workflow_dir / name).exists():
            raise SystemExit(f"Unsafe legacy workflow remains in candidate tree: {name}")
    for path in workflow_dir.glob("*.yml"):
        raw = path.read_text()
        if re.search(r"uses:\s+[^\s@]+/[^\s@]+@(?![0-9a-f]{40}(?:\s|$))", raw):
            raise SystemExit(f"{path.name} contains a mutable remote action reference")

    pages = (workflow_dir / "pages.yml").read_text()
    for marker in ("build:pages", "prepare_pages_release.py", "--profile release", "github-pages"):
        if marker not in pages:
            raise SystemExit(f"Pages workflow is missing release contract {marker}")
    if "T2D_PUBLIC_API_BASE_URL" in pages:
        raise SystemExit("Static Pages workflow cannot accept a runtime API URL")

    security = yaml.safe_load((workflow_dir / "security-gates.yml").read_text())
    if set(security["jobs"]) != {"dependency-review", "secret-scan", "container"}:
        raise SystemExit("Security workflow must retain dependency, secret, and container gates")


if __name__ == "__main__":
    validate()
    print("Public security workflow and runtime boundaries validated.")
