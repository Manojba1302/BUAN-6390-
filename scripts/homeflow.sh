#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f docker-compose.yml -f compose.auth.yml --profile models)
# Ollama in Docker only when .env points at it; otherwise it runs natively on the host.
docker_ollama() { grep -q '^OLLAMA_BASE_URL=http://ollama:' .env 2>/dev/null; }
case "${1:-start}" in
  start) if docker_ollama; then "${compose[@]}" up -d; else "${compose[@]}" up -d db rabbitmq minio backend worker frontend mailpit; fi ;;
  stop) "${compose[@]}" down ;;
  status) "${compose[@]}" ps ;;
  logs) "${compose[@]}" logs -f backend worker ;;
  test) "${compose[@]}" run --rm --no-deps backend python -m unittest tests.auth_test tests.classifier_test tests.logic_test tests.code_standards_test ;;
  test-db) "${compose[@]}" run --rm -e HOMEFLOW_DB_TEST=1 backend python -m unittest tests.postgres_test ;;
  test-worker) "${compose[@]}" run --rm --no-deps worker python -m unittest discover -s tests ;;
  models) if docker_ollama; then "${compose[@]}" up -d ollama; pull=("${compose[@]}" exec -T ollama ollama pull); else pull=(ollama pull); fi
    for model in gemma3:4b llama3.1:8b nomic-embed-text "${@:2}"; do "${pull[@]}" "$model"; done ;;
  doctor) "${compose[@]}" run --rm --no-deps worker python -m worker.doctor ;;
  eval) if docker_ollama; then "${compose[@]}" up -d ollama; fi
    "${compose[@]}" run --rm --no-deps worker python -m evaluation.run "${@:2}" ;;
  eval-compare) "${compose[@]}" run --rm --no-deps worker python -m evaluation.compare "${@:2}" ;;
  *) echo 'Usage: bash scripts/homeflow.sh start|stop|status|logs|test|test-db|test-worker|models|doctor|eval|eval-compare'; exit 1 ;;
esac
