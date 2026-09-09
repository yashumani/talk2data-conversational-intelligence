#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
mkdir -p .talk2data

python scripts/dependencies.py install dev

docker version >/dev/null
docker compose version >/dev/null
python scripts/validate_codespaces_config.py

cat <<'EOF'
Talk2Data Codespaces setup completed.

The standalone CSV workspace starts automatically after the container opens:
  - React workspace and Talk2Data API: port 8000
  - No GCP, database credential, or model download required

Startup logs:
  tail -f .talk2data/codespaces-startup.log
EOF
