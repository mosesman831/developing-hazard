#!/usr/bin/env bash
# Scan full git history and the working tree for likely secrets. Exit 1 on a hit.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PATTERNS=(
  'AKIA[0-9A-Z]{16}'
  'sk-[A-Za-z0-9]{20,}'
  'ghp_[A-Za-z0-9]{20,}'
  'gho_[A-Za-z0-9]{20,}'
  'xox[baprs]-[A-Za-z0-9-]{10,}'
  'BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY'
  'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'
  'PASSWORD=[^$[:space:]]{8,}'
  'WANDB_API_KEY=[^$[:space:]]+'
  'api_key[[:space:]]*=[[:space:]]*[^$[:space:]][^[:space:]]{7,}'
  'Bearer [A-Za-z0-9._-]{20,}'
  'current-context:[[:space:]]*[A-Za-z0-9._-]+'
)

SKIP_PATH_RE='(\.venv/|__pycache__/|\.egg-info/|/config$|\.env$|secret_scan\.sh)'

redact() {
  local value="$1"
  local len=${#value}
  if (( len <= 8 )); then
    printf '%s…' "${value:0:4}"
  else
    printf '%s…' "${value:0:8}"
  fi
}

scan_text() {
  local label="$1"
  local text="$2"
  local hit=0
  for pattern in "${PATTERNS[@]}"; do
    while IFS= read -r match; do
      [[ -z "$match" ]] && continue
      if [[ "$match" == *fixture* ]] || [[ "$match" == *'_require'* ]] || [[ "$match" == *'${'* ]]; then
        continue
      fi
      printf 'SECRET_HIT %s pattern=%s redacted=%s\n' "$label" "$pattern" "$(redact "$match")"
      hit=1
    done < <(grep -Eo -e "$pattern" <<<"$text" 2>/dev/null || true)
  done
  if (( hit )); then
    return 0
  fi
  return 1
}

HITS=0
FILES_SCANNED=0

while IFS= read -r -d '' path; do
  if [[ "$path" =~ $SKIP_PATH_RE ]]; then
    continue
  fi
  FILES_SCANNED=$((FILES_SCANNED + 1))
  if scan_text "worktree:$path" "$(cat "$path")"; then
    HITS=1
  fi
done < <(git ls-files -z)

while IFS= read -r commit; do
  [[ -z "$commit" ]] && continue
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    if [[ "$path" =~ $SKIP_PATH_RE ]]; then
      continue
    fi
    patch="$(git show "$commit" -p --no-color -- "$path" 2>/dev/null || true)"
    if scan_text "commit:$commit file:$path" "$patch"; then
      HITS=1
    fi
  done < <(git diff-tree --no-commit-id --name-only -r "$commit" 2>/dev/null || true)
done < <(git rev-list --all)

printf 'secret_scan: files_scanned=%s hits=%s\n' "$FILES_SCANNED" "$HITS"
if (( HITS != 0 )); then
  exit 1
fi
exit 0
