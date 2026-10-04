#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo 'Install and start Docker Desktop / Docker Engine with Compose first.'; exit 1; }
docker info --format '{{.ServerVersion}}'
docker compose version
[ -f .env ] || cp .env.example .env
compose=(docker compose -f docker-compose.yml -f compose.auth.yml --profile models)
"${compose[@]}" config --quiet
if [ "${1:-}" != '--skip-models' ]; then
  "${compose[@]}" up -d ollama
  ready=false
  for attempt in $(seq 1 30); do
    if "${compose[@]}" exec -T ollama ollama list >/dev/null 2>&1; then ready=true; break; fi
    sleep 1
  done
  [ "$ready" = true ] || { echo 'Ollama did not start. Check its logs.'; exit 1; }
  for model in gemma3:4b llama3.1:8b nomic-embed-text; do
    "${compose[@]}" exec -T ollama ollama pull "$model"
  done
else
  echo 'Models skipped: AI processing will be unavailable until downloaded.'
fi
"${compose[@]}" up --build -d
echo 'App: http://localhost:5173 | Reset emails: http://localhost:8025'

