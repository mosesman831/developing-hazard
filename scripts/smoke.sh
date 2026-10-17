#!/usr/bin/env bash
# Hit every AG3 endpoint once.
# Deployed check: DH_BASE=http://video-lab-team-36.cosmos.vastdata.com/app bash scripts/smoke.sh
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
check "/api/runs"
check "/api/leaderboard"

CLIP="$(curl -fsS "${BASE}/api/clips" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["clip_id"])')"
RUN="$(curl -fsS "${BASE}/api/runs" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(rows[0]["run_id"] if rows else "")')"

check "/api/clips/${CLIP}"
check "/api/clips/${CLIP}?blind=1"
check "/api/clips/${CLIP}/tracks"

SOURCE="$(curl -fsS "${BASE}/api/clips/${CLIP}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["segments"][0]["source"])')"
ENCODED="$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "${SOURCE}")"
code="$(curl -sS -o /tmp/dh-smoke-video.bin -w '%{http_code}' -H 'Range: bytes=0-15' "${BASE}/video?source=${ENCODED}")"
if [ "${code}" != "200" ] && [ "${code}" != "206" ]; then
  echo "error: video returned ${code}" >&2
  exit 1
fi
echo "ok ${BASE}/video ${code}"

if [ -n "${RUN}" ]; then
  check "/api/runs/${RUN}"
  check "/api/runs/${RUN}/stream?clip=${CLIP}"
  code="$(curl -sS -o /tmp/dh-smoke-explain.json -w '%{http_code}' -X POST "${BASE}/api/explain/${RUN}/c03_h1")"
  if [ "${code}" != "200" ]; then
    echo "error: explain returned ${code}" >&2
    exit 1
  fi
  echo "ok POST ${BASE}/api/explain/${RUN}/c03_h1"
fi

curl -fsS -X POST "${BASE}/api/human" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"smoke\",\"role\":\"team\",\"blind\":true,\"clip_id\":\"${CLIP}\",\"clicks\":[1.0]}" \
  >/tmp/dh-smoke-human.json
python3 -c 'import json; body=json.load(open("/tmp/dh-smoke-human.json")); assert isinstance(body["clip_score"], int)'
echo "ok POST ${BASE}/api/human"

MODE="$(curl -fsS "${BASE}/api/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["mode"])')"
if [ "${MODE}" = "demo" ]; then
  code="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "${BASE}/api/runs" \
    -H 'Content-Type: application/json' \
    -d '{"agent":"yolo_risk","config":{},"testset_id":"testset_v0","latency_mode":"zero"}')"
  if [ "${code}" != "404" ]; then
    echo "error: demo POST /api/runs returned ${code}" >&2
    exit 1
  fi
  echo "ok POST ${BASE}/api/runs demo 404"
fi
