# MariaDB backup & restore (Spy Love)

The production stack runs MariaDB in Docker (`mariadb` service in
`infra/docker-compose.prod.yml`). Compose volumes are **not** a backup plan —
take logical dumps on a schedule and practice restore.

This document is intentionally script-oriented and non-destructive. Nothing
here is wired into deploy automatically.

## What to back up

| Item | Notes |
|------|-------|
| MariaDB logical dump | Primary restore path (`mysqldump` / `mariadb-dump`) |
| `.env` / secrets | Store offline (password manager / sealed secret); never in git |
| `FIELD_ENCRYPTION_KEY` | Required to read ciphertext in event/contact payloads after restore |
| Media (if any) | App stores photo URLs only today — usually nothing local |

## Backup (logical dump)

Helper script (from repo root, on the host that runs compose):

```bash
./scripts/backup-mariadb.sh
```

What it does:

1. Resolves the running MariaDB container (`SPY_DB_CONTAINER`, default `spy-mariadb`).
2. Runs `mariadb-dump` inside the container (single-transaction, routines).
3. Writes a gzipped file under `./backups/` (or `$BACKUP_DIR`) named
   `spylove-YYYYMMDD-HHMMSS.sql.gz`.
4. Prunes dumps older than `$BACKUP_KEEP_DAYS` (default 14).

Cron example (daily 03:15 local time):

```cron
15 3 * * * cd /path/to/spy_backend && ./scripts/backup-mariadb.sh >>/var/log/spy-backup.log 2>&1
```

Optional: copy the gzip off-box (`rclone`, `scp`, object storage). Keep at
least one copy off the same disk as the MariaDB volume.

## Restore (drill)

1. Stop writers (API / celery) so nothing races the import.
2. Ensure the target database is empty or you accept overwrite.
3. Gunzip and import:

```bash
gunzip -c backups/spylove-YYYYMMDD-HHMMSS.sql.gz \
  | docker exec -i "$SPY_DB_CONTAINER" mariadb \
      -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"
```

4. Start API / celery again. Confirm `/health/ready/` and a smoke login.

Always practice this on a **non-production** compose project first
(`SPY_PROJECT_NAME=spy-test`).

## Retention vs backups

Application retention (`purge_expired_events` Celery task / management
command) deletes events older than the plan window. Backups are the safety net
for operator error and disaster recovery — do not treat retention purge as a
backup.
