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
  *) echo 'Usage: bash scripts/homeflow.sh start|stop|status|logs|test|test-db'; exit 1 ;;
esac
