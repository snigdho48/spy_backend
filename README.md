# Spy Love

Consent-based device monitoring platform. Pairing, scoped consent, event ingestion, real-time streams, sharing pause, safe zones, and keyword watchlists are implemented. Enterprise-scale and compliance items stay in the architecture docs as planned.

## Stack

| Layer | Technology (implemented) |
|-------|--------------------------|
| Mobile | Flutter (`spy_love/`), **Consent Horizon** UI, `provider`, `AppNavigator`, `one_request` |
| Backend | Django 5.1+, DRF, Channels (daphne), simplejwt (+ blacklist), Argon2 |
| Async | Celery configured in Compose but **no task modules yet**; event fan-out uses a background thread + Channels `group_send` |
| Database | MySQL 8+ (Compose: MySQL 8.4) |
| Cache / channels | Redis optional (`USE_REDIS=false` → locmem / in-memory channel layer / eager Celery) |
| Infra | `infra/docker-compose.yml`: MySQL, Redis, API (daphne), Celery worker, Nginx, Prometheus, Grafana |

- API: `/api/v1/` (Swagger: `/api/v1/docs/`)
- WebSocket: `/ws/v1/events/?token=<jwt>`
- Health: `/health/live/`, `/health/ready/`, `/health/`

## Product surface (current)

**Mobile UI** — Stitch “Consent Horizon” design (tokens, Inter typography, responsive breakpoints: compact `<600`, medium `<1024`, expanded `≥1024`). See [Flutter Architecture](docs/architecture/FLUTTER_ARCHITECTURE.md) and `spy_love/.cursor/stitch-phase1/`.

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

```powershell
cd D:\Spy_LOve\backend\scripts
.\setup-local.ps1
```

Or manually:

```powershell
cd D:\Spy_LOve\backend
..\venv\Scripts\pip.exe install -r requirements\dev.txt
..\venv\Scripts\python.exe manage.py migrate
..\venv\Scripts\python.exe manage.py runserver
```

Copy `backend\.env.example` to `backend\.env` if needed. Set `USE_REDIS=false` without Redis.  
Never commit `.env` or keystores.

API docs: http://localhost:8000/api/v1/docs/

### 3. Flutter

```bash
cd spy_love
flutter pub get
flutter run
```

Override API/WS with `--dart-define=API_BASE_URL=...` and `--dart-define=WS_BASE_URL=...` (see `spy_love/README.md`).

### Full stack (optional Docker)

See `infra/docker-compose.yml` and [Deployment Plan](docs/architecture/DEPLOYMENT_PLAN.md).

## Documentation

| Doc | Purpose |
|-----|---------|
| [docs/architecture/](docs/architecture/) | System, DB, API, Flutter, security, deployment |
| [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) | Production cut checklist (backend, mobile, security, smoke) |
| [spy_love/README.md](spy_love/README.md) | App-specific setup and UI notes |

## Project Structure

```
Spy_LOve/
├── backend/          # Django API (accounts, tenants, devices, events, audit)
├── spy_love/         # Flutter app (Consent Horizon UI)
├── infra/            # docker-compose, Nginx, Prometheus
└── docs/             # Architecture + release checklist
```

## License

Proprietary — all rights reserved.
