# Spy Love — Release Checklist

Concrete, repo-specific steps before a production cut. Mark owner decisions as **TODO(user)**. Do not commit secrets, `.env`, or keystores.

Related: [DEPLOYMENT_PLAN.md](../architecture/DEPLOYMENT_PLAN.md), [SECURITY_MODEL.md](../architecture/SECURITY_MODEL.md), [API_DESIGN.md](../architecture/API_DESIGN.md).

---

## Backend

### Production settings (`backend/config/settings/prod.py` + env)

- [ ] Deploy with `DJANGO_SETTINGS_MODULE=config.settings.prod` (or equivalent) so `DEBUG = False`.
- [ ] **TODO(user):** Set a unique strong `SECRET_KEY` in production env (never reuse the default from `base.py` / local `.env`).
- [ ] **TODO(user):** Set `ALLOWED_HOSTS` to the real API hostname(s) only (CSV). Remove `localhost` / `.ngrok-free.app` from prod.
- [ ] **TODO(user):** Set `CORS_ALLOWED_ORIGINS` to the real web origins if any; do **not** use `CORS_ALLOW_ALL_ORIGINS` (that is only in `settings/dev.py`).
- [ ] Confirm prod enables `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`, HSTS, and `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` (already in `prod.py`).
- [ ] Confirm reverse proxy (see `infra/nginx/nginx.conf`) forwards `X-Forwarded-Proto` / `Host` correctly for HTTPS and WebSocket (`/ws/`).

### Database (MySQL)

- [ ] **TODO(user):** Configure automated MySQL backups (full + restore drill). Compose alone is not a backup plan.
- [ ] Run migrations on the production DB before traffic:  
  `python manage.py migrate` (from `backend/`, prod settings + credentials).
- [ ] Confirm migrations through devices `0005_device_photo_url` (and earlier pause / safe zone / keyword) are applied.

### HTTPS / WSS and Channels

- [ ] API served only over HTTPS; clients use `wss://` for `/ws/v1/events/`.
- [ ] Run ASGI (daphne / Channels) — not bare `runserver` — for WebSockets in prod (`infra/docker-compose.yml` uses daphne).
- [ ] **TODO(user):** Set `USE_REDIS=true` and a production Redis URL for the channel layer + cache (avoid in-memory channel layer with multiple workers).
- [ ] Confirm Nginx (or LB) upgrades WebSocket connections for `/ws/`.

### Health checks

- [ ] Liveness probe: `GET /health/live/`
- [ ] Readiness probe: `GET /health/ready/` (DB reachable)
- [ ] Optional: `GET /health/` as documented in compose / deployment plan

### Django admin

Staff sign in at `/admin/` (`python manage.py createsuperuser` prompts for email, the user model's `USERNAME_FIELD`). Concrete models in accounts, tenants, devices, events, and audit are registered on the default admin site with changelist filters and search. Password updates go through Django's admin password form. Refresh-token ids, pairing codes and tokens, and password hashes stay off changelist columns; device events and audit logs are inspect-only so operators can read payloads and metadata without rewriting history.

### Logs and audit retention

- [ ] **TODO(user):** Define log retention (app / access / error) and shipping destination.
- [ ] **TODO(user):** Define `AuditLog` retention / archival policy (no automated purge in code today; see SECURITY_MODEL).
- [ ] Confirm sensitive values are not logged (pairing tokens, JWTs in query strings).

---

## Mobile (`spy_love/`)

### Signing and identity

- [ ] Release builds use `android/key.properties` + keystore referenced by `android/app/build.gradle.kts` (`signingConfigs.project`). **Never commit** `key.properties`, `*.jks`, `*.keystore`.
- [ ] **TODO(user):** Create / store the Play upload keystore off-repo; document recovery with the team.
- [ ] Package name: `org.hmg.spy_love` (`applicationId` / `namespace` in `build.gradle.kts`).
- [ ] **TODO(user):** Bump `version` / `versionCode` in `spy_love/pubspec.yaml` (currently `1.0.0+1`) for the store build.

### Permissions ↔ consent scopes

Manifest permissions must match what you disclose and what consent scopes allow. Current `AndroidManifest.xml` includes:

| Permission | Typical consent / feature |
|------------|---------------------------|
| `INTERNET`, `ACCESS_NETWORK_STATE` | Always |
| `ACCESS_FINE/COARSE/BACKGROUND_LOCATION` | `location` (+ geofence enter/exit) |
| `READ_CALL_LOG` | `call_log` |
| `READ_SMS`, `RECEIVE_SMS` | `sms` |
| `READ_PHONE_STATE`, `READ_PHONE_NUMBERS` | SIM / phone state |
| `CAMERA` | QR scan (pairing) |
| `POST_NOTIFICATIONS` | Alerts |
| `PACKAGE_USAGE_STATS` | `app_usage` (Usage Access settings) |
| Notification listener service | `notifications` / message alerts |

- [ ] Play Console Data safety / permissions declarations match the above and in-app consent copy.
- [ ] **TODO(user):** Finalize privacy policy URL and consent disclosures for the store listing.

### Release hardening

- [ ] **TODO(user):** Decide whether to enable R8/ProGuard for release (`isMinifyEnabled` / `isShrinkResources` are currently `false` in `build.gradle.kts`). If enabling, add keep rules for Flutter / Firebase / MethodChannels and smoke-test collectors.
- [ ] Remove or gate debug-only logging before store builds.

### API / WebSocket URLs (prod)

Build-time overrides (see `lib/app/core/config/app_config.dart`):

```bash
flutter build appbundle \
  --dart-define=API_BASE_URL=https://YOUR_HOST/api/v1 \
  --dart-define=WS_BASE_URL=wss://YOUR_HOST/ws/v1/events/ \
  --dart-define=GOOGLE_WEB_CLIENT_ID=YOUR_WEB_CLIENT_ID
```

- [ ] **TODO(user):** Set production `API_BASE_URL` and `WS_BASE_URL` (defaults in code point at a ngrok tunnel — do not ship that).
- [ ] **TODO(user):** Set production `GOOGLE_WEB_CLIENT_ID` for Google Sign-In on Android.
- [ ] Strip or avoid relying on `ngrok-skip-browser-warning` header in production clients if the API is on a real host.

### Inter font (offline)

- [ ] Theme uses Inter via `google_fonts` (network fetch). For offline / first-frame reliability: **TODO(user)** bundle Inter under `assets/fonts/`, declare in `pubspec.yaml`, and point `app_theme.dart` at the asset family (see Stitch COMPARISON note about phone `flutter run` vs goldens).
- [ ] Verify UI on a device with no network after cold start.

---

## Security

- [ ] No test fixtures, demo tenants, or seed passwords left in production DB.
- [ ] **TODO(user):** Rotate any keys/passwords that were used in local/dev/ngrok (Django `SECRET_KEY`, MySQL, Redis, Google OAuth client secrets, JWT-related secrets).
- [ ] Confirm DRF rate limits are active (anon / user / auth / events throttles in settings).
- [ ] Run security tests from `backend/`:

```powershell
# from the repository root; settings come from backend/pytest.ini
cd backend
..\venv\Scripts\python.exe -m pytest tests/security tests/api
```

- [ ] Confirm `photo_url` / `contact_photo_url` are https-only and the **server never fetches** those URLs (SSRF avoidance).
- [ ] Confirm sharing pause does not alter consent; revoke still uses disconnect / `DELETE .../consent/`.

---

## Final smoke (staging or prod-like)

Use two accounts/devices where possible (monitor + monitored).

1. [ ] Register / login (email or Google).
2. [ ] Pair: initiate on monitored device → complete on monitor with consent scopes → device shows linked.
3. [ ] Ingest: location (and optionally call/SMS) appears in activity feed / events API.
4. [ ] Pause sharing on owned device → ingest accepted `0` / client stops upload → resume → events flow again; consent scopes unchanged.
5. [ ] Create a safe zone → trigger or simulate `geofence.enter` / `exit` (requires `location` consent) → event visible to monitor.
6. [ ] Add / delete a watchlist keyword; confirm list on both roles as designed.
7. [ ] Revoke / disconnect → further ingest rejected; device no longer actively monitoring.

Optional: open WebSocket subscribe for the device and confirm live updates after ingest.

---

## Sign-off

| Role | Name | Date | Notes |
|------|------|------|-------|
| Backend | **TODO(user)** | | |
| Mobile | **TODO(user)** | | |
| Security | **TODO(user)** | | |
