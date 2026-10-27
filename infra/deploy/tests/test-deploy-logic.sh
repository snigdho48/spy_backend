#!/usr/bin/env bash
# Logic tests for the TX6 deploy scripts. No Docker daemon required.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# --- static checks ----------------------------------------------------------
example="$ROOT/infra/env/prod.env.example"
prod="$ROOT/infra/docker-compose.prod.yml"
overlay="$ROOT/infra/docker-compose.prod.test.yml"
deploy="$ROOT/infra/deploy/deploy-spy.sh"

grep -q '__CHANGE_ME__' "$example" || fail "example is missing placeholders"
if grep -Eq 'SECRET_KEY=[A-Za-z0-9]{16,}' "$example"; then
  fail "example contains a real-looking SECRET_KEY"
fi
# shellcheck disable=SC2016 # Literal compose text, not a shell expansion.
grep -q 'container_name: ${SPY_NGINX_CONTAINER:-spy-nginx}' "$prod" || fail "nginx is not named spy-nginx"
grep -q 'image: mariadb:11.4' "$prod" || fail "prod db is not mariadb 11.4"
grep -q 'allkeys-lru' "$prod" || fail "redis policy missing"
grep -q 'innodb-buffer-pool-size=256M' "$prod" || fail "buffer pool missing"
grep -q 'name: snigdho-net' "$prod" || fail "external network missing"
grep -q 'external: true' "$prod" || fail "snigdho-net is not external"
grep -q 'platform: linux/arm64' "$prod" || fail "arm64 platform missing"
grep -q 'pull_policy: never' "$prod" || fail "api image should not be pulled from a registry"
if grep -Eq 'prometheus|grafana|mysql:8' "$prod"; then
  fail "prod compose pulls in dev-only services"
fi
if grep -Eq '^[[:space:]]+ports:' "$prod"; then
  fail "prod compose publishes a host port"
fi
grep -q 'exclude-from-test' "$overlay" || fail "test overlay still starts celery"
grep -q '!override' "$overlay" || fail "test nginx can stay on snigdho-net"
grep -q 'spy-test-nginx' "$overlay" || fail "test nginx name missing"
grep -q 'http://spy-nginx:80' "$ROOT/infra/deploy/README.md" || fail "runbook missing tunnel URL"
grep -q 'http://spy-nginx:80' "$ROOT/README.md" || fail "root README missing tunnel URL"
if grep -E 'docker[[:space:]]+(stop|rm|restart|kill)[[:space:]]+snigdho' "$deploy" "$ROOT/infra/deploy/spy-watcher.sh"; then
  fail "script stops a portfolio container"
fi
grep -q 'spy-api:previous' "$deploy" || fail "rollback tag missing"
grep -q 'docker tag spy-api:previous spy-api:latest' "$deploy" || fail "rollback does not retag previous"

python3 - <<'PY'
token_ready = b'"status":"ready"'
token_alive = b'"status":"alive"'
assert token_ready in b'{"status":"ready"}'
assert token_ready not in b'{"status":"not_ready"}'
assert token_alive in b'{"status":"alive"}'
assert b'"status": "ready"' not in b'{"status": "not_ready"}'
PY

printf '%s' '{"status":"not_ready"}' >"$tmp/body"
if grep -E -q '"status"[[:space:]]*:[[:space:]]*"ready"' "$tmp/body"; then
  fail "ready regex matches not_ready"
fi
printf '%s' '{"status":"ready"}' >"$tmp/body"
grep -E -q '"status"[[:space:]]*:[[:space:]]*"ready"' "$tmp/body" || fail "compact ready regex"
printf '%s' '{"status": "ready"}' >"$tmp/body"
grep -E -q '"status"[[:space:]]*:[[:space:]]*"ready"' "$tmp/body" || fail "spaced ready regex"

if git -C "$ROOT" check-ignore -q infra/env/prod.env.example; then
  fail "prod.env.example is gitignored"
fi

# --- source scripts ---------------------------------------------------------
export SPY_APP_DIR="$tmp/app"
export SPY_CACHE_DIR="$tmp/cache"
export SPY_ENV_FILE="$tmp/prod.env"
export SPY_ENV_EXAMPLE="$ROOT/infra/env/prod.env.example"
mkdir -p "$tmp/app/infra/nginx" "$tmp/cache"
git -C "$tmp/app" init -b master >/dev/null
git -C "$tmp/app" config user.email "deploy-test@example.com"
git -C "$tmp/app" config user.name "deploy-test"
printf '%s\n' "old compose" >"$tmp/app/infra/docker-compose.prod.yml"
printf '%s\n' "old nginx" >"$tmp/app/infra/nginx/nginx.prod.conf"
git -C "$tmp/app" add infra
git -C "$tmp/app" commit -m old >/dev/null
old_sha="$(git -C "$tmp/app" rev-parse HEAD)"
printf '%s\n' "new compose" >"$tmp/app/infra/docker-compose.prod.yml"
printf '%s\n' "new nginx" >"$tmp/app/infra/nginx/nginx.prod.conf"
git -C "$tmp/app" add infra
git -C "$tmp/app" commit -m new >/dev/null
printf '%s\n' "$old_sha" >"$tmp/cache/previous-sha"

# shellcheck disable=SC1091
source "$ROOT/infra/deploy/spy-watcher.sh"
# shellcheck disable=SC1091
source "$ROOT/infra/deploy/deploy-spy.sh"

[[ "$(watcher_decision abc abc '' 0 5)" == "skip" ]] || fail "equal sha should skip"
[[ "$(watcher_decision abc def '' 0 5)" == "run" ]] || fail "new sha should run"
[[ "$(watcher_decision old new new 5 5)" == "skip" ]] || fail "fail cap should skip"
[[ "$(watcher_decision old new new 4 5)" == "run" ]] || fail "under cap should run"
[[ "$(watcher_decision old new new 9 0)" == "run" ]] || fail "max 0 should not cap"

# Portfolio mutations are refused before docker is invoked.
set +e
( refuse_portfolio_docker_args stop snigdho-tunnel >/dev/null )
rc=$?
set -e
[[ "$rc" -ne 0 ]] || fail "stop snigdho-tunnel was allowed"
set +e
( refuse_portfolio_docker_args network rm snigdho-net >/dev/null )
rc=$?
set -e
[[ "$rc" -ne 0 ]] || fail "network rm snigdho-net was allowed"
refuse_portfolio_docker_args inspect snigdho-tunnel
refuse_portfolio_docker_args exec spy-nginx wget

# Missing tunnel.
set +e
(
  run_docker() {
    if [[ "$1" == "inspect" && "$2" != "-f" ]]; then
      return 1
    fi
    return 0
  }
  require_tunnel
) >/dev/null
rc=$?
set -e
[[ "$rc" -eq 76 ]] || fail "missing tunnel should exit 76, got $rc"

# Stopped tunnel.
set +e
(
  run_docker() {
    if [[ "$1" == "inspect" && "$2" == "-f" ]]; then
      printf '%s\n' false
      return 0
    fi
    return 0
  }
  require_tunnel
) >/dev/null
rc=$?
set -e
[[ "$rc" -eq 76 ]] || fail "stopped tunnel should exit 76, got $rc"

# Running tunnel on snigdho-net.
(
  run_docker() {
    if [[ "$1" == "inspect" && "$2" == "-f" ]]; then
      case "$3" in
        *Running*) printf '%s\n' true ;;
        *Networks*) printf '%s\n' "snigdho-net " ;;
        *) printf '%s\n' ok ;;
      esac
      return 0
    fi
    return 0
  }
  require_tunnel
)

generate_env_file
mode="$(stat -c %a "$SPY_ENV_FILE")"
[[ "$mode" == "600" ]] || fail "env mode is $mode"
if grep -v '^[[:space:]]*#' "$SPY_ENV_FILE" | grep -q '__CHANGE_ME__'; then
  fail "generated env kept placeholders"
fi
secret="$(grep '^SECRET_KEY=' "$SPY_ENV_FILE" | cut -d= -f2-)"
mysql_pass="$(grep '^MYSQL_PASSWORD=' "$SPY_ENV_FILE" | cut -d= -f2-)"
mysql_root="$(grep '^MYSQL_ROOT_PASSWORD=' "$SPY_ENV_FILE" | cut -d= -f2-)"
jwt="$(grep '^JWT_SIGNING_KEY=' "$SPY_ENV_FILE" | cut -d= -f2-)"
[[ "${#secret}" -eq 64 ]] || fail "SECRET_KEY length"
[[ "${#mysql_pass}" -eq 48 && "${#mysql_root}" -eq 48 && "${#jwt}" -eq 64 ]] || fail "secret lengths"
[[ "$secret" != "$mysql_pass" && "$mysql_pass" != "$mysql_root" && "$secret" != "$jwt" ]] || fail "secrets not unique"

# not_ready must not count as ready.
(
  run_docker() {
    if [[ "$1" == "exec" && "$*" == *"/health/ready/"* ]]; then
      printf '%s' '{"status":"not_ready"}'
      return 0
    fi
    if [[ "$1" == "exec" ]]; then
      printf '%s' '{"status": "alive"}'
      return 0
    fi
    return 1
  }
  if http_path_ok spy-nginx /health/ready/ ready; then
    echo "not_ready was treated as ready" >&2
    exit 1
  fi
  http_path_ok spy-nginx /health/live/ alive
)

calls="$tmp/calls"
: >"$calls"
(
  run_docker() {
    printf 'docker %s\n' "$*" >>"$calls"
    return 0
  }
  compose_project() {
    printf 'compose %s\n' "$*" >>"$calls"
    return 0
  }
  restore_previous_release
)
grep -q 'old compose' "$tmp/app/infra/docker-compose.prod.yml" || fail "compose file was not restored"
grep -q 'old nginx' "$tmp/app/infra/nginx/nginx.prod.conf" || fail "nginx conf was not restored"
grep -q 'docker tag spy-api:previous spy-api:latest' "$calls" || fail "did not retag previous to latest"
grep -q 'compose spy latest up -d --no-build --force-recreate --remove-orphans' "$calls" || fail "rollback up missing"

# Cron installer preserves unrelated jobs and is idempotent.
cron_file="$tmp/cron"
mkdir -p "$tmp/bin" "$tmp/app/infra/deploy"
cp "$ROOT/infra/deploy/spy-watcher.sh" "$tmp/app/infra/deploy/spy-watcher.sh"
cp "$ROOT/infra/deploy/deploy-spy.sh" "$tmp/app/infra/deploy/deploy-spy.sh"
chmod +x "$tmp/app/infra/deploy/"*.sh
printf '%s\n' '0 4 * * * /usr/bin/other-job' >"$cron_file"
cat >"$tmp/bin/crontab" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\${1:-}" == "-l" ]]; then
  if [[ -f "$cron_file" ]]; then
    cat "$cron_file"
  fi
  exit 0
fi
if [[ "\${1:-}" == "-" ]]; then
  cat >"$cron_file"
  exit 0
fi
echo "unexpected crontab args: \$*" >&2
exit 1
EOF
chmod +x "$tmp/bin/crontab"
PATH="$tmp/bin:$PATH" HOME="$tmp/home" SPY_APP_DIR="$tmp/app" \
  bash "$ROOT/infra/deploy/install-spy-cron.sh" >/dev/null
grep -q '/usr/bin/other-job' "$cron_file" || fail "installer dropped an existing cron job"
grep -q 'CRON_TZ=Asia/Dhaka' "$cron_file" || fail "CRON_TZ missing"
grep -q '0 1 \* \* \* TZ=Asia/Dhaka /bin/bash' "$cron_file" || fail "01:00 job missing"
count="$(grep -c 'BEGIN spy-backend-watcher' "$cron_file")"
[[ "$count" -eq 1 ]] || fail "marker count $count before second install"
PATH="$tmp/bin:$PATH" HOME="$tmp/home" SPY_APP_DIR="$tmp/app" \
  bash "$ROOT/infra/deploy/install-spy-cron.sh" >/dev/null
count="$(grep -c 'BEGIN spy-backend-watcher' "$cron_file")"
[[ "$count" -eq 1 ]] || fail "installer duplicated the block ($count)"
grep -q '/usr/bin/other-job' "$cron_file" || fail "second install dropped the other job"

echo "deploy logic tests passed"
