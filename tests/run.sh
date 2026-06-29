#!/usr/bin/env bash
#
# End-to-end test runner: brings up the isolated test stack, runs all four
# test layers, tears down. Designed to be idempotent and CI-safe.
#
# Flags:
#   --no-up      skip docker compose up (assume infra already running)
#   --no-down    skip docker compose down (leave infra running for debugging)
#   --only LAYER run a single layer: unit-backend | int-backend | unit-frontend | e2e
#
set -euo pipefail
cd "$(dirname "$0")/.."         # repo root (the databricks_cost_app/ folder)

UP=true
DOWN=true
ONLY=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-up)   UP=false; shift;;
        --no-down) DOWN=false; shift;;
        --only)    ONLY="$2"; shift 2;;
        *)         echo "Unknown flag: $1"; exit 2;;
    esac
done

COMPOSE="docker compose -f tests/docker-compose.test.yml"

run_layer() {
    local layer="$1"
    if [[ -n "$ONLY" && "$ONLY" != "$layer" ]]; then
        return 0
    fi
    case "$layer" in
        unit-backend)
            echo "========== Backend unit tests =========="
            (cd tests/backend && python -m pytest unit/ -v)
            ;;
        int-backend)
            echo "========== Backend integration tests =========="
            (cd tests/backend && python -m pytest integration/ -v)
            ;;
        unit-frontend)
            echo "========== Frontend unit tests =========="
            (cd tests/frontend && npm run test:run)
            ;;
        e2e)
            echo "========== End-to-end tests =========="
            (cd tests/e2e && npx playwright test)
            ;;
    esac
}

if $UP; then
    echo "▸ Bringing up test infrastructure..."
    $COMPOSE up -d --build
    echo "▸ Waiting for backend health..."
    for i in $(seq 1 60); do
        if curl -sf http://localhost:58000/health > /dev/null 2>&1; then
            echo "  backend ready (${i}s)"
            break
        fi
        sleep 1
    done
fi

trap 'EXIT=$?; if $DOWN; then echo "▸ Tearing down..."; $COMPOSE down -v; fi; exit $EXIT' EXIT

run_layer unit-backend
run_layer int-backend
run_layer unit-frontend
run_layer e2e

echo "✅ All test layers passed."
