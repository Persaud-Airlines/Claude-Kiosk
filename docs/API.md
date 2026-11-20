# API reference (summary)

Interactive OpenAPI docs: `http://<host>:8000/api/docs` (disabled when `ENVIRONMENT=production`).

## Kiosk (device token: `X-Device-Token`, `X-Device-UID`)
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/kiosk/pair/init` | *(no auth)* `{device_uid, firmware_version}` → `{pairing_code "XXXX-XXXX", pairing_secret, pairing_url, expires_in_seconds}` |
| GET | `/api/v1/kiosk/pair/status/{device_uid}` | header `X-Pairing-Secret` → `pending` · `expired` · `revoked` · `paired` (+ one-time `device_api_token`, `school_name`, `room_number`, `timezone`, `posix_tz`, `destinations`) |
| GET/POST | `/api/v1/kiosk/config`, `/api/v1/kiosk/heartbeat` | Room/school/timezone/destinations/lockdown; the heartbeat also reports IP, RSSI and queue depth |
| POST | `/api/v1/kiosk/scan-card` | Raw `image/jpeg` body (or multipart `image`) → `{detected, first_name, last_name, confidence, scan_session_id, roster_match}` |
| POST | `/api/v1/kiosk/events` | `{event_type, destination?, first_name, last_name, scan_session_id?, client_timestamp_utc, client_event_id, entry_method, was_offline_queued}` |
| POST | `/api/v1/kiosk/events/batch` | `{events:[…]}`. Replayed chronologically; results come back in request order; idempotent on `client_event_id` |
| POST | `/api/v1/kiosk/verify-pin`, `/api/v1/kiosk/unpair` | Diagnostics PIN gate; factory-reset notification |

## Staff portal (Bearer JWT)
| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `/auth/mfa/verify`, `/auth/refresh`, `/auth/logout`, `/auth/logout-all`, `/auth/change-password`, `/auth/mfa/{enroll,confirm,disable}`, `GET /auth/me` |
| Schools | `GET /schools/current`, `PATCH /schools/{id}`, `POST /schools/{id}/lockdown?active=`, `GET /schools/{id}/dashboard`, `GET/POST /schools/{id}/classrooms`, `PATCH/DELETE /schools/classrooms/{id}`, `GET /schools/timezones` |
| Live feed | `GET /classrooms/{id}/events`, `GET /schools/{id}/events`, `GET /schools/{id}/out-now`, `POST /events/staff`, WebSocket `/api/v1/ws/schools/{id}` (send `{"token": "<access>"}` first) |
| Emergency | `GET /schools/{id}/locate?q=`, `GET /students/{id}/locate`, `GET /schools/{id}/roll-call` |
| Students | `GET/POST /students`, `PATCH /students/{id}`, `POST /students/import` (CSV) |
| Accommodations / flags | `GET /students/{id}/exemptions`, `POST /exemptions`, `PATCH /exemptions/{id}`, `GET /flags`, `PATCH /flags/{id}` |
| Kiosks | `POST /kiosks/claim`, `GET /kiosks`, `PATCH /kiosks/{id}`, `POST /kiosks/{id}/revoke` |
| Staff / audit | `GET/POST /users`, `PATCH /users/{id}`, `GET /audit-logs` |
| Billing | `POST /billing/create-checkout-session`, `POST /billing/create-portal-session`, `GET /billing/status`, `POST /billing/webhook` (Stripe-Signature) |
| SUPERSUDO | `GET /admin/overview` (MRR, kiosks, volume), `GET/POST /admin/schools`, `GET /admin/boards` |

All paths above are prefixed with `/api/v1` where not shown.
