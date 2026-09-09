#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
mkdir -p .talk2data

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-talk2data-codespaces}"

docker compose \
  -f docker-compose.csv-demo.yml \
  -f .devcontainer/docker-compose.codespaces.yml \
  up -d --build --remove-orphans

if [[ -f .talk2data/codespaces-wait.pid ]] && kill -0 "$(cat .talk2data/codespaces-wait.pid)" 2>/dev/null; then
  exit 0
fi

nohup bash .devcontainer/wait-for-runtime.sh \
  > .talk2data/codespaces-startup.log 2>&1 &
echo "$!" > .talk2data/codespaces-wait.pid

echo "Talk2Data is starting. Follow progress with:"
echo "  tail -f .talk2data/codespaces-startup.log"
