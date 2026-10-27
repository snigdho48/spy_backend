# Spy Love on the TX6

Production deploy for an Armbian box (Ubuntu 24.04, 4-core ARM64, 3GB RAM + 1.5GB swap, 64GB eMMC) that **already** runs the portfolio stack. These scripts add a second Compose project. They do not edit portfolio containers or the portfolio deploy script.

| Already on the box | Spy adds |
|---|---|
| Docker network `snigdho-net` | Compose project `spy` |
| `snigdho-tunnel` (Cloudflare) | `spy-nginx` on `snigdho-net` |
| `snigdho-web` | `spy-mariadb`, `spy-redis`, `spy-api`, `spy-celery` on `spy_internal` only |

`deploy-spy.sh` exits **76** if `snigdho-tunnel` is missing or stopped. It never creates, starts, stops, or recreates `snigdho-tunnel` or `snigdho-web`.

## Cloudflare (you add this in the dashboard)

The tunnel is dashboard-managed. Nothing in this repo writes tunnel config.

In Cloudflare Zero Trust → Networks → Tunnels → the existing tunnel → Public Hostname:

- **Hostname:** `spy.way2points.com`
- **Service:** `http://spy-nginx:80`

`spy-nginx` is the container name on `snigdho-net`. MariaDB and Redis are not on that network and have no host ports.

## First install

On the TX6, as the user that already runs the portfolio (so `docker` works without sudo):

```bash
mkdir -p "$HOME/apps"
git clone --branch master https://github.com/snigdho48/spy_backend.git "$HOME/apps/spy-backend"
"$HOME/apps/spy-backend/infra/deploy/deploy-spy.sh"
"$HOME/apps/spy-backend/infra/deploy/install-spy-cron.sh"
```

What the install does:

1. Refuses to continue unless `snigdho-tunnel` is running on `snigdho-net`.
2. Clones or fast-forwards `master` into `$HOME/apps/spy-backend`.
3. On first run only, writes `$HOME/.config/spy-backend/prod.env` (mode 600) from `infra/env/prod.env.example` and fills `SECRET_KEY`, `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`, and `JWT_SIGNING_KEY` with `openssl rand -hex`. Later runs never rotate those values.
4. Builds `spy-api:candidate` (`linux/arm64`).
5. Starts a throwaway Compose project `spy-test` (its own volumes, nginx named `spy-test-nginx`, not attached to `snigdho-net`).
6. Requires `GET /health/live/` and `GET /health/ready/` through that nginx. On failure it deletes the test project, prints logs, and **does not** recreate the live `spy` project.
7. On success, tags the image that was serving traffic as `spy-api:previous` (this happens before the swap), retags the candidate as `spy-api:latest`, and `docker compose -p spy up -d --force-recreate`.
8. Checks live `/health/live/` and `/health/ready/` via `spy-nginx`, and checks that `spy-celery` is running. On failure it retags `spy-api:previous` back to `spy-api:latest`, restores `infra/docker-compose.prod.yml` and `infra/nginx/nginx.prod.conf` from the saved commit, recreates the live project, and health-checks again.

The dev file `infra/docker-compose.yml` (MySQL 8, Prometheus, Grafana, published ports) is not what this script starts.

## Update

```bash
"$HOME/apps/spy-backend/infra/deploy/deploy-spy.sh" --update
```

`--update` will not create `prod.env`. Use it when the checkout and secrets already exist.

## Rollback

`:previous` is the image id that was running **before** the swap. `$HOME/.cache/spy-backend/previous-sha` is the git commit checked out before this attempt pulled, and rollback restores `infra/docker-compose.prod.yml` and `infra/nginx/nginx.prod.conf` from that commit.

```bash
"$HOME/apps/spy-backend/infra/deploy/deploy-spy.sh" --rollback
```

Rollback runs `docker tag spy-api:previous spy-api:latest` and `docker compose -p spy up -d --no-build --force-recreate`, then checks `/health/live/` and `/health/ready/` again. If that check fails, the script exits non-zero and leaves logs on stderr.

Do not run `docker image prune -a`. That can delete `spy-api:previous` even though the tag exists, and then rollback has nothing to start. Ordinary `docker image prune` (without `-a`) keeps tagged images.

Database migrations are forward-only. Rolling the image back does not reverse a migration that already committed.

## Daily updater (01:00 Asia/Dhaka)

```bash
"$HOME/apps/spy-backend/infra/deploy/install-spy-cron.sh"
```

The user crontab entry is:

```cron
CRON_TZ=Asia/Dhaka
0 1 * * * TZ=Asia/Dhaka /bin/bash $HOME/apps/spy-backend/infra/deploy/spy-watcher.sh
```

**Armbian / Ubuntu 24.04 cron** is Debian cron, not cronie. It schedules in the **system timezone** and does not honor `CRON_TZ` for the clock. `TZ=` on the command only affects timestamps inside the watcher. If `timedatectl` does not show `Asia/Dhaka`, `0 1 * * *` is not 01:00 in Dhaka (Dhaka is UTC+6, no DST; 01:00 Dhaka is 19:00 UTC the previous evening). Set it once:

```bash
sudo timedatectl set-timezone Asia/Dhaka
```

That changes the clock for the whole box, including portfolio cron if any jobs share this system timezone. The installer prints a warning when the timezone is something else. On cronie, `CRON_TZ` applies to the whole user crontab; the line is inside the marked block at the bottom.

Watcher behavior:

- `git fetch`. If `origin/master` equals `$HOME/.cache/spy-backend/deployed-sha`, exit 0 and print nothing.
- Otherwise pull, build, test, and swap via `deploy-spy.sh --update`.
- On failure, roll back when a swap was left in progress, append `$HOME/.cache/spy-backend/watcher.log`, and exit non-zero (cron can mail that line).
- The same failed commit is retried on later nights. After 5 failed attempts (`SPY_WATCHER_MAX_FAILS`, `0` means unlimited) later nights exit 0 until a newer commit appears. Delete `$HOME/.cache/spy-backend/fail-state` to retry sooner.
- Exit 75 (another deploy holds the lock) and exit 76 (tunnel down) do not count toward that cap. Exit 76 does not roll Spy back.

## RAM

Hard caps (`mem_limit` = `memswap_limit`, so Spy is not allowed to grow into host swap):

| Container | Cap | Notes |
|---|---|---|
| `spy-mariadb` | 512m | `innodb_buffer_pool_size=256M`, performance schema off, binary log off |
| `spy-redis` | 80m | `maxmemory 64mb`, `allkeys-lru` |
| `spy-api` | 420m | Daphne, non-root, migrate + collectstatic on start |
| `spy-celery` | 280m | concurrency 1, non-root, `USE_REDIS=true` |
| `spy-nginx` | 32m | |

About 1.3GB of caps. The kernel OOM-kills a Spy cgroup that exceeds its cap instead of the portfolio. The pre-swap `spy-test` project is a second, smaller MariaDB (64M pool) plus API and nginx. It is removed before the live recreate. Expect swap use on the host during that window if the portfolio is busy. `allkeys-lru` can evict Celery keys if Redis hits 64MB; this app does not ship task modules yet.

`innodb_flush_log_at_trx_commit=2` and `O_DIRECT` cut eMMC writes. If MariaDB exits on boot on this Allwinner kernel, remove `--innodb-flush-method=O_DIRECT` from `infra/docker-compose.prod.yml`.

## Layout

| File | Role |
|---|---|
| `infra/docker-compose.prod.yml` | Live stack |
| `infra/docker-compose.prod.test.yml` | Pre-swap overlay (Compose 2.24+ `!override`) |
| `infra/docker/Dockerfile.api` | Same API image as dev; `python:3.12-slim` arm64 |
| `infra/env/prod.env.example` | Placeholders only |
| `infra/deploy/deploy-spy.sh` | Install, `--update`, `--rollback` |
| `infra/deploy/spy-watcher.sh` | Daily updater |
| `infra/deploy/install-spy-cron.sh` | User crontab |

Secrets live in `$HOME/.config/spy-backend/prod.env` only. Compose interpolates that file; keep values as hex without `$` or `#`.

## Manual health check

```bash
docker exec spy-nginx wget -q -O - \
  --header='Host: spy.way2points.com' \
  --header='X-Forwarded-Proto: https' \
  http://127.0.0.1/health/live/
docker exec spy-nginx wget -q -O - \
  --header='Host: spy.way2points.com' \
  --header='X-Forwarded-Proto: https' \
  http://127.0.0.1/health/ready/
```

`/health/ready/` is 200 when MariaDB answers `SELECT 1`. Prod Django redirects plain HTTP, so the probe sends `X-Forwarded-Proto: https`. After the Cloudflare hostname exists, `https://spy.way2points.com/health/live/` should return the same body.
