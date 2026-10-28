# Phase 1 — Geofencing, Alerts & Push

All paths are relative to `<API_BASE>`. Auth: `Authorization: Bearer <access_token>`.
`DeviceAccessService` BOLA applies: owner or OWNER/ADMIN/MONITOR. VIEWER → 403 on
device-scoped reads/writes (deletes always require monitor/owner).

## Consent scopes (new / reused)

| Scope | Notes |
|-------|-------|
| `location` (existing) | Gates `location.*`; powers server-side geofence evaluation |
| `sim` (existing) | Gates `sim.changed` |
| `telemetry` (from feeds PR) | Gates `device.telemetry` → low_battery alerts |
| `app_usage` (existing) | Gates `app_inventory.*` → app_installed alerts |
| `sos` (**new**) | Gates `sos.triggered` |

## Event types (new)

| Event | Scope | Alert produced |
|-------|-------|----------------|
| `location.update` / `location.snapshot` | `location` | `geofence_enter` / `geofence_exit` on state change |
| `sim.changed` | `sim` | `sim_changed` |
| `device.telemetry` | `telemetry` | `low_battery` when `battery_pct <= LOW_BATTERY_THRESHOLD_PCT` (default 15) and not charging |
| `sos.triggered` | `sos` | `sos` (severity `critical`) |
| `app_inventory.snapshot` | `app_usage` | `app_installed` for each newly-seen package |

## Geofencing (extends SafeZone)

Safe zones already support CRUD at `<API_BASE>/devices/safe-zones/`. This
increment adds:

- `enabled` boolean (default `true`) on create/patch/list responses.
- Server-side enter/exit evaluation on every accepted `location.*` event.
- `GeofenceState` row per `(device, safe_zone)` storing last-known inside/outside.
  First observation sets the baseline (no alert). Subsequent transitions only
  fire when the boolean flips (debounce against GPS jitter).

Safe-zone write body (create):
```json
{
  "name": "Home", "lat": 23.81, "lng": 90.41,
  "radius_m": 100, "address": "", "device_id": "<uuid|null>",
  "enabled": true
}
```

## Alerts

### Model shape
```json
{
  "id": "<uuid>", "device_id": "<uuid>",
  "type": "geofence_enter|geofence_exit|app_installed|sim_changed|low_battery|sos",
  "severity": "info|warning|high|critical",
  "title": "...", "body": "...", "metadata": {},
  "created_at": "...", "read_at": null, "is_read": false
}
```

### Endpoints
| Method | Path | Notes |
|--------|------|-------|
| GET | `<API_BASE>/alerts/?device_id=&type=&unread=true` | Paginated list |
| POST | `<API_BASE>/alerts/<id>/read/` | Mark one read |
| POST | `<API_BASE>/alerts/read-all/?device_id=` | Mark all (optionally per device) |
| DELETE | `<API_BASE>/alerts/<id>/` | Owner/monitor only; VIEWER → 403 |

## Push tokens + FCM

| Method | Path |
|--------|------|
| POST | `<API_BASE>/alerts/push-tokens/` body `{ "token": "...", "platform": "android\|ios\|web" }` |
| DELETE | `<API_BASE>/alerts/push-tokens/<id>/` |

On every new alert a Celery task `alerts.push_alert_notification` is enqueued.
It fans out to the device owner's and workspace monitors' registered tokens via
a lightweight FCM HTTP v1 client (google-auth JWT + `requests`). When
`FCM_CREDENTIALS_PATH` (or `GOOGLE_APPLICATION_CREDENTIALS`) is unset / missing,
the client no-ops.

## Env / secrets (prod)

| Variable | Purpose |
|----------|---------|
| `FCM_CREDENTIALS_PATH` | Absolute path to a Google service-account JSON with FCM scope. **Never commit.** |
| `LOW_BATTERY_THRESHOLD_PCT` | Optional; default `15`. |

## Migrations
- `devices/0007_safezone_enabled_geofencestate` — `SafeZone.enabled` + `GeofenceState`
- `alerts/0001_initial` — `Alert` + `PushToken`

## ARM64 / RAM notes
- No `firebase-admin` / `grpcio` (heavy to build on the TX6). HTTP v1 only.
- Alert hooks run after the ingest transaction commits so Celery never races.
