#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

base_url="http://127.0.0.1:8000"
runtime_url="${base_url}/demo"

if [[ -n "${CODESPACE_NAME:-}" && -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]]; then
  runtime_url="https://${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/demo"
fi

for attempt in $(seq 1 180); do
  if curl -fsS "${base_url}/health/ready" >/tmp/talk2data-ready.json 2>/dev/null; then
    python - <<PY
import json
from pathlib import Path

body = json.loads(Path("/tmp/talk2data-ready.json").read_text(encoding="utf-8"))
payload = {
    "status": body.get("status"),
    "url": "${runtime_url}",
    "attempt": ${attempt},
}
Path(".talk2data/codespaces-runtime.json").write_text(
    json.dumps(payload, indent=2) + "\n",
    encoding="utf-8",
)
PY
    echo
    echo "Talk2Data full runtime is ready."
    echo "Open: ${runtime_url}"
    echo "API docs: ${runtime_url%/demo}/docs"
    exit 0
  fi

  if (( attempt % 12 == 0 )); then
    echo "Still starting Talk2Data (attempt ${attempt}/180)."
    docker compose \
      -f docker-compose.yml \
      -f .devcontainer/docker-compose.codespaces.yml \
      ps || true
  fi
  sleep 5
done

echo "Talk2Data did not become ready within 15 minutes."
docker compose \
  -f docker-compose.yml \
  -f .devcontainer/docker-compose.codespaces.yml \
  ps || true
docker compose \
  -f docker-compose.yml \
  -f .devcontainer/docker-compose.codespaces.yml \
  logs --tail=250 || true
exit 1
