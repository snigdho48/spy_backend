#!/usr/bin/env bash
# Daily updater for the TX6. Quiet when origin/master is already the deployed SHA.
# On failure, deploy-spy.sh rolls back; this script retries rollback if a swap
# was left in progress, then exits non-zero. Log: $HOME/.cache/spy-backend/watcher.log
set -euo pipefail

APP_DIR="${SPY_APP_DIR:-$HOME/apps/spy-backend}"
CACHE_DIR="${SPY_CACHE_DIR:-$HOME/.cache/spy-backend}"
LOG="${SPY_WATCHER_LOG:-$CACHE_DIR/watcher.log}"
MAX_FAILS="${SPY_WATCHER_MAX_FAILS:-5}"

# stdout: skip or run
# $1 deployed sha, $2 origin sha, $3 fail sha, $4 fail count, $5 max fails (0 = unlimited)
watcher_decision() {
  local deployed=${1:-}
  local origin=${2:-}
  local fsha=${3:-}
  local fcount=${4:-0}
  local max=${5:-5}
  if [[ -n "$deployed" && "$deployed" == "$origin" ]]; then
    printf '%s\n' skip
    return 0
  fi
  if [[ "$max" != "0" && -n "$fsha" && "$fsha" == "$origin" && "$fcount" -ge "$max" ]]; then
    printf '%s\n' skip
    return 0
  fi
  printf '%s\n' run
}

rotate_log() {
  local size=0
  if [[ -f "$LOG" ]]; then
    size="$(stat -c%s "$LOG" 2>/dev/null || echo 0)"
  fi
  if [[ "$size" -gt 1048576 ]]; then
    mv "$LOG" "$LOG.1"
  fi
}

read_fail_state() {
  FAIL_SHA=""
  FAIL_COUNT=0
  if [[ -f "$CACHE_DIR/fail-state" ]]; then
    read -r FAIL_SHA FAIL_COUNT <"$CACHE_DIR/fail-state" || true
    FAIL_COUNT="${FAIL_COUNT:-0}"
    if ! [[ "$FAIL_COUNT" =~ ^[0-9]+$ ]]; then
      FAIL_COUNT=0
    fi
  fi
}

record_failure() {
  local target=$1
  local count=1
  read_fail_state
  if [[ "$FAIL_SHA" == "$target" ]]; then
    count=$((FAIL_COUNT + 1))
  fi
  mkdir -p "$CACHE_DIR"
  printf '%s %s\n' "$target" "$count" >"$CACHE_DIR/fail-state"
}

run_update() {
  local rc=0 target deploy
  mkdir -p "$CACHE_DIR"
  rotate_log
  exec 4>&2
  exec >>"$LOG" 2>&1
  echo "=== $(date -Is) deploy --update ==="
  target="$(git -C "$APP_DIR" rev-parse origin/master)"
  deploy="$APP_DIR/infra/deploy/deploy-spy.sh"
  set +e
  bash "$deploy" --update
  rc=$?
  set -e
  if [[ "$rc" -eq 0 ]]; then
    rm -f "$CACHE_DIR/fail-state"
    echo "=== $(date -Is) update succeeded ==="
    exit 0
  fi
  if [[ "$rc" -eq 75 ]]; then
    echo "=== $(date -Is) deploy lock busy; left the stack as-is ==="
    exit 0
  fi
  echo "=== $(date -Is) deploy failed rc=${rc} ==="
  if [[ "$rc" -ne 76 && -f "$CACHE_DIR/swap-started" ]]; then
    echo "Swap marker is still present. Running deploy-spy.sh --rollback."
    set +e
    bash "$deploy" --rollback
    local rollback_rc=$?
    set -e
    if [[ "$rollback_rc" -ne 0 ]]; then
      echo "ROLLBACK FAILED rc=${rollback_rc}"
    else
      echo "Rollback health check passed."
    fi
  fi
  if [[ "$rc" -ne 76 ]]; then
    record_failure "$target"
  fi
  echo "spy-watcher: update failed rc=${rc}; see ${LOG}" >&4
  exit "$rc"
}

main() {
  local origin deployed decision
  if [[ "${1:-}" == "--run" ]]; then
    run_update
  fi
  if [[ ! -d "$APP_DIR/.git" ]]; then
    echo "spy-watcher: ${APP_DIR} is not a checkout. Run deploy-spy.sh first." >&2
    exit 1
  fi
  mkdir -p "$CACHE_DIR"
  if ! git -C "$APP_DIR" fetch origin master; then
    rotate_log
    echo "$(date -Is) git fetch failed" >>"$LOG"
    echo "spy-watcher: git fetch failed; see ${LOG}" >&2
    exit 1
  fi
  origin="$(git -C "$APP_DIR" rev-parse origin/master)"
  deployed=""
  if [[ -f "$CACHE_DIR/deployed-sha" ]]; then
    deployed="$(tr -d '[:space:]' <"$CACHE_DIR/deployed-sha")"
  fi
  read_fail_state
  decision="$(watcher_decision "$deployed" "$origin" "$FAIL_SHA" "$FAIL_COUNT" "$MAX_FAILS")"
  if [[ "$decision" == "skip" ]]; then
    exit 0
  fi
  git -C "$APP_DIR" pull --ff-only origin master
  exec "$APP_DIR/infra/deploy/spy-watcher.sh" --run
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
