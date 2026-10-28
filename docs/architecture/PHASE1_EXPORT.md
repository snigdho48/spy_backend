# Phase 1 — Device report export (CSV / PDF)

All paths relative to `<API_BASE>`. Auth: `Authorization: Bearer <access_token>`.
Gated by `DeviceAccessService` (owner or OWNER/ADMIN/MONITOR). VIEWER → 403.

## Endpoint

### GET `<API_BASE>/events/export/`

| Query param | Required | Notes |
|-------------|----------|-------|
| `device_id` | yes | UUID of the device |
| `from` / `to` | no | ISO-8601 range bounds |
| `feeds` | no | Comma-separated: `events`, `locations`, `app_usage`, `alerts`, `telemetry` (default: events,locations,app_usage,alerts) |
| `export_format` | no | `csv` (default) or `pdf`. Alias: `fmt`. **Do not use `format=`** — DRF reserves it for content negotiation. |

**CSV response:** `Content-Type: text/csv; charset=utf-8`, streamed
(`StreamingHttpResponse`). Columns:
`feed,timestamp,type,title,body,payload_json`.

**PDF response:** `Content-Type: application/pdf` (reportlab, single-pass).
Sections mirror the selected feeds.

**Errors:** `400` for missing `device_id` / bad range / unknown feed /
unknown `export_format`; `403` when the caller cannot access the device;
`404` when the device is absent from the tenant.

## Implementation notes
- CSV uses the stdlib `csv` module + a tiny `Echo` writer so rows are
  yielded one at a time (TX6 RAM-friendly).
- PDF uses `reportlab` (already ARM64-friendly wheels).
- Sensitive payload fields are decrypted via Fernet before serialising.
- No new migrations.

## Dependency
- `reportlab>=4.2,<5.0` added to `requirements/base.txt`.
