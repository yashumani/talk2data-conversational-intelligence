#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
mkdir -p .talk2data

python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

docker version >/dev/null
docker compose version >/dev/null
python scripts/validate_codespaces_config.py

cat <<'EOF'
Talk2Data Codespaces setup completed.

The full runtime starts automatically after the container opens:
  - Talk2Data UI/API: port 8000
  - Ollama: port 11434
  - Default Codespaces model: qwen3:0.6b

Startup logs:
  tail -f .talk2data/codespaces-startup.log
EOF
