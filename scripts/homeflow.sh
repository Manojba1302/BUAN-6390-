#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f docker-compose.yml -f compose.auth.yml --profile models)
case "${1:-start}" in
  start) "${compose[@]}" up -d ;;
  stop) "${compose[@]}" down ;;
  status) "${compose[@]}" ps ;;
  logs) "${compose[@]}" logs -f backend worker ;;
  test) "${compose[@]}" run --rm --no-deps backend python -m unittest tests.auth_test tests.classifier_test tests.logic_test tests.code_standards_test ;;
  test-db) "${compose[@]}" run --rm -e HOMEFLOW_DB_TEST=1 backend python -m unittest tests.postgres_test ;;
  test-worker) "${compose[@]}" run --rm --no-deps worker python -m unittest discover -s tests ;;
  models) "${compose[@]}" up -d ollama
    for model in gemma3:4b llama3.1:8b nomic-embed-text "${@:2}"; do "${compose[@]}" exec -T ollama ollama pull "$model"; done ;;
  eval) "${compose[@]}" up -d ollama
    "${compose[@]}" run --rm --no-deps worker python -m evaluation.run "${@:2}" ;;
  eval-compare) "${compose[@]}" run --rm --no-deps worker python -m evaluation.compare "${@:2}" ;;
  *) echo 'Usage: bash scripts/homeflow.sh start|stop|status|logs|test|test-db|test-worker|models|eval|eval-compare'; exit 1 ;;
esac
