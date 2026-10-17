#!/usr/bin/env bash
# Phase 1 stub: local dev server health and API routes.
# Deployed /app check: DH_BASE=http://$APP_HOST/app bash scripts/smoke.sh
# BASE is accepted as an alias for the same URL.
set -euo pipefail

if [ -n "${DH_BASE:-}" ]; then
  BASE="${DH_BASE}"
elif [ -z "${BASE:-}" ]; then
  BASE="http://127.0.0.1:${DH_PORT:-8000}"
fi

check() {
  local path="$1"
  curl -fsS "${BASE}${path}" >/dev/null
  echo "ok ${BASE}${path}"
}

check "/health"
check "/api/health"
check "/api/clips"
check "/api/leaderboard"
