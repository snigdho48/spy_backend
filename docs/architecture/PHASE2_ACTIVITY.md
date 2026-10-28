# Phase 2 — Activity feed (merged device timeline)

All paths relative to `<API_BASE>`. Auth: `Authorization: Bearer <access_token>`.
Gated by `DeviceAccessService` (owner or OWNER/ADMIN/MONITOR). VIEWER → 403.
Consent scopes are enforced at ingestion time, so this read endpoint mirrors the
other device feeds and does not re-check scopes.

## Endpoint

### GET `<API_BASE>/events/activity/`

Returns one reverse-chronological page merging a device's `DeviceEvent` rows and
`Alert` rows into a single stream. Powers the monitor-side Activity timeline.

| Query param | Required | Notes |
|-------------|----------|-------|
| `device_id` | yes | UUID of the device |
| `from` / `to` | no | ISO-8601 window bounds (inclusive) |
| `types` | no | Comma-separated categories (default: all). One of `location`, `app_inventory`, `notifications`, `app_usage`, `telemetry`, `contacts`, `calls`, `sms`, `messages`, `alerts` |
| `cursor` | no | Opaque cursor from a previous page's `next` |
| `limit` | no | 1–100 (default 50) |

**Response:**

```json
{
  "device_id": "<uuid>",
  "results": [
    {
      "source": "alert",
      "id": "<uuid>",
      "category": "alerts",
      "event_type": "low_battery",
      "timestamp": "2026-01-01T12:00:00+00:00",
      "title": "Battery critically low",
      "body": "5% remaining",
      "severity": "critical",
      "payload": {"battery_pct": 5}
    },
    {
      "source": "event",
      "id": "<uuid>",
      "category": "telemetry",
      "event_type": "device.telemetry",
      "timestamp": "2026-01-01T11:40:00+00:00",
      "title": "",
      "body": "",
      "severity": null,
      "payload": {"battery_pct": 55, "charging": true}
    }
  ],
  "next": "<opaque-cursor-or-null>"
}
```

**Category → event_type prefixes** (events); `alerts` pulls from the Alert table:

| Category | Prefixes |
|----------|----------|
| `location` | `location.`, `geofence.` |
| `app_inventory` | `app_inventory.` |
| `notifications` | `notification.` |
| `app_usage` | `app_usage.` |
| `telemetry` | `device.` |
| `contacts` | `contact.` |
| `calls` | `call.` |
| `sms` | `sms.` |
| `messages` | `message.` |

**Errors:** `400` for missing `device_id` / bad range / unknown `types` / bad
`cursor` / non-integer `limit`; `403` when the caller cannot access the device;
`404` when the device is absent from the tenant.

## Implementation notes
- Bounded offset cursor: since the merged stream is ordered by timestamp desc,
  the first `offset + limit` merged items come from at most `offset + limit + 1`
  rows of each source, so each source query is sliced to that bound (no
  full-table scans, TX6 RAM-friendly). Max offset is capped at 5000.
- Event payloads are decrypted via Fernet before serialising; alert `payload`
  is the alert `metadata`.
- Read-only. **No new migrations.**
