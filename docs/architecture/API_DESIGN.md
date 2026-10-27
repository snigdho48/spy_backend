# API Design Specification v1

Base path: `/api/v1/` (e.g. `http://localhost:8000/api/v1` locally). OpenAPI: `/api/v1/schema/` · Swagger UI: `/api/v1/docs/`

Authentication: `Authorization: Bearer <access_token>`

> Documents the endpoints present in `backend/apps/*/presentation/urls.py`. Items under **Planned / not implemented** do not exist in code yet.

---

## Authentication

### POST `/auth/register/`
Register a new user and workspace (tenant).

**Request:**
```json
{
  "email": "user@example.com",
  "password": "at-least-10-chars",
  "full_name": "Jane Doe",
  "tenant_name": "Acme Corp"
}
```

**Response 201:** `user`, `tenant`, `tokens { access, refresh }`
**Throttle:** `auth` scope (10/min, `AuthRateThrottle`, anonymous/IP based)

### POST `/auth/login/`
**Request:** `{ "email": "...", "password": "..." }`
**Throttle:** `auth` scope (10/min)

### POST `/auth/google/`
Sign in / sign up with a Google ID token.
**Request:** `{ "id_token": "...", "full_name"?: "...", "tenant_name"?: "..." }`
**Throttle:** `auth` scope (10/min)

### POST `/auth/link/google/`
Link a Google account to the signed-in user. **Request:** `{ "id_token": "..." }`

### POST `/auth/link/password/`
Set a password for the signed-in user. **Request:** `{ "password": "..." }` (min 10 chars)

### POST `/auth/token/refresh/`
simplejwt `TokenRefreshView`. **Request:** `{ "refresh": "..." }`. Refresh tokens rotate and the old one is blacklisted (`ROTATE_REFRESH_TOKENS`, `BLACKLIST_AFTER_ROTATION`).

### POST `/auth/logout/`
**Request:** `{ "refresh": "..." }` — blacklists the refresh token.

### GET `/auth/me/`
Current user profile.

Token lifetimes: access ~15 min, refresh 7 days (env-configurable).

---

## Subscriptions / Workspaces

| Method | Path | Notes |
|--------|------|-------|
| GET | `/subscriptions/plans/` | Plans: `free`, `pro`, `enterprise` |
| GET | `/subscriptions/current/` | Current tenant plan |
| POST | `/subscriptions/subscribe/` | **Sets the plan directly; no payment integration** |
| POST | `/subscriptions/workspaces/` | Create a workspace |

---

## Devices

| Method | Path | Notes |
|--------|------|-------|
| GET | `/devices/` | Devices in the user's tenant (paginated, newest first, page size 20). Each device includes `photo_url` and `sharing` |
| GET | `/devices/owned/` | Devices owned by the signed-in user (monitored phone); returns `{ "results": [...] }` with `sharing` |
| GET | `/devices/owned/{device_id}/status/` | Pairing status poll: `device_id, device_name, status, tenant_name, is_linked, sharing` |
| POST | `/devices/owned/{device_id}/pause/` | Owner-only temporary pause of telemetry upload (see Sharing pause) |
| POST | `/devices/owned/{device_id}/resume/` | Owner-only end of pause |
| GET/POST | `/devices/safe-zones/` | Tenant safe-zone (geofence) list / create |
| PATCH/DELETE | `/devices/safe-zones/{zone_id}/` | Update / delete a safe zone |
| GET/POST | `/devices/keywords/` | Tenant keyword watchlist list / create |
| DELETE | `/devices/keywords/{keyword_id}/` | Delete a keyword |
| POST | `/devices/pair/initiate/` | See below |
| POST | `/devices/pair/complete/` | See below |
| GET | `/devices/{device_id}/` | Device detail including active `consent`, `photo_url`, `sharing` |
| PATCH | `/devices/{device_id}/` | Set optional `photo_url` (https only; server never fetches or proxies) |
| DELETE | `/devices/{device_id}/` | Delete device |
| POST | `/devices/{device_id}/disconnect/` | Stop monitoring: revokes consent, marks device disconnected |
| DELETE | `/devices/{device_id}/consent/` | Revoke consent / disconnect (204) |

### Sharing pause (telemetry only)

**Owner of the monitored device only.** Consent scopes are unchanged; only event upload is suspended.

**POST `/devices/owned/{device_id}/pause/`**
```json
{ "duration_minutes": 60, "reason": "optional" }
```
`duration_minutes` must be one of `15, 30, 60, 120, 240` (max 24h via service rules).

**Response 200:** `{ "device_id": "uuid", "sharing": { "paused": true, "paused_until": "...", "resumes_in_s": 3600 } }`

**POST `/devices/owned/{device_id}/resume/`** → same shape with `paused: false`.

While paused:
- Batch ingest returns accepted `0` with `paused: true` / `paused_until` (and may reject events whose timestamps fall in a pause window).
- The Flutter monitored client also skips uploads locally.
- WebSocket may emit `device_status` with sharing state.
- Audit: `sharing.paused` / `sharing.resumed`.

### Safe zones

**GET `/devices/safe-zones/`** — list tenant zones (monitors manage; monitored users may list for client geofence).

**POST `/devices/safe-zones/`**
```json
{
  "name": "School",
  "address": "optional",
  "lat": 40.7,
  "lng": -74.0,
  "radius_m": 500,
  "device_id": null
}
```
`device_id` optional (null = workspace-wide). Audited as `safe_zone.created` / `safe_zone.updated` / `safe_zone.deleted`.

### Keyword watchlist

**GET `/devices/keywords/`** — tenant keywords (`id`, `word`, `created_by_email`, `created_at`). Visible to owner/admin/monitor and the monitored user (list).

**POST `/devices/keywords/`** — `{ "word": "emergency" }` (owner/admin/monitor). Audited `keyword.created`.

**DELETE `/devices/keywords/{id}/`** — audited `keyword.deleted`.

### Device photo URL

**PATCH `/devices/{device_id}/`**
```json
{ "photo_url": "https://cdn.example.com/avatar.jpg" }
```
- `https` only (or empty string to clear). No credentials in URL. Max 2048 chars.
- Server stores the URL only — **never fetches or proxies** the image (client loads it).

### POST `/devices/pair/initiate/`
Called by the **monitored device's** signed-in user (any authenticated user; no workspace/plan needed).

**Request (all required):**
```json
{ "device_name": "Pixel 8", "platform": "android", "device_fingerprint": "stable-device-id" }
```
**Response 201:**
```json
{
  "pairing_id": "uuid",
  "device_id": "uuid",
  "pairing_code": "ABC123",
  "qr_payload": "spylove://pair?code=ABC123&token=...",
  "expires_at": "2026-06-23T12:30:00Z"
}
```

### POST `/devices/pair/complete/`
Called by the **monitor** account; the monitor chooses the consent scopes. `ConsentRecord.granted_by` is the device owner.

**Request:**
```json
{
  "pairing_code": "ABC123",
  "consent_scopes": ["location", "call_log", "sms"],
  "consent_version": "1.0.0"
}
```
`consent_scopes` must be non-empty and drawn from: `location, battery, network, app_usage, device_info, notifications, call_log, sms, messaging, sim`.

**Response 201:** `{ "device": {...}, "consent": { id, scopes, consent_version, granted_at, revoked_at } }`

### Consent updates
There is **no** `POST /devices/{id}/consent/` to update scopes in place. Consent can only be granted at pair-complete and revoked via `DELETE /devices/{id}/consent/` or `POST /devices/{id}/disconnect/`.

### Consent scope mapping (ingest)

| Event type prefix / type | Required consent scope |
|--------------------------|------------------------|
| `location.*` | `location` |
| `geofence.enter`, `geofence.exit` | `location` (same as location; not a separate scope) |
| `call.*` | `call_log` |
| `sms.*` | `sms` |
| `message.*` / notification alerts | `notifications` / messaging as configured |
| `sim.*` | `sim` |
| `battery.*` | `battery` |
| `network.*` | `network` |
| `app_usage.*` | `app_usage` |
| `device_info.*` | `device_info` |

**Pause vs consent:** sharing pause does **not** revoke or alter consent scopes. It only blocks telemetry acceptance/upload until resume or expiry.

---

## Events

### POST `/events/batch/`
Ingest device events. Called by the monitored device's owner; the device must be `active` and owned by the caller.

**Request:**
```json
{
  "device_id": "uuid",
  "events": [
    {
      "event_type": "location.update",
      "payload": {
        "lat": 40.7,
        "lng": -74.0,
        "place_name": "Westwood High",
        "address": "optional",
        "zone_id": "optional-uuid"
      },
      "idempotency_key": "optional-unique-key",
      "timestamp": "2026-06-23T12:00:00Z"
    }
  ]
}
```
- `events`: 1–100 items; `payload`, `idempotency_key`, `timestamp` optional.
- Consent scope is checked per event; rejected events are reported individually, valid ones are still saved.
- Duplicate `idempotency_key` is reported as a rejected item (not a request-level 409).
- If sharing is paused: response may include `paused: true` and accept `0` events.

**Response 202:** `{ "accepted": 1, "rejected": 0, "errors": [ { "index": 0, "message": "..." } ], "paused"?: true, "paused_until"?: "..." }`
**Throttle:** `events` scope, 1000/min **per authenticated user** (`EventRateThrottle`), not per device.

### Location / geofence payloads

- `location.update` may include `place_name`, `address`, `zone_id`.
- `geofence.enter` / `geofence.exit` require a known safe zone (`zone_id` or resolvable `zone_name`). Server may enrich zone display names. Client emits these against `/devices/safe-zones/` while location consent is active and sharing is not paused.

### Contact fields on `call.*` / `sms.*`

Optional payload fields (validated; photos never fetched by the server):

| Field | Rules |
|-------|--------|
| `contact_name` | string |
| `contact_photo_url` | https URL only |
| `is_known`, `is_flagged`, `is_redacted` | booleans |
| Redaction | When `is_redacted` is true, body/text preview fields are cleared server-side |

### GET `/events/`
List events for the user's tenant (paginated, newest first by `event_timestamp`).
**Query:** `device_id`, `event_type`, `event_prefix` (matches `<prefix>.*`), plus pagination. There are no `from`/`to` filters.

**Event types in use:** `location.update`, `geofence.enter`, `geofence.exit`, `call.*`, `sms.*`, `message.notification`, `sim.*`, plus battery/network/app_usage/device_info when collectors run.

---

## WebSocket

### `ws(s)://<host>/ws/v1/events/?token=<access_jwt>`
JWT is passed in the `token` query parameter (an `Authorization: Bearer` header is also accepted by the consumer). Close codes: `4001` unauthenticated, `4003` no active tenant.

On connect the socket joins the group `tenant_<tenant_id>_events`: **all events for the tenant are pushed**; the `subscribe` message is acknowledged but does **not** filter.

**Subscribe (acknowledged only):** `{ "action": "subscribe", "device_ids": ["uuid"] }` → `{ "type": "subscribed", "device_ids": [...] }`

**Event push:**
```json
{
  "type": "event",
  "device_id": "uuid",
  "event_type": "location.update",
  "payload": { "lat": 40.7, "lng": -74.0 },
  "timestamp": "2026-06-23T12:00:00Z"
}
```
Pushes are produced by a background thread after ingest (`group_send`), not by Celery.

---

## Audit

### GET `/audit/`
Tenant-scoped audit log (paginated). **Query:** `actor_id`, `action`. (No date range filter; no `audit.view_auditlog` permission check documented in code.)

---

## Health (no `/api/v1` prefix)

- `GET /health/` → `{ "status": "healthy|degraded", "db": "ok|error", "redis": "ok|error", "version": "1.0.0" }` (the `redis` key reflects the configured cache backend; with `USE_REDIS=false` this is locmem)
- `GET /health/ready/` → `{ "status": "ready" }` or 503 `not_ready` (DB check)
- `GET /health/live/` → `{ "status": "alive" }`

---

## Error Responses

Domain errors and DRF errors are wrapped by `core.presentation.exceptions.custom_exception_handler`:

```json
{ "error": { "code": "<domain code or api_error>", "message": "...", "details": { } } }
```
`details` is present for DRF-generated errors (e.g. validation, throttling, auth).

| Status | Cause |
|--------|-------|
| 400 | Validation error |
| 401 | Missing/invalid token |
| 403 | Permission denied or consent required |
| 404 | Entity not found |
| 409 | Conflict |
| 429 | Throttled (DRF) |

---

## Rate Limits (DRF throttling, implemented)

| Scope | Rate | Applies to |
|-------|------|-----------|
| `anon` | 20/min | Default for unauthenticated requests |
| `user` | 100/min | Default for authenticated requests |
| `auth` | 10/min | Register, login, Google login |
| `events` | 1000/min | `POST /events/batch/` (per user) |

---

## Planned / not implemented

- `POST /devices/{id}/consent/` — in-place scope update
- `GET /users/me/export/`, `DELETE /users/me/` — GDPR export/erasure
- Per-device throttles, 5/hour register limit, one-WebSocket-per-user limit
- Server-side WebSocket subscription filtering by `device_ids`
- Event list `from`/`to` filters; audit log date filters
- Permission-code based RBAC (`devices.view_device`, `audit.view_auditlog`)