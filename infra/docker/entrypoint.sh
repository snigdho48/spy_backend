#!/bin/sh
# Runs DB migrations (idempotent) before starting the main process (daphne).
# SKIP_MIGRATIONS=true bypasses (used by celery). RUN_COLLECTSTATIC=true also runs
# collectstatic (off by default: very slow over the Windows bind mount in dev).
set -e
if [ "${SKIP_MIGRATIONS:-false}" != "true" ]; then
  echo "[entrypoint] applying migrations..."
  python manage.py migrate --noinput
fi
if [ "${RUN_COLLECTSTATIC:-false}" = "true" ]; then
  echo "[entrypoint] collectstatic..."
  python manage.py collectstatic --noinput
fi
echo "[entrypoint] starting: $*"
exec "$@"
