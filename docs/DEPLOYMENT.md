# Deploying the Master / Host (Mac Mini)

## 1. Requirements
* Mac Mini (Apple Silicon or Intel) with macOS 13+, FileVault **on** (the database holds student PII).
* Homebrew, Python 3.11+, Node 20, Tesseract (`brew install tesseract`). For French/Spanish card text, also run `brew install tesseract-lang` and set `TESSERACT_LANG=eng+fra+spa`.
* Optional, for higher OCR accuracy: `pip install -r requirements-ocr-extra.txt` (EasyOCR, or PaddleOCR). `OCR_ENGINE=auto` picks the best engine that is installed.

## 2. One-command install
```bash
git clone <this repo> ~/detechtive && cd ~/detechtive
./deploy/macos/install.sh              # SQLite: one school, zero database admin
./deploy/macos/install.sh --postgres   # PostgreSQL 16 (recommended for a board / many schools)
```
The installer:
1. creates `backend/.venv`,
2. writes `backend/.env` with fresh `JWT_SECRET` / `FIELD_ENCRYPTION_KEY`,
3. builds the portal,
4. installs a **launchd agent** (`~/Library/LaunchAgents/com.detechtive.server.plist`) that starts the server at login and restarts it if it crashes.

Migrations run automatically on every start. The first SUPERSUDO account is created from `BOOTSTRAP_SUPERSUDO_EMAIL`. If `BOOTSTRAP_SUPERSUDO_PASSWORD` is blank, a random password is written to `backend/data/INITIAL_ADMIN_PASSWORD.txt` (mode 600). Delete that file after you first log in, then enable MFA under **My account**.

Manual alternative: `cd backend && ./run.sh --prod`.

### SQLite ⇄ PostgreSQL
One flag switches databases: `USE_SQLITE=true|false` plus `DATABASE_URL=postgresql+asyncpg://…`. The same Alembic migrations run on both, and CI checks both.

## 3. HTTPS
`ENVIRONMENT=production` refuses to start unless `SECURE_COOKIES=true` and both secrets have been rotated. Secure cookies only work over HTTPS, so pick one of these:

**A. Cloudflare Tunnel (recommended; required for multi-school boards).** No inbound ports are opened, and kiosks validate the public certificate with the CA bundle built into the firmware. Follow `deploy/cloudflared/config.yml.example`, then set:
```
PUBLIC_BASE_URL=https://kiosk.your-board.org
FRONTEND_BASE_URL=https://kiosk.your-board.org
CORS_ORIGINS=https://kiosk.your-board.org
TRUST_PROXY_HEADERS=true
```

**B. LAN-only with your own certificate.** Put Caddy or nginx with the school's internal CA in front of `127.0.0.1:8000`. Paste that CA's PEM into `firmware/main/certs/host_ca.pem` before you flash, so kiosks trust it.

Plain `http://` on a LAN works for evaluation only: use `ENVIRONMENT=development`. Kiosks accept an `http://` host URL. Never use plain HTTP with real student data.

## 4. Stripe ($19.99 / month per school)
1. In Stripe, create a product "DE-TECH-TIVE School Subscription" with a **recurring $19.99/month** price. Copy its `price_…` id into `STRIPE_PRICE_ID_SCHOOL_MONTHLY`. If you leave it blank, an inline $19.99 price is used.
2. Set `STRIPE_SECRET_KEY` (`sk_live_…` or `sk_test_…`).
3. Add a webhook endpoint `https://<host>/api/v1/billing/webhook` with these events: `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `customer.subscription.updated`, `customer.subscription.deleted`. Put its signing secret in `STRIPE_WEBHOOK_SECRET`.
4. Enable the **Customer Portal** in Stripe settings (cards, invoices, cancellation).
5. To test locally: `stripe listen --forward-to localhost:8000/api/v1/billing/webhook`.

Principals and board admins subscribe from **Billing** in the portal. SUPERSUDO sees MRR and subscription status for every school on **Platform Overview**. A `past_due` or `canceled` school gets a banner, but **kiosks, the locator and roll-call keep working**.

## 5. Onboarding a school
1. SUPERSUDO → **Platform Overview → Provision school**: name, timezone, board, and the principal's account.
2. Principal → **Classrooms**: add rooms, or create them while pairing.
3. Principal → **Students → Import CSV**. Optional: unknown students are auto-registered on their first scan.
4. Principal → **School Settings**: destinations (up to 6), flag thresholds, kiosk admin PIN.
5. Power on each kiosk. On the pairing step, enter its `XXXX-XXXX` code in **Kiosks → Pair a kiosk**, or scan its QR code with a phone that is logged into the portal.

## 6. Operations
* **Backups:** `deploy/macos/backup.sh` (cron at 02:15 is suggested). Keep `BACKUP_DIR` on an encrypted volume.
* **Logs:** `backend/logs/server*.log`. Security-relevant actions are in the **Audit Log** page / `security_audit_logs` table.
* **Retention:** events and flags older than `DATA_RETENTION_DAYS` (default 400) are purged automatically. OCR images are never stored.
* **Upgrades:** `git pull && (cd frontend && npm ci && npm run build) && launchctl kickstart -k gui/$UID/com.detechtive.server`. Migrations apply on start.
* **Scaling:** the realtime hub and rate limiter are in-process, so run **one** uvicorn worker. One Mac Mini handles dozens of schools; OCR is limited to 2 concurrent scans by default. For larger boards, see `docs/SECURITY.md` → "Scaling out".
