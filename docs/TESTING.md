# Testing

| Layer | Command | Covers |
|---|---|---|
| Backend (SQLite) | `cd backend && pytest` | 33 tests: pairing handshake and secret, OCR on synthetic cards (real OpenCV + Tesseract), sign-out/in, scan-session reuse, cross-room lockdown detection, locator + roll-call, offline batch replay (order, timestamps, idempotency), clock clamping, revocation, kiosk PIN, destinations, flag engine (frequency, duration, exemption suppression and re-opening), encryption at rest, tenant isolation, RBAC, lockout, MFA, refresh/logout-all, CSV import, security headers, Stripe webhooks (signature, idempotency, status transitions, grace policy), name/QR parsing |
| Backend (PostgreSQL) | `TEST_DATABASE_URL=postgresql+asyncpg://… pytest` | The same suite on PostgreSQL 16 |
| Migrations | `alembic upgrade head` (CI: PostgreSQL service) | Schema builds from scratch |
| Portal | `cd frontend && npm run build` | Strict TypeScript (`noUnusedLocals`, `strict`) + production bundle |
| Kiosk UI | `firmware/sim` | Real UI code + LVGL renders all 16 states to PNG/PPM |
| Firmware | `pio run -e kiosk` / `-e kiosk-mock-camera` (CI) | Full ESP-IDF build of every component |

## OCR bench test
```bash
cd backend
python scripts/make_test_card.py --first Émilie --last "O'Brien" --layout labels -o /tmp/card.jpg
python -c "from app.services.ocr import analyze_card_image as a; print(a(open('/tmp/card.jpg','rb').read()))"
```
Photograph a few of the school's real cards in the enclosure and run them the same way before go-live. If confidence is low, raise lighting diffusion, or set `OCR_ENGINE=easyocr`/`paddle`.

## End-to-end bench test (no webcam)
1. Start the backend and `python scripts/seed_demo.py`.
2. Flash `pio run -e kiosk-mock-camera -t upload`, complete the wizard and pair the kiosk to Room 204 in the portal.
3. Tap **SIGN OUT → Washroom**. The mock card ("Jordan Taylor") is uploaded, then **CONFIRM** takes you to **Signed out successfully**. The portal dashboard updates live.
4. Turn off the access point and do **SIGN IN** → "Card reader offline — type your name". Enter the name, **CONFIRM**, and you should see "Saved on this kiosk". The status dot turns red/amber.
5. Restore Wi-Fi. Within about 10 s the queued event appears in the portal with an *offline* badge and its original time.
6. In the portal, **Emergency Locator → Start lockdown**. The kiosk top bar turns red within one heartbeat (≤ 30 s). Sign the student in on a second kiosk and search their name: the current room shows the **cross-room** badge.
