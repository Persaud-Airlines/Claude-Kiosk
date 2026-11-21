# Security & Student-Data Protection

> **Note on scope:** the original specification was cut off at Section 4 ("1. **Auth…"). The controls below are the defence-in-depth baseline implemented in its place. Review them against your board's privacy obligations (e.g. MFIPPA / PIPEDA in Ontario, FERPA / COPPA in the US) and tell us about anything else Section 4 required.

## Identity & access
| Control | Implementation |
|---|---|
| Passwords | **Argon2id** (m=64 MiB, t=3, p=4); hashes upgrade automatically on login. Minimum 12 characters using 3 character classes. |
| Brute force | 5 failures lock the account for 15 min (HTTP 423). Login is rate-limited per IP. Timing is equalised for unknown e-mails, so they can't be enumerated. |
| Sessions | 30-min **JWT access token kept in memory only** (never in localStorage). 12-h refresh token in an `HttpOnly; SameSite=Strict; Path=/api/v1/auth` cookie (`Secure` in production). `token_version` revokes every session on password change, MFA change, role change, deactivation or "log out everywhere". |
| MFA | Optional **TOTP** (RFC 6238) per user. Enrolling shows a QR code; the secret is Fernet-encrypted at rest. |
| RBAC | `SUPERSUDO` › `PRINCIPAL` › `SCHOOL_ADMIN` › `TEACHER`. Each role can only create or modify roles below it (principals can add principals). |
| Tenant isolation | Every school-scoped query goes through `resolve_school_id` / `ensure_same_school`. Cross-tenant IDs return **404**, so other schools' resources are not revealed to exist. Covered by `test_tenant_isolation`. |

## Kiosks
* **Pairing:** an 8-character code from an unambiguous alphabet, valid for 15 minutes, collision-checked. The kiosk also receives a random **pairing secret** and must present it while polling, so knowing a device UID is not enough to steal a token. The token is delivered **exactly once**.
* **Device tokens:** 320-bit random values. Only the **SHA-256 digest** is stored. Admins can revoke a token instantly, and the kiosk then returns to pairing.
* Each request is rate-limited per device. `X-Device-UID` must match the token's device.
* Card images are at most 2.5 MB, must be JPEG/PNG (checked by magic bytes, not just headers) and 160–4096 px. They are processed **in memory and never stored**. Only the OCR result is kept (24 h `card_scan_sessions` rows, linked to events).
* Client timestamps are trusted only within ±5 min online, or up to 72 h old for offline replays. Future timestamps are clamped to server time.
* Firmware secure profile: **flash encryption, Secure Boot v2 and encrypted NVS**, so the device token, Wi-Fi password and offline queue are encrypted at rest; serial console disabled. The kiosk admin PIN is verified **server-side**, with Argon2 hashing and a limit of 5 tries/min.
* TLS: Mozilla CA bundle by default (e.g. Cloudflare Tunnel), or a pinned private CA via `certs/host_ca.pem`.

## Data protection
* **Health / IEP information:** exemption `reason_notes` and MFA secrets are **Fernet-encrypted columns** (`FIELD_ENCRYPTION_KEY`). Exemption category and notes are returned only to admin roles. Teachers see "Approved Accommodation on File". Every admin read is audited (`VIEW_STUDENT_EXEMPTION`).
* **Audit log** (`security_audit_logs`): logins (success, failure, lockout), MFA, pairing and revocation, lockdown start/end, every locator search (`LOCKDOWN_SEARCH`, which logs the query length, not the name), roster imports, staff-entered events, user/role changes, settings changes, Stripe status changes, kiosk PIN attempts. There is no API to edit or delete entries.
* `hall_pass_events` is **append-only** through the API: no update/delete endpoints.
* **Retention:** events and flags are purged after `DATA_RETENTION_DAYS` (default 400); scan sessions after 24 h.
* **Data minimisation:** no student photos, no images on disk (`OCR_DEBUG_DIR` is refused in production), no PII in URLs (WebSocket auth uses the first message, not a query string).

## Windows host
* Student data is protected at rest by **BitLocker** (Windows 10/11 Pro). `install.ps1` checks it and warns if it is off.
* Secret files (`backend\.env`, `backend\data\INITIAL_ADMIN_PASSWORD.txt`, `backend\backups`) are restricted with `icacls` to SYSTEM, Administrators and the installing user. This replaces the POSIX `chmod 600` used on macOS/Linux.
* The server runs as **NT AUTHORITY\SYSTEM** from a scheduled task, bound to `127.0.0.1` and reachable only through the Cloudflare Tunnel. No inbound firewall ports are opened.

## Transport & browser hardening
`Strict-Transport-Security` (production), CSP (`default-src 'self'`, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, `Cache-Control: no-store` on all API responses, a strict CORS allow-list, and OpenAPI docs disabled in production. The server **refuses to start in production** with default secrets, insecure cookies or OCR debug mode.

## Safety-first availability
Billing status is never checked on kiosk endpoints, the locator or the roll-call (`test_stripe_webhook_updates_status_without_blocking_kiosks`). Kiosks keep working offline and replay events later. Any staff member can **start** a lockdown roll-call; only admins can **end** one.

## Scaling out / known limits
* The rate limiter and realtime hub are **in-process**, so run one uvicorn worker (the scheduled task does). To run several workers or hosts, back `SlidingWindowLimiter` and `RealtimeHub` with Redis (same interfaces) and move the flag-engine loop to a single scheduler.
* Manual name entry on kiosks (the fallback when the camera or host is down) is inherently spoofable. Such events are tagged `MANUAL` in every view so staff can tell them apart.
* OCR can misread a name. That is why the student must **confirm** it on the kiosk, roster matching corrects near-misses, and a student number only matches when the printed name also agrees (`test_student_number_requires_matching_name`).

## Reporting
Send vulnerabilities privately to the platform operator. Do not open public issues containing student data.
