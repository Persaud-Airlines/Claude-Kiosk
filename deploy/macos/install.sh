#!/usr/bin/env bash
# DE-TECH-TIVE Master/Host installer for macOS (Apple Silicon or Intel Mac Mini).
#   ./deploy/macos/install.sh            # SQLite (single school, 60-second setup)
#   ./deploy/macos/install.sh --postgres # PostgreSQL 16 via Homebrew (recommended for boards)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PG=0; [ "${1:-}" = "--postgres" ] && PG=1

command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
brew install python@3.12 node@20 tesseract
[ $PG = 1 ] && brew install postgresql@16 && brew services start postgresql@16

cd "$ROOT/backend"
python3.12 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
if [ ! -f .env ]; then
  cp .env.example .env
  ./.venv/bin/python scripts/gen_secrets.py >> .env   # later lines override the dev defaults
  sed -i '' 's/^ENVIRONMENT=development.*/ENVIRONMENT=production/' .env
  sed -i '' 's/^SECURE_COOKIES=false.*/SECURE_COOKIES=true/' .env
  echo "Created backend/.env with fresh secrets — review PUBLIC_BASE_URL / FRONTEND_BASE_URL / Stripe keys."
fi
if [ $PG = 1 ]; then
  createuser -s detechtive 2>/dev/null || true
  createdb -O detechtive detechtive 2>/dev/null || true
  sed -i '' 's/^USE_SQLITE=true/USE_SQLITE=false/' .env
fi
mkdir -p data logs

cd "$ROOT/frontend"
npm ci && npm run build

PLIST="$HOME/Library/LaunchAgents/com.detechtive.server.plist"
sed "s#__ROOT__#$ROOT#g" "$ROOT/deploy/macos/com.detechtive.server.plist" > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"
sleep 3
curl -fsS http://127.0.0.1:8000/api/health && echo
echo "Portal: http://$(ipconfig getifaddr en0 2>/dev/null || echo localhost):8000"
[ -f "$ROOT/backend/data/INITIAL_ADMIN_PASSWORD.txt" ] && echo "First SUPERSUDO login: $ROOT/backend/data/INITIAL_ADMIN_PASSWORD.txt"
