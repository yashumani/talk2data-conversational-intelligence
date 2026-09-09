from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEVCONTAINER = ROOT / ".devcontainer" / "devcontainer.json"
OVERRIDE = ROOT / ".devcontainer" / "docker-compose.codespaces.yml"
SETUP = ROOT / ".devcontainer" / "setup.sh"
START = ROOT / ".devcontainer" / "start.sh"
WAIT = ROOT / ".devcontainer" / "wait-for-runtime.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "github-runtime.yml"
CSV_COMPOSE = ROOT / "docker-compose.csv-demo.yml"

EXPECTED_FILES = [DEVCONTAINER, OVERRIDE, SETUP, START, WAIT, WORKFLOW, CSV_COMPOSE]
FORBIDDEN_PATTERNS = [
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    missing = [path.relative_to(ROOT).as_posix() for path in EXPECTED_FILES if not path.is_file()]
    require(not missing, "Missing Codespaces files: " + ", ".join(missing))

    payload = json.loads(DEVCONTAINER.read_text(encoding="utf-8"))
    require(
        payload.get("image", "").startswith("mcr.microsoft.com/devcontainers/python:"),
        "Unexpected image",
    )
    features = payload.get("features", {})
    require(
        "ghcr.io/devcontainers/features/docker-in-docker:2" in features,
        "Docker feature missing",
    )
    require(8000 in payload.get("forwardPorts", []), "Port 8000 must be forwarded")
    require(
        payload.get("postCreateCommand") == "bash .devcontainer/setup.sh",
        "Unexpected setup command",
    )
    require(
        payload.get("postStartCommand") == "bash .devcontainer/start.sh",
        "Unexpected start command",
    )
    port = payload.get("portsAttributes", {}).get("8000", {})
    require(
        port.get("onAutoForward") == "openBrowser",
        "Port 8000 must open automatically",
    )
    require(
        port.get("visibility") == "private",
        "Port 8000 must default to private visibility",
    )

    override = OVERRIDE.read_text(encoding="utf-8")
    require(
        'T2D_CSV_DEMO_ENABLED: "true"' in override,
        "Codespaces must enable the CSV workspace",
    )
    require(
        'T2D_OLLAMA_REQUIRED: "false"' in override,
        "Codespaces must not require a model",
    )

    start = START.read_text(encoding="utf-8")
    require(
        "docker-compose.csv-demo.yml" in start,
        "Startup must use the isolated CSV Docker Compose profile",
    )
    require("wait-for-runtime.sh" in start, "Startup readiness monitor is missing")
    require(
        "--remove-orphans" in start,
        "Startup must remove containers left by an earlier runtime profile",
    )

    waiter = WAIT.read_text(encoding="utf-8")
    require(
        "/health/ready" in waiter,
        "Readiness must use the application health contract",
    )
    require(
        'health_payload.get("status") != "ready"' in waiter,
        "Codespaces must reject a failed readiness payload",
    )
    require("/workspace/" in waiter, "Runtime URL must open the React CSV workspace")

    workflow = WORKFLOW.read_text(encoding="utf-8")
    require(
        'health_payload.get("status") != "ready"' in workflow,
        "GitHub runtime validation must reject a failed readiness payload",
    )

    csv_compose = CSV_COMPOSE.read_text(encoding="utf-8")
    require(
        "payload.get('status') == 'ready'" in csv_compose,
        "The CSV container healthcheck must reject a failed readiness payload",
    )

    for path in EXPECTED_FILES:
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PATTERNS:
            require(
                pattern.search(text) is None,
                f"Potential secret found in {path.relative_to(ROOT)}",
            )

    print("GitHub Codespaces runtime configuration validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
