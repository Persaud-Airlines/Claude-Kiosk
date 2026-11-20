#!/usr/bin/env bash
# One-command start for the Mac Mini host (SQLite by default). Usage: ./run.sh [--prod]
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip >/dev/null
  ./.venv/bin/pip install -r requirements.txt
fi
[ -f .env ] || { cp .env.example .env; echo "Created backend/.env from .env.example"; }
mkdir -p data
WORKERS=1  # in-process realtime hub + rate limiter: keep 1 worker (see docs/SECURITY.md for scaling)
if [ "${1:-}" = "--prod" ]; then
  exec ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers $WORKERS --proxy-headers --forwarded-allow-ips="127.0.0.1"
fi
exec ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
