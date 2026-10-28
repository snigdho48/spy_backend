# Phase 1 — Telemetry & App-Usage Feeds

All paths are relative to the API base, shown here as `<API_BASE>` (no real
hosts are documented). Auth: `Authorization: Bearer <access_token>`.
Every endpoint enforces `DeviceAccessService` object-level authorization: the
device owner or a workspace member with OWNER/ADMIN/MONITOR role. A VIEWER-only
member receives `403`.

## Consent scopes

| Scope | Catalog label | Gated event prefixes |
|-------|---------------|----------------------|
| `telemetry` (new) | Device telemetry | `device.*` |
| `app_usage` (existing) | App usage | `app_usage.*` |

Feeds refuse ingestion when the scope is not consented: the event is counted in
`rejected` with a `consent_required` reason; no row is stored.

## Event types

### `device.telemetry` (scope `telemetry`)
Device-reported telemetry. Suggested payload:
```json
{
  "battery_pct": 42,
  "charging": false,
  "network_type": "wifi",
  "storage_free": 1000000000,
  "storage_total": 4000000000,
  "ram_free": 300000000,
  "ram_total": 3000000000
}
```
Upserts a latest `DeviceTelemetrySnapshot` and is retained in the event feed.

### `app_usage.snapshot` (scope `app_usage`, already defined)
Per-app foreground time and launch counts for a reporting window:
```json
{
  "period_start": "2026-10-28T00:00:00Z",
  "period_end": "2026-10-28T01:00:00Z",
  "apps": [
    { "package": "com.example.app", "app_name": "Example",
      "foreground_ms": 1000, "launches": 2 }
  ]
}
```

## Endpoints

### GET `<API_BASE>/events/telemetry/latest/?device_id=<uuid>`
Latest telemetry snapshot.
**200:**
```json
{
  "device_id": "<uuid>", "battery_pct": 42, "charging": false,
  "network_type": "wifi", "storage_free": 1000, "storage_total": 4000,
  "ram_free": null, "ram_total": null, "metrics": { ... },
  "captured_at": "...", "updated_at": "..."
}
```
`404` when no snapshot exists, `400` when `device_id` missing.

### GET `<API_BASE>/events/telemetry/?device_id=<uuid>&limit=50`
Short history of `device.telemetry` events, newest first (`limit` 1–200).
**200:** `{ "device_id": "<uuid>", "results": [ { "payload": {...}, "timestamp": "..." } ] }`

### GET `<API_BASE>/events/app-usage/latest/?device_id=<uuid>`
Latest app-usage snapshot.
**200:** `{ "device_id", "apps": [...], "app_count", "period_start", "period_end", "captured_at", "updated_at" }`

### GET `<API_BASE>/events/app-usage/?device_id=<uuid>&from=<iso>&to=<iso>`
Per-app totals aggregated across `app_usage.snapshot` events in the range
(`from`/`to` optional ISO-8601).
**200:**
```json
{
  "device_id": "<uuid>", "from": "...", "to": "...", "app_count": 1,
  "results": [
    { "package": "com.example.app", "app_name": "Example",
      "foreground_ms": 2000, "launches": 4 }
  ]
}
```
Results are sorted by `foreground_ms` descending.

## Migrations
- `events/0003_deviceappusagesnapshot_devicetelemetrysnapshot` — adds
  `DeviceAppUsageSnapshot` and `DeviceTelemetrySnapshot` latest-snapshot tables.
