#!/usr/bin/env bash
# Install or update Spy Love on the TX6 beside the existing portfolio stack.
# Never creates, starts, stops, or recreates snigdho-tunnel / snigdho-web.
set -euo pipefail

APP_DIR="${SPY_APP_DIR:-$HOME/apps/spy-backend}"
REPO_URL="${SPY_REPO_URL:-https://github.com/snigdho48/spy_backend.git}"
BRANCH="${SPY_BRANCH:-master}"
ENV_FILE="${SPY_ENV_FILE:-$HOME/.config/spy-backend/prod.env}"
CACHE_DIR="${SPY_CACHE_DIR:-$HOME/.cache/spy-backend}"
EXAMPLE_FILE="${SPY_ENV_EXAMPLE:-$APP_DIR/infra/env/prod.env.example}"
COMPOSE_FILE="${SPY_COMPOSE_FILE:-$APP_DIR/infra/docker-compose.prod.yml}"
TEST_COMPOSE_FILE="${SPY_TEST_COMPOSE_FILE:-$APP_DIR/infra/docker-compose.prod.test.yml}"
HEALTHCHECK_HOST="${SPY_HEALTH_HOST:-spy.way2points.com}"
TUNNEL_CONTAINER="${SPY_TUNNEL_CONTAINER:-snigdho-tunnel}"
WEB_CONTAINER="${SPY_WEB_CONTAINER:-snigdho-web}"
TUNNEL_NETWORK="${SPY_TUNNEL_NETWORK:-snigdho-net}"

MODE="install"
PORTFOLIO_BEFORE=""
WEB_BEFORE="absent"
TEST_UP=0

usage() {
  cat <<EOF
Usage: deploy-spy.sh [--update | --rollback | --apply-live-config]

  (default)    First install or idempotent deploy. Creates $ENV_FILE
               when it is missing, builds spy-api, health-checks a
               throwaway spy-test stack, then swaps the live "spy" project.
  --update     Same swap path, but refuses to invent secrets. For the watcher.
  --rollback   Retag spy-api:previous as spy-api:latest, restore the compose
               and nginx files from the saved commit, and health-check again.
  --apply-live-config
               Pull the repo, then "compose up -d --no-build" on the live spy
               project only, so Docker recreates just the containers whose
               config changed (e.g. healthcheck intervals). No image build,
               no spy-test stack, no --force-recreate.

The script exits 76 if $TUNNEL_CONTAINER is missing or stopped. It will not
start the tunnel. Cloudflare hostnames are dashboard-managed:

  Hostname: spy.way2points.com
  Service:  http://spy-nginx:80
EOF
}

refuse_portfolio_docker_args() {
  local cmd=${1:-}
  shift || true
  local arg mutating=0
  case "$cmd" in
    stop|rm|restart|kill|pause|update|rename)
      mutating=1
      ;;
    exec)
      mutating=1
      ;;
    network)
      case "${1:-}" in
        rm|disconnect|connect|create)
          mutating=1
          ;;
      esac
      ;;
  esac
  if [[ "$mutating" -eq 0 ]]; then
    return 0
  fi
  for arg in "$@"; do
    case "$arg" in
      snigdho-tunnel|snigdho-web|snigdho-net|snigdho-*)
        echo "ERROR: refusing to ${cmd} portfolio resource ${arg}." >&2
        exit 1
        ;;
    esac
  done
}

run_docker() {
  refuse_portfolio_docker_args "$@"
  command docker "$@"
}

compose_project() {
  local project=$1
  local tag=$2
  shift 2
  case "$project" in
    spy|spy-test) ;;
    *)
      echo "ERROR: refusing unexpected compose project: ${project}" >&2
      exit 1
      ;;
  esac
  local arg
  for arg in "$@"; do
    case "$arg" in
      snigdho-tunnel|snigdho-web|snigdho-net)
        echo "ERROR: refusing compose argument that names the portfolio: ${arg}" >&2
        exit 1
        ;;
    esac
  done
  export SPY_ENV_FILE="$ENV_FILE"
  export SPY_PROJECT_NAME="$project"
  export SPY_IMAGE_TAG="$tag"
  local -a args=(
    --project-directory "$APP_DIR/infra"
    --env-file "$ENV_FILE"
    -f "$COMPOSE_FILE"
  )
  if [[ "$project" == "spy-test" ]]; then
    args+=(-f "$TEST_COMPOSE_FILE")
  fi
  args+=(-p "$project")
  command docker compose "${args[@]}" "$@"
}

require_tools() {
  local missing=0 tool
  for tool in docker git openssl flock; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      echo "ERROR: ${tool} is required." >&2
      missing=1
    fi
  done
  if ! command docker compose version >/dev/null 2>&1; then
    echo "ERROR: docker compose v2 is required (Compose 2.24+ for the test overlay)." >&2
    missing=1
  fi
  if [[ "$missing" -ne 0 ]]; then
    exit 1
  fi
}

require_tunnel() {
  if ! run_docker inspect "$TUNNEL_CONTAINER" >/dev/null 2>&1; then
    echo "ERROR: ${TUNNEL_CONTAINER} is not present. Refusing to start." >&2
    echo "This script never creates, starts, stops, or recreates the portfolio tunnel." >&2
    exit 76
  fi
  local running
  running="$(run_docker inspect -f '{{.State.Running}}' "$TUNNEL_CONTAINER")"
  if [[ "$running" != "true" ]]; then
    echo "ERROR: ${TUNNEL_CONTAINER} is not running. Refusing to start." >&2
    echo "Start the portfolio stack first. This script will not start the tunnel." >&2
    exit 76
  fi
  if ! run_docker network inspect "$TUNNEL_NETWORK" >/dev/null 2>&1; then
    echo "ERROR: docker network ${TUNNEL_NETWORK} is missing." >&2
    exit 76
  fi
  local nets
  # shellcheck disable=SC2016 # Docker Go template; $k is not a shell variable.
  nets="$(run_docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$TUNNEL_CONTAINER")"
  if [[ "$nets" != *"${TUNNEL_NETWORK}"* ]]; then
    echo "ERROR: ${TUNNEL_CONTAINER} is not attached to ${TUNNEL_NETWORK}." >&2
    exit 76
  fi
}

snapshot_portfolio() {
  PORTFOLIO_BEFORE="$(run_docker inspect -f '{{.Id}} {{.State.Running}}' "$TUNNEL_CONTAINER")"
  if run_docker inspect "$WEB_CONTAINER" >/dev/null 2>&1; then
    WEB_BEFORE="$(run_docker inspect -f '{{.Id}} {{.State.Running}}' "$WEB_CONTAINER")"
  else
    WEB_BEFORE="absent"
  fi
}

assert_portfolio_unchanged() {
  local now web
  now="$(run_docker inspect -f '{{.Id}} {{.State.Running}}' "$TUNNEL_CONTAINER")"
  if [[ "$now" != "$PORTFOLIO_BEFORE" ]]; then
    echo "ERROR: ${TUNNEL_CONTAINER} changed (${PORTFOLIO_BEFORE} -> ${now})." >&2
    return 76
  fi
  if [[ "$WEB_BEFORE" != "absent" ]]; then
    web="$(run_docker inspect -f '{{.Id}} {{.State.Running}}' "$WEB_CONTAINER" 2>/dev/null || echo missing)"
    if [[ "$web" != "$WEB_BEFORE" ]]; then
      echo "ERROR: ${WEB_CONTAINER} changed (${WEB_BEFORE} -> ${web})." >&2
      return 76
    fi
  fi
}

acquire_lock() {
  mkdir -p "$CACHE_DIR"
  exec 9>"$CACHE_DIR/deploy.lock"
  if ! flock -n 9; then
    echo "Another spy deploy holds ${CACHE_DIR}/deploy.lock." >&2
    exit 75
  fi
}

generate_env_file() {
  local dir secret_key mysql_root mysql_pass jwt
  if [[ ! -f "$EXAMPLE_FILE" ]]; then
    echo "ERROR: missing env example ${EXAMPLE_FILE}" >&2
    exit 1
  fi
  dir="$(dirname "$ENV_FILE")"
  mkdir -p "$dir"
  chmod 700 "$dir"
  secret_key="$(openssl rand -hex 32)"
  mysql_root="$(openssl rand -hex 24)"
  mysql_pass="$(openssl rand -hex 24)"
  jwt="$(openssl rand -hex 32)"
  (
    umask 077
    sed \
      -e "s|^SECRET_KEY=.*|SECRET_KEY=${secret_key}|" \
      -e "s|^MYSQL_ROOT_PASSWORD=.*|MYSQL_ROOT_PASSWORD=${mysql_root}|" \
      -e "s|^MYSQL_PASSWORD=.*|MYSQL_PASSWORD=${mysql_pass}|" \
      -e "s|^JWT_SIGNING_KEY=.*|JWT_SIGNING_KEY=${jwt}|" \
      "$EXAMPLE_FILE" >"$ENV_FILE"
  )
  chmod 600 "$ENV_FILE"
  if grep -v '^[[:space:]]*#' "$ENV_FILE" | grep -q '__CHANGE_ME__'; then
    echo "ERROR: generated env still contains __CHANGE_ME__. Check ${EXAMPLE_FILE}." >&2
    rm -f "$ENV_FILE"
    exit 1
  fi
  echo "Wrote ${ENV_FILE} (mode 600). Secrets stay on this host."
}

ensure_env() {
  if [[ -f "$ENV_FILE" ]]; then
    if grep -v '^[[:space:]]*#' "$ENV_FILE" | grep -q '__CHANGE_ME__'; then
      echo "ERROR: ${ENV_FILE} still contains __CHANGE_ME__ placeholders." >&2
      exit 1
    fi
    chmod 600 "$ENV_FILE" || true
    return 0
  fi
  if [[ "$MODE" != "install" ]]; then
    echo "ERROR: ${ENV_FILE} is missing. Run deploy-spy.sh without --update first." >&2
    exit 1
  fi
  generate_env_file
}

sync_repo() {
  if [[ ! -d "$APP_DIR/.git" ]]; then
    if [[ "$MODE" == "update" ]]; then
      echo "ERROR: ${APP_DIR} is not a git checkout. Run a first install before --update." >&2
      exit 1
    fi
    if [[ -d "$APP_DIR" ]] && [[ -n "$(ls -A "$APP_DIR" 2>/dev/null || true)" ]]; then
      echo "ERROR: ${APP_DIR} exists but is not a git checkout." >&2
      exit 1
    fi
    mkdir -p "$(dirname "$APP_DIR")"
    git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$APP_DIR"
    return 0
  fi
  if [[ -n "$(git -C "$APP_DIR" status --porcelain)" ]]; then
    echo "ERROR: ${APP_DIR} has local changes. Refusing to pull." >&2
    exit 1
  fi
  git -C "$APP_DIR" fetch origin "$BRANCH"
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
}

exact_container_id() {
  local want=$1 id name
  while read -r id; do
    [[ -z "$id" ]] && continue
    name="$(run_docker inspect -f '{{.Name}}' "$id")"
    name="${name#/}"
    if [[ "$name" == "$want" ]]; then
      printf '%s\n' "$id"
      return 0
    fi
  done < <(run_docker ps -aq --filter "name=${want}")
}

save_previous_image() {
  local cid img
  mkdir -p "$CACHE_DIR"
  cid="$(exact_container_id spy-api)"
  if [[ -n "$cid" ]]; then
    img="$(run_docker inspect -f '{{.Image}}' "$cid")"
    run_docker tag "$img" spy-api:previous
    printf '%s\n' "$img" >"$CACHE_DIR/previous-image-id"
    echo "Saved the running API image as spy-api:previous (${img})."
    return 0
  fi
  if run_docker image inspect spy-api:latest >/dev/null 2>&1; then
    img="$(run_docker image inspect -f '{{.Id}}' spy-api:latest)"
    run_docker tag "$img" spy-api:previous
    printf '%s\n' "$img" >"$CACHE_DIR/previous-image-id"
    echo "Tagged spy-api:latest as spy-api:previous."
    return 0
  fi
  rm -f "$CACHE_DIR/previous-image-id" "$CACHE_DIR/previous-sha"
  echo "No existing spy-api image. First install will not have a rollback target until it succeeds once."
}

has_previous_image() {
  if run_docker image inspect spy-api:previous >/dev/null 2>&1; then
    return 0
  fi
  [[ -s "$CACHE_DIR/previous-image-id" ]]
}

build_image() {
  local -a pull=()
  if [[ "$MODE" == "install" && ! -f "$CACHE_DIR/installed" ]]; then
    pull=(--pull)
  fi
  echo "Building spy-api:candidate"
  COMPOSE_PARALLEL_LIMIT=1 compose_project spy-test candidate build "${pull[@]}" api
}

http_path_ok() {
  local container=$1
  local path=$2
  local status_name=$3
  local body compact spaced
  if ! body="$(run_docker exec "$container" wget -q -O - \
    --header="Host: ${HEALTHCHECK_HOST}" \
    --header="X-Forwarded-Proto: https" \
    "http://127.0.0.1${path}" 2>/dev/null)"; then
    return 1
  fi
  compact="\"status\":\"${status_name}\""
  spaced="\"status\": \"${status_name}\""
  # "ready" must not match "not_ready": the token includes the JSON key.
  [[ "$body" == *"$compact"* || "$body" == *"$spaced"* ]]
}

dump_container_logs() {
  local container
  for container in "$@"; do
    echo "----- logs ${container} -----" >&2
    run_docker logs --tail 120 "$container" >&2 || true
  done
}

celery_running() {
  local name=$1 status
  if ! run_docker inspect "$name" >/dev/null 2>&1; then
    return 1
  fi
  status="$(run_docker inspect -f '{{.State.Status}}' "$name")"
  [[ "$status" == "running" ]]
}

wait_for_stack() {
  local nginx_name=$1
  local celery_name=${2:-}
  local tries=${3:-60}
  local i
  for i in $(seq 1 "$tries"); do
    if http_path_ok "$nginx_name" "/health/live/" alive \
      && http_path_ok "$nginx_name" "/health/ready/" ready \
      && { [[ -z "$celery_name" ]] || celery_running "$celery_name"; }; then
      echo "Health OK via ${nginx_name} (/health/live/ and /health/ready/)."
      return 0
    fi
    if (( i % 5 == 0 )); then
      echo "Waiting for ${nginx_name} (${i}/${tries})..."
    fi
    sleep 5
  done
  echo "ERROR: ${nginx_name} did not pass /health/live/ and /health/ready/." >&2
  return 1
}

assert_test_nginx_isolated() {
  local nets
  # shellcheck disable=SC2016 # Docker Go template; $k is not a shell variable.
  nets="$(run_docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' spy-test-nginx)"
  if [[ "$nets" == *"${TUNNEL_NETWORK}"* ]]; then
    echo "ERROR: spy-test-nginx joined ${TUNNEL_NETWORK}. Refusing to swap so the tunnel cannot reach the test stack." >&2
    return 1
  fi
}

dump_test_stack_diagnostics() {
  # Runs on any test-stack failure, before teardown, so the evidence lands in
  # the deploy log. Never fatal.
  echo "===== spy-test failure diagnostics ($(date -Is)) =====" >&2
  echo "----- docker ps -a (project spy-test) -----" >&2
  run_docker ps -a --filter "label=com.docker.compose.project=spy-test" \
    --format 'table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}' >&2 || true
  local ids id name
  ids="$(run_docker ps -aq --filter "label=com.docker.compose.project=spy-test" \
    --filter "label=com.docker.compose.service=mariadb" 2>/dev/null || true)"
  if [[ -z "$ids" ]] && run_docker inspect spy-test-mariadb >/dev/null 2>&1; then
    ids="spy-test-mariadb"
  fi
  if [[ -z "$ids" ]]; then
    echo "No spy-test mariadb container found." >&2
  fi
  for id in $ids; do
    name="$(run_docker inspect -f '{{.Name}}' "$id" 2>/dev/null || echo "$id")"
    echo "----- health ${name} -----" >&2
    run_docker inspect --format '{{json .State.Health}}' "$id" >&2 || true
    echo "----- state ${name} -----" >&2
    run_docker inspect --format 'Status={{.State.Status}} ExitCode={{.State.ExitCode}} OOMKilled={{.State.OOMKilled}} Restarts={{.RestartCount}} Started={{.State.StartedAt}}' "$id" >&2 || true
    echo "----- logs ${name} (last 100) -----" >&2
    run_docker logs --tail 100 --timestamps "$id" >&2 || true
  done
  echo "===== end spy-test diagnostics =====" >&2
}

apply_live_config() {
  # Recreate only live containers whose compose config changed (e.g. healthcheck
  # intervals). No build, no test stack, no --force-recreate, no dockerd restart.
  echo "Applying live compose config to project spy (no build, no test stack)."
  if ! run_docker image inspect spy-api:latest >/dev/null 2>&1; then
    echo "ERROR: spy-api:latest is missing; run a normal deploy instead." >&2
    return 1
  fi
  compose_project spy latest up -d --no-build --remove-orphans || return 1
  if ! wait_for_stack spy-nginx spy-celery; then
    dump_container_logs spy-nginx spy-api spy-celery spy-mariadb spy-redis
    return 1
  fi
  write_deployed_sha
  echo "Live config applied and spy-nginx is healthy."
}

cleanup_test_stack() {
  if [[ "$TEST_UP" != "1" ]]; then
    return 0
  fi
  TEST_UP=0
  compose_project spy-test candidate down -v --remove-orphans || true
}

run_test_stack() {
  # Release BuildKit cache / dangling images so they don't hold memory while
  # the live and test stacks run side by side. Never fatal.
  docker builder prune -f >/dev/null 2>&1 || true
  docker image prune -f >/dev/null 2>&1 || true
  TEST_UP=1
  echo "Starting throwaway spy-test stack (live spy project is left running)."
  if ! compose_project spy-test candidate up -d --no-build --force-recreate --remove-orphans; then
    # "dependency failed to start: ... unhealthy" is raised here by compose
    # (api depends_on mariadb: service_healthy), not by wait_for_stack.
    dump_test_stack_diagnostics
    return 1
  fi
  if ! assert_test_nginx_isolated; then
    return 1
  fi
  if ! wait_for_stack spy-test-nginx; then
    dump_test_stack_diagnostics
    dump_container_logs spy-test-nginx spy-test-api spy-test-mariadb spy-test-redis
    return 1
  fi
}

restore_previous_release() {
  echo "Restoring spy-api:previous onto the live spy project." >&2
  if ! run_docker image inspect spy-api:previous >/dev/null 2>&1; then
    if [[ -s "$CACHE_DIR/previous-image-id" ]]; then
      run_docker tag "$(<"$CACHE_DIR/previous-image-id")" spy-api:previous
    else
      echo "ERROR: spy-api:previous is not present and no image id was saved." >&2
      return 1
    fi
  fi
  if [[ -s "$CACHE_DIR/previous-sha" && -d "$APP_DIR/.git" ]]; then
    local sha
    sha="$(<"$CACHE_DIR/previous-sha")"
    git -C "$APP_DIR" checkout "$sha" -- infra/docker-compose.prod.yml infra/nginx/nginx.prod.conf
  fi
  run_docker tag spy-api:previous spy-api:latest
  compose_project spy latest up -d --no-build --force-recreate --remove-orphans
}

rollback_live() {
  if ! restore_previous_release; then
    return 1
  fi
  if ! wait_for_stack spy-nginx spy-celery; then
    dump_container_logs spy-nginx spy-api spy-celery spy-mariadb spy-redis
    echo "ERROR: rollback health check failed." >&2
    return 1
  fi
  rm -f "$CACHE_DIR/swap-started"
  echo "Rollback succeeded. spy-nginx is healthy on spy-api:previous."
}

rollback_or_stop() {
  if has_previous_image; then
    if rollback_live; then
      echo "Update failed. The previous release is healthy again." >&2
      return 0
    fi
    echo "Update failed and rollback did not become healthy." >&2
    return 1
  fi
  echo "No previous image. Stopping api, celery, and nginx. The database volume is kept." >&2
  compose_project spy latest stop api celery nginx || true
  rm -f "$CACHE_DIR/swap-started"
  return 1
}

note_public_url() {
  echo "Cloudflare Zero Trust public hostname (dashboard only; this script does not edit the tunnel):"
  echo "  Hostname: spy.way2points.com"
  echo "  Service:  http://spy-nginx:80"
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 10 "https://spy.way2points.com/health/live/" >/dev/null; then
      echo "Public https://spy.way2points.com/health/live/ responded."
    else
      echo "Public URL did not respond yet. Local spy-nginx health passed."
    fi
  fi
}

write_deployed_sha() {
  local sha tmp
  sha="$(git -C "$APP_DIR" rev-parse HEAD)"
  tmp="$(mktemp "$CACHE_DIR/deployed-sha.XXXXXX")"
  printf '%s\n' "$sha" >"$tmp"
  mv "$tmp" "$CACHE_DIR/deployed-sha"
}

deploy_new_release() {
  if [[ -f "$CACHE_DIR/swap-started" ]]; then
    echo "A previous swap did not finish. Restoring spy-api:previous before this attempt." >&2
    rollback_or_stop || return 1
  fi
  save_previous_image
  build_image
  if ! run_test_stack; then
    echo "Test stack failed. The live spy project was not modified." >&2
    cleanup_test_stack
    return 1
  fi
  cleanup_test_stack
  if ! assert_portfolio_unchanged; then
    return 76
  fi
  date -Is >"$CACHE_DIR/swap-started"
  echo "Test stack passed. Swapping the live spy project to spy-api:latest."
  run_docker tag spy-api:candidate spy-api:latest
  if ! compose_project spy latest up -d --no-build --force-recreate --remove-orphans; then
    echo "Live compose up failed." >&2
    rollback_or_stop || true
    return 1
  fi
  if ! wait_for_stack spy-nginx spy-celery; then
    dump_container_logs spy-nginx spy-api spy-celery spy-mariadb spy-redis
    rollback_or_stop || true
    return 1
  fi
  if ! assert_portfolio_unchanged; then
    # New stack is healthy, but the portfolio id moved. Do not roll Spy back
    # and do not leave the swap marker, or the next failure would undo it.
    rm -f "$CACHE_DIR/swap-started"
    return 76
  fi
  rm -f "$CACHE_DIR/swap-started" "$CACHE_DIR/fail-state"
  write_deployed_sha
  touch "$CACHE_DIR/installed"
  echo "Spy Love live stack is healthy."
  note_public_url
}

parse_args() {
  MODE="install"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --update) MODE="update" ;;
      --rollback) MODE="rollback" ;;
      --apply-live-config) MODE="apply-live-config" ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage >&2
        exit 2
        ;;
    esac
    shift
  done
}

main() {
  local rc=0
  local -a args=("$@")
  parse_args "${args[@]}"
  echo "Portfolio guard: ${TUNNEL_CONTAINER} and ${WEB_CONTAINER} are not stopped or recreated."
  require_tools
  require_tunnel
  snapshot_portfolio
  if [[ "$MODE" != "rollback" ]]; then
    # Record the pre-pull commit once. Re-exec happens after pull, and a second
    # record would point previous-sha at the new commit instead of the one
    # whose image is still running.
    if [[ "${SPY_DEPLOY_REEXEC:-}" != "1" && -d "$APP_DIR/.git" ]]; then
      mkdir -p "$CACHE_DIR"
      git -C "$APP_DIR" rev-parse HEAD >"$CACHE_DIR/previous-sha"
    fi
    sync_repo
    if [[ "${SPY_DEPLOY_REEXEC:-}" != "1" ]]; then
      if [[ ! -f "$APP_DIR/infra/deploy/deploy-spy.sh" ]]; then
        echo "ERROR: missing ${APP_DIR}/infra/deploy/deploy-spy.sh after sync." >&2
        exit 1
      fi
      export SPY_DEPLOY_REEXEC=1
      exec "$APP_DIR/infra/deploy/deploy-spy.sh" "${args[@]}"
    fi
  fi
  acquire_lock
  ensure_env
  trap cleanup_test_stack EXIT
  if [[ "$MODE" == "apply-live-config" ]]; then
    apply_live_config
    assert_portfolio_unchanged
    exit 0
  fi
  if [[ "$MODE" == "rollback" ]]; then
    rollback_live
    assert_portfolio_unchanged
    exit 0
  fi
  deploy_new_release || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    exit "$rc"
  fi
  assert_portfolio_unchanged
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
