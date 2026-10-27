# Flutter Architecture

> Describes the Consent Horizon Flutter app (`spy_love/` in the separate spy_app repository). Items under **Planned / not implemented** are not in the code.

## Stack (Implemented)

| Concern | Implementation |
|---------|----------------|
| State management | `provider` (`ChangeNotifier` controllers wired in `lib/app/app_providers.dart`) |
| Navigation | `AppNavigator` (`core/navigation/app_navigator.dart`) with `onGenerateRoute` and route names in `routes/app_routes.dart` |
| HTTP | `one_request` via `core/network/api_service.dart`, `network_service.dart`, `one_request_config.dart` |
| Real-time | `core/network/event_stream_client.dart` (WebSocket to `/ws/v1/events/?token=`) |
| Storage | `flutter_secure_storage` (tokens), `device_fingerprint_storage.dart`, `hive` dependency |
| Auth | Email/password + Google Sign-In (`google_sign_in_service.dart`, Firebase core) |
| Pairing | `qr_flutter` (show QR), `mobile_scanner` (scan QR) |
| Collectors / monitoring | `geolocator` (+ geofence vs safe zones), `call_log`, SMS/notification/SIM/collectors bridges under `core/monitoring/` |
| Maps | `flutter_map` (location tab) |
| Design system | **Consent Horizon** (Stitch): `app_colors`, `app_theme`, `app_tokens`, Inter via `google_fonts` |
| Responsive | `AppBreakpoints` + `ResponsiveBody` / `TwoPaneLayout` |

Not used: Riverpod, GoRouter, Dio as a direct dependency.

## Consent Horizon UI

- Visual source of truth: Stitch project screens mirrored under `spy_love/.cursor/stitch-phase1/` (see `COMPARISON.md`).
- Theme: navy / soft status colors, Inter typography, shared widgets (`app_button`, `metric_card`, `family_circle_switcher`, `device_avatar`, etc.).
- Offline font: release builds should prefer bundled Inter assets; runtime `google_fonts` fetch can miss on first paint (documented in release checklist).

## Responsive breakpoints

Defined in `lib/app/core/theme/app_tokens.dart` (`AppBreakpoints`):

| Name | Width | Typical use |
|------|-------|-------------|
| Compact | `< 600` | Phone — single column |
| Medium | `600`–`< 1024` | Tablet — optional two-pane |
| Expanded | `≥ 1024` | Wide — two-pane + larger page margins |

`maxContentWidth = 1280`. Goldens cover phone (`412`) and tablet-ish (`800`) widths in light/dark.

## Directory Structure (actual)

```
spy_love/lib/
├── main.dart
├── firebase_options.dart
└── app/
    ├── app.dart                    # MaterialApp + onGenerateRoute
    ├── app_providers.dart          # MultiProvider wiring
    ├── core/
    │   ├── auth/
    │   ├── bootstrap/
    │   ├── config/                 # app_config.dart (API_BASE_URL, WS_BASE_URL)
    │   ├── constants/              # api_constants.dart (must match backend)
    │   ├── monitoring/             # monitoring_service, bridges, geofence, pause-aware upload
    │   ├── navigation/
    │   ├── network/
    │   ├── permissions/
    │   ├── storage/
    │   ├── theme/                  # Consent Horizon tokens + breakpoints
    │   └── widgets/                # responsive_scaffold, device_avatar, ...
    ├── routes/
    └── modules/
        ├── auth/
        ├── home/
        ├── dashboard/
        ├── device_detail/          # overview, activity, location/map, SIM, manage (keywords)
        ├── pairing/
        ├── subscription/
        └── audit/
```

## Data Flow

```
View → Controller (provider) → Repository → ApiService (one_request) → /api/v1/...
Monitored device: MonitoringService → collectors → POST /api/v1/events/batch/
Monitor: EventStreamClient (WebSocket) + EventRepository (GET /api/v1/events/)
```

## Pairing, consent, pause, zones (Implemented)

- Monitored device: `pair/initiate/` → code + QR `spylove://pair?code=&token=`.
- Monitor: scopes from `pairing/models/consent_scope.dart` → `pair/complete/`.
- **Geofence** client events use the same **`location`** consent as GPS updates.
- **Pause / resume** via `POST /devices/owned/{id}/pause|resume/` — client skips uploads while paused; consent scopes unchanged.
- **Safe zones** via `/devices/safe-zones/`; monitor Manage UI + monitored client for boundary events.
- **Keywords** via `/devices/keywords/` on Manage.
- **Device photo** optional `photo_url` on device model / PATCH; `DeviceAvatar` loads https URLs client-side.
- Revoke: disconnect / `DELETE /devices/{id}/consent/`.

Collectors: location (+ geofence), call log, SMS, notification messages, SIM, battery, network, app usage, device info (platform bridges).

## Planned / not implemented

- Deep-link handling for `spylove://pair?...` beyond QR scanning.
- Offline event queue with consent re-validation on sync.
- Separate web monitoring dashboard.
- Bundled Inter font assets as the default (checklist item).
