#!/usr/bin/env bash
set -euo pipefail

MODEL="${T2D_OLLAMA_MODEL:-qwen3:8b}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed or is not on PATH." >&2
  exit 1
fi

ollama pull "$MODEL"
echo "Ollama model ready: $MODEL"
