#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT}"

mapfile -t CONFIG_FILES < <(find /config -maxdepth 1 -type f -name '*.config' 2>/dev/null | sort)
if [ "${#CONFIG_FILES[@]}" -ne 1 ]; then
  echo "error: expected exactly one /config/*.config, found ${#CONFIG_FILES[@]}" >&2
  exit 2
fi
CONFIG_FILE="${CONFIG_FILES[0]}"

read_config() {
  local key="$1"
  grep -E "^${key}=" "${CONFIG_FILE}" | head -n1 | cut -d= -f2-
}

USERNAME="$(read_config USERNAME)"
INGRESS_URL="$(read_config INGRESS_URL)"
PASSWORD="$(read_config PASSWORD)"

if [ -z "${USERNAME}" ] || [ -z "${INGRESS_URL}" ] || [ -z "${PASSWORD}" ]; then
  echo "error: ${CONFIG_FILE} must set USERNAME, INGRESS_URL and PASSWORD" >&2
  exit 2
fi

NS="${USERNAME}"
KUBECONFIG="/config/${NS}-k8s.yaml"
export KUBECONFIG
if [ ! -f "${KUBECONFIG}" ]; then
  echo "error: kubeconfig not found: ${KUBECONFIG}" >&2
  exit 2
fi

TEAM_N="${USERNAME#team-}"
APP_HOST="video-lab-team-${TEAM_N}.cosmos.vastdata.com"
APP_NAME="developing-hazard"

if [ -x "${ROOT}/.venv/bin/python" ]; then
  PYTHON="${ROOT}/.venv/bin/python"
else
  PYTHON="python3"
fi
"${PYTHON}" -m dh.snapshot

ARCHIVE="$(mktemp --suffix=.tar.gz)"
tar -C "${ROOT}/data/snapshot" -czf "${ARCHIVE}" .
trap 'rm -f "${MANIFEST:-}" "${ARCHIVE}"' EXIT

# Client-side apply stores the whole object in an annotation capped at 256 KB.
# The pod bundle is larger than that, so the code ConfigMap uses server-side apply.
kubectl -n "${NS}" create configmap "${APP_NAME}-code" \
  --from-file=app.tar.gz="${ARCHIVE}" \
  --dry-run=client -o yaml | kubectl apply --server-side --force-conflicts -f -

kubectl -n "${NS}" create secret generic "${APP_NAME}-vss-creds" \
  --from-literal=VSS_URL="${INGRESS_URL}" \
  --from-literal=VSS_USERNAME="${USERNAME}" \
  --from-literal=VSS_PASSWORD="${PASSWORD}" \
  --dry-run=client -o yaml | kubectl apply -f -

MANIFEST="$(mktemp)"
trap 'rm -f "${MANIFEST}" "${ARCHIVE}"' EXIT
sed -e "s/NS_PLACEHOLDER/${NS}/g" -e "s/APP_HOST_PLACEHOLDER/${APP_HOST}/g" \
  deploy/k8s.yaml > "${MANIFEST}"
kubectl apply -f "${MANIFEST}"

kubectl -n "${NS}" rollout restart "deploy/${APP_NAME}"
kubectl -n "${NS}" rollout status "deploy/${APP_NAME}" --timeout=180s

# Ingress endpoints lag the readiness probe. Retry before failing the script.
health_url="http://${APP_HOST}/app/health"
ok=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "${health_url}"; then
    ok=1
    break
  fi
  sleep 3
done
echo
if [ "${ok}" -ne 1 ]; then
  echo "error: ${health_url} did not return 200" >&2
  exit 1
fi

echo "Open https://workshop.thecosmoslabs.com and click the App button."
