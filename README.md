# Spy Love

Consent-based device monitoring platform. This repository holds the Django API, local infrastructure, and docs. Pairing, scoped consent, event ingestion, real-time streams, sharing pause, safe zones, and keyword watchlists are implemented. Enterprise-scale and compliance items stay in the architecture docs as planned.

## Stack

| Layer | Technology (implemented) |
|-------|--------------------------|
| Mobile | Flutter (**Consent Horizon** UI) in the separate spy_app repository (`spy_love/`) |
| Backend | Django 5.1+, DRF, Channels (daphne), simplejwt (+ blacklist), Argon2 |
| Async | Celery configured in Compose but **no task modules yet**; event fan-out uses a background thread + Channels `group_send` |
| Database | MySQL 8+ (Compose: MySQL 8.4) |
| Cache / channels | Redis optional (`USE_REDIS=false` → locmem / in-memory channel layer / eager Celery) |
| Infra | `infra/docker-compose.yml`: MySQL, Redis, API (daphne), Celery worker, Nginx, Prometheus, Grafana |

- API: `/api/v1/` (Swagger: `/api/v1/docs/`)
- WebSocket: `/ws/v1/events/?token=<jwt>`
- Health: `/health/live/`, `/health/ready/`, `/health/`

## Product surface (current)

**Mobile UI** — Stitch “Consent Horizon” design (tokens, Inter typography, responsive breakpoints: compact `<600`, medium `<1024`, expanded `≥1024`). See [Flutter Architecture](docs/clients/FLUTTER_ARCHITECTURE.md).

**Consent behavior**

- Geofence events (`geofence.enter` / `geofence.exit`) require the **`location`** consent scope (not a separate scope).
- **Sharing pause** suspends telemetry upload/ingest only; it does **not** revoke or change consent scopes. Resume or expiry restores sharing.

**Notable APIs** (full contract in [API Design](docs/architecture/API_DESIGN.md))

| Area | Endpoints |
|------|-----------|
| Pause / resume | `POST /devices/owned/{id}/pause/`, `.../resume/` |
| Safe zones | `GET/POST /devices/safe-zones/`, `PATCH/DELETE /devices/safe-zones/{id}/` |
| Keywords | `GET/POST /devices/keywords/`, `DELETE /devices/keywords/{id}/` |
| Device photo | `PATCH /devices/{id}/` with `photo_url` (https only; server does not fetch) |
| Events | Contact payload fields on call/SMS; place/zone fields on location/geofence |

## Quick Start (local — no Docker)

### 1. Install MySQL 8+

Ensure the MySQL service is running.

### 2. Backend

From the repository root:

```powershell
.\scripts\setup-local.ps1
```

Or manually (expects a virtualenv at `venv/`):

```powershell
cd backend
..\venv\Scripts\pip.exe install -r requirements\dev.txt
..\venv\Scripts\python.exe manage.py migrate
..\venv\Scripts\python.exe manage.py runserver
```

Copy `backend/.env.example` to `backend/.env` if needed. Set `USE_REDIS=false` without Redis.
Never commit `.env` or keystores.

API docs: http://localhost:8000/api/v1/docs/

### Tests

From `backend/` (SQLite via `config.settings.test`):

```powershell
..\venv\Scripts\python.exe -m pytest
..\venv\Scripts\python.exe manage.py makemigrations --check --settings=config.settings.test
```

### 3. Flutter

The mobile app lives in the spy_app repository. Setup notes are in [Flutter Architecture](docs/clients/FLUTTER_ARCHITECTURE.md).

### Full stack (optional Docker)

See `infra/docker-compose.yml`, `infra/.env.example`, and [Deployment Plan](docs/architecture/DEPLOYMENT_PLAN.md).

## Documentation

| Doc | Purpose |
|-----|---------|
| [docs/architecture/](docs/architecture/) | System, DB, API, security, deployment |
| [docs/clients/FLUTTER_ARCHITECTURE.md](docs/clients/FLUTTER_ARCHITECTURE.md) | Consent Horizon client (spy_app repository) |
| [docs/operations/RELEASE_CHECKLIST.md](docs/operations/RELEASE_CHECKLIST.md) | Production cut checklist (backend, mobile, security, smoke) |

## Project Structure

```
.
├── backend/                 # Django project
│   ├── apps/                # accounts, tenants, devices, events, audit
│   ├── config/              # settings package, asgi, wsgi, urls, celery
│   ├── core/                # shared domain, middleware, presentation
│   ├── requirements/
│   └── tests/               # pytest modules grouped by area
├── docs/
│   ├── architecture/
│   ├── clients/
│   └── operations/
├── infra/                   # compose, image, nginx, prometheus
│   ├── docker/
│   ├── nginx/
│   └── prometheus/
└── scripts/                 # local MySQL + venv setup
```

Inside each Django app, keep the existing layering: `presentation` → `application` → `domain` (where present) → `infrastructure`.

## License

Proprietary — all rights reserved.
