#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f docker-compose.yml -f compose.auth.yml --profile models)
case "${1:-start}" in
  start) "${compose[@]}" up -d ;;
  stop) "${compose[@]}" down ;;
  status) "${compose[@]}" ps ;;
  logs) "${compose[@]}" logs -f backend worker ;;
  test) "${compose[@]}" run --rm --no-deps backend python tests/auth_test.py ;;
  *) echo 'Usage: bash scripts/homeflow.sh start|stop|status|logs|test'; exit 1 ;;
esac
