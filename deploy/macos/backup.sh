#!/usr/bin/env bash
# Nightly backup (add to crontab: 15 2 * * * /path/to/deploy/macos/backup.sh)
# Backups contain student PII: keep BACKUP_DIR on an encrypted volume (FileVault) and restrict access.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT/backend/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
cd "$ROOT/backend"
if grep -q '^USE_SQLITE=true' .env; then
  DB=$(grep '^SQLITE_PATH=' .env | cut -d= -f2-); DB=${DB:-./data/detechtive.db}
  sqlite3 "$DB" ".backup '$BACKUP_DIR/detechtive-$STAMP.db'"
  gzip "$BACKUP_DIR/detechtive-$STAMP.db"
else
  pg_dump -Fc detechtive > "$BACKUP_DIR/detechtive-$STAMP.dump"
fi
chmod 600 "$BACKUP_DIR"/*
find "$BACKUP_DIR" -type f -mtime +"$KEEP_DAYS" -delete
echo "backup written to $BACKUP_DIR"
