# Deploying the Master / Host on Windows 10 or 11 Pro

This guide covers a single Windows PC running the server, PostgreSQL or SQLite, and a Cloudflare Tunnel for `https://edu.detechtive.ca`. The same PC can run for a whole board, but read the **Scaling** notes at the end first.

## 1. Requirements
| Item | Why |
|---|---|
| Windows 10 (22H2) or Windows 11 **Pro** | BitLocker disk encryption for student data |
| Python **3.12**, *Install for all users* | The server runs as SYSTEM (a background service), which cannot use a per-user Python |
| Node.js **20 LTS** | Builds the staff portal once |
| Tesseract OCR (UB Mannheim installer) | Reads student cards. Tick "Additional language data" for French/Spanish |
| `cloudflared` (MSI from GitHub) | Publishes the server through the tunnel |
| Git | To clone the repository |
| PC set to never sleep, on UPS if possible | Kiosks and the locator must stay reachable |

Install the tools, then open **PowerShell as Administrator** for everything below.

## 2. Get the code
```powershell
cd C:\
git clone -b ccr-40a6b7fc-82qtaf https://github.com/Persaud-Airlines/Claude-Kiosk.git DeTechtive
cd C:\DeTechtive
```
Use `C:\DeTechtive` rather than a folder inside your user profile, so the service account can always read it.

## 3. Allow the scripts to run (once)
```powershell
Set-ExecutionPolicy -Scope LocalMachine RemoteSigned
```
The install script is also run with `-ExecutionPolicy Bypass`, so this step is optional for it.

## 4. Install
```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1 -PublicUrl https://edu.detechtive.ca
```
The script:
1. checks Python, Node.js, Tesseract and BitLocker, and warns about anything missing,
2. creates `backend\.venv` and installs the Python packages,
3. creates `backend\.env` with freshly generated secrets (`scripts\init_env.py`),
4. builds the staff portal (`frontend\dist`),
5. turns off sleep and hibernation on AC power,
6. registers two scheduled tasks that run as SYSTEM:
   * **DE-TECH-TIVE Server**: starts at boot, restarts within a minute if it stops, and has no time limit,
   * **DE-TECH-TIVE Backup**: every day at 02:15,
7. starts the server and checks `http://127.0.0.1:8000/api/health`,
8. asks for the **tunnel token** from the Cloudflare dashboard and installs the tunnel as a Windows service.

Paste the tunnel token when asked. It is not stored in the repository. It is passed to `cloudflared service install` and then forgotten.

### Choosing SQLite or PostgreSQL
* **SQLite (default)**: a single file in `backend\data\detechtive.db`. Fine for one school or a pilot.
* **PostgreSQL 16** (recommended for a board): install PostgreSQL with the EDB installer, create a database and user, then run the installer again with
  ```powershell
  powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1 -PublicUrl https://edu.detechtive.ca -PostgresUrl "postgresql+asyncpg://detechtive:PASSWORD@localhost:5432/detechtive"
  ```
  Add `pg_dump` (in PostgreSQL's `bin` folder) to PATH, or set the `PG_DUMP` variable, so backups work.

## 5. Check it works
1. Open `https://edu.detechtive.ca`. You should see the login page. (Before the tunnel is set up, use `http://127.0.0.1:8000` on the PC.)
2. Open `backend\data\INITIAL_ADMIN_PASSWORD.txt`, log in as the admin shown in it, change the password, enable MFA under **My account**, then **delete that file**.
3. Check `backend\logs\` for errors. Each start writes `server-<time>.log`; errors go to `server-<time>-error.log`.

## 6. Cloudflare Tunnel
In the Cloudflare Zero Trust dashboard, the published route should read:

| Hostname | Service |
|---|---|
| `edu.detechtive.ca` | `http://localhost:8000` |

If you set the tunnel up another way, run `cloudflared service install <TOKEN>` again. Kiosks and staff then reach the server through the tunnel, and **no inbound ports need to be opened** on the router or the Windows firewall.

## 7. Configure the school
1. **Platform Overview > Provision school** (SUPERSUDO): name, timezone, board, and principal login.
2. **Classrooms**: add rooms, or create them when pairing a kiosk.
3. **Students > Import CSV**: optional; unknown students are added automatically on their first scan.
4. **School Settings**: destinations, flag thresholds, and the kiosk admin PIN.
5. **Billing**: subscribe at $19.99/month (see section 9).

## 8. Kiosks
* Set the server address to `https://edu.detechtive.ca` on each kiosk: tap the gear icon on the Wi-Fi screen (or set `CONFIG_DT_DEFAULT_HOST_URL` before flashing).
* Pair each kiosk: **Kiosks > Pair a kiosk**, then enter the `XXXX-XXXX` code shown on its screen.

## 9. Stripe ($19.99 / month per school)
1. In Stripe, create a product with a **recurring $19.99 monthly** price. Put its `price_…` id in `backend\.env` as `STRIPE_PRICE_ID_SCHOOL_MONTHLY`, and set `STRIPE_SECRET_KEY`.
2. Add a webhook endpoint `https://edu.detechtive.ca/api/v1/billing/webhook` for `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `customer.subscription.updated`, and `customer.subscription.deleted`. Put its signing secret in `STRIPE_WEBHOOK_SECRET`.
3. Enable the Stripe **Customer Portal**.
4. Restart the server so it reloads `.env`: `Stop-ScheduledTask "DE-TECH-TIVE Server"`, then `Start-ScheduledTask "DE-TECH-TIVE Server"`.

A school whose payment is past due still gets sign-ins, the emergency locator and the roll-call. Only the portal shows a banner.

## 10. Security checklist
* **BitLocker on** for the system drive (Settings > Privacy & security > Device encryption). Pro edition has a full BitLocker option under Control Panel > BitLocker Drive Encryption.
* **Windows Update** set to install automatically, and the PC restarted at night (the server restarts itself after a reboot).
* **Use Windows 11 if your hardware supports it.** Windows 10 reached end of support in October 2025, so it no longer receives security fixes.
* Keep `backend\.env` and `backend\backups` private. The install script restricts them to SYSTEM, Administrators and your user account.
* Do not run the tunnel and the local server on a PC that other people use to browse the web.

## 11. Operations
| Task | How |
|---|---|
| Logs | `backend\logs\` |
| Backups | Nightly at 02:15 to `backend\backups\` (30 days kept). Run one now: `python scripts\backup.py` from `backend` with the venv active, or `Start-ScheduledTask "DE-TECH-TIVE Backup"` |
| Restore | Stop the server task, then copy a backup over `backend\data\detechtive.db` (gunzip the `.db.gz` first). Start the server task again. |
| Restart the server | `Stop-ScheduledTask "DE-TECH-TIVE Server"`, then `Start-ScheduledTask "DE-TECH-TIVE Server"` (both in an Administrator PowerShell) |
| Update to a new version | `git pull`, then run `install.ps1` again (it reuses `.env` and the data) |
| Remove the services | `powershell -ExecutionPolicy Bypass -File deploy\windows\uninstall.ps1` (keeps your data) |

Run `install.ps1` again after an update. It reinstalls the Python packages and rebuilds the portal, and it leaves your `.env` and data alone.

## 12. Developing on Windows (without the service)
```powershell
cd C:\DeTechtive\backend
.\run.ps1              # http://localhost:8000, auto-reloads, reachable on the LAN
.\run.ps1 -Production  # the production settings, bound to 127.0.0.1 for the tunnel
```

## Scaling
* The realtime feed and rate limiter run inside one server process, so keep **one** worker (the scheduled task does this).
* A single PC handles many schools. OCR runs two scans at a time by default. For a whole board, use a separate PC for the server and the database, and see `docs/SECURITY.md` ("Scaling out").
