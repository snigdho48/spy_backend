#!/usr/bin/env bash
# Logical backup of the Spy Love MariaDB container. Non-destructive.
set -euo pipefail

SPY_DB_CONTAINER="${SPY_DB_CONTAINER:-spy-mariadb}"
MYSQL_DATABASE="${MYSQL_DATABASE:-spylove}"
MYSQL_USER="${MYSQL_USER:-spylove}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"

if [[ -z "${MYSQL_PASSWORD:-}" ]]; then
  echo "MYSQL_PASSWORD must be set (or sourced from your env file)." >&2
  exit 1
fi

if ! docker inspect -f '{{.State.Running}}' "$SPY_DB_CONTAINER" 2>/dev/null | grep -q true; then
  echo "Container $SPY_DB_CONTAINER is not running." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
outfile="$BACKUP_DIR/${MYSQL_DATABASE}-${stamp}.sql.gz"

echo "Dumping $MYSQL_DATABASE from $SPY_DB_CONTAINER -> $outfile"
docker exec "$SPY_DB_CONTAINER" \
  mariadb-dump \
    -u"$MYSQL_USER" \
    -p"$MYSQL_PASSWORD" \
    --single-transaction \
    --routines \
    --triggers \
    --hex-blob \
    "$MYSQL_DATABASE" \
  | gzip -c > "$outfile"

echo "Wrote $(du -h "$outfile" | awk '{print $1}')"
find "$BACKUP_DIR" -name "${MYSQL_DATABASE}-*.sql.gz" -mtime +"$BACKUP_KEEP_DAYS" -delete
echo "Pruned dumps older than ${BACKUP_KEEP_DAYS} days (if any)."
