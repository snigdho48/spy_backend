# Deployment Plan

> **Status:** a local / single-host stack exists in `infra/`. The DigitalOcean, Kubernetes, Cloudflare and GitLab CI/CD sections are **planned / not implemented** (no `.gitlab-ci.yml`, `.do/` specs or K8s manifests in the repo).

**Before shipping:** follow the concrete steps in [docs/operations/RELEASE_CHECKLIST.md](../operations/RELEASE_CHECKLIST.md) (prod settings, MySQL backups, HTTPS/WSS, health probes, Android signing, smoke: pair → ingest → pause/resume → safe zone → revoke).

## Implemented: Local & Docker Compose

| Path | Purpose |
|------|---------|
| `scripts/setup-local.ps1` | No-Docker local setup (MySQL 8+, venv, migrate) with `USE_REDIS=false` |
| `infra/docker-compose.yml` | MySQL 8.4 (`utf8mb4`), Redis 7, API (daphne via `infra/docker/Dockerfile.api`), Celery worker (`celery -A config worker`), Nginx 1.27, Prometheus 2.54, Grafana 11.2 |
| `infra/nginx/nginx.conf` | Reverse proxy for API/WebSocket |
| `infra/prometheus/prometheus.yml` | Prometheus scrape config |

Notes:
- The Celery worker runs, but the project has **no Celery task modules**; it is idle.
- Redis is optional for the API (`USE_REDIS=false` → in-memory/locmem/eager).
- Compose contains development credentials (e.g. MySQL passwords); treat it as a dev / prod-like starting point, not a hardened production config. Override secrets via env.
- Health endpoints for probes exist: `GET /health/`, `/health/ready/`, `/health/live/`.

## Environments

| Environment | Purpose | Infrastructure | Status |
|-------------|---------|----------------|--------|
| `dev` | Local development | Local MySQL + `runserver`, or Docker Compose | Implemented |
| `staging` | Pre-production testing | DO App Platform (1 instance) | Planned |
| `production` | Live traffic | DO Kubernetes / App Platform (HA) | Planned |

## Production Topology — Planned

```
Internet → Cloudflare (WAF/CDN) → DO Load Balancer
    → Nginx (2+ pods) → Django API (4+ pods)
    → Channels workers (2+ pods)
    → Celery workers (4+ pods)
    → Managed MySQL (Primary + 2 replicas)
    → Managed Redis (HA cluster)
    → Spaces (S3 media + backups)
```

## Zero-Downtime Deployment — Planned

1. Blue/green deployment via DO App Platform or K8s rolling updates
2. `maxUnavailable: 0`, `maxSurge: 1` for API pods
3. Readiness probe: `GET /health/ready/` (exists)
4. Liveness probe: `GET /health/live/` (exists)
5. Pre-deploy: run migrations in init container
6. Post-deploy: smoke test auth + health endpoints

## CI/CD Pipeline (GitLab) — Planned / not implemented

```yaml
stages:
  - lint
  - test
  - build
  - deploy-staging
  - deploy-production

lint:
  - ruff check backend/
  - flutter analyze

test:
  - pytest backend/ --cov=apps --cov-fail-under=80
  - flutter test

build:
  - docker build -f infra/docker/Dockerfile.api

deploy-staging:
  - doctl apps update staging --spec .do/app-staging.yaml

deploy-production:
  - manual trigger
  - doctl apps update production --spec .do/app-production.yaml
```

## Rollback Strategy — Planned

1. Keep previous 3 container images in registry
2. `doctl apps create-deployment --force-rebuild=false` with previous image tag
3. Database migrations: forward-only; rollbacks use reverse migrations only in staging

## Disaster Recovery — Planned targets

| Scenario | RTO | RPO | Action |
|----------|-----|-----|--------|
| API pod failure | < 30s | 0 | K8s auto-restart |
| DB primary failure | < 5min | < 1min | Managed MySQL failover |
| Region outage | < 1hr | < 5min | DNS failover to secondary region |
| Data corruption | < 4hr | < 24hr | Point-in-time / backup restore |

## Secret Management

- **Implemented:** development uses a `.env` file (never committed; see `backend/.env.example`).
- **Planned:** staging/production via DigitalOcean App Platform encrypted env vars; quarterly rotation of `SECRET_KEY` and JWT signing keys.

## WAF Recommendations (Cloudflare) — Planned

- Rate limiting: 100 req/min per IP on `/api/v1/auth/`
- OWASP Core Ruleset enabled
- Bot fight mode on auth endpoints
- Geo-blocking optional per tenant policy