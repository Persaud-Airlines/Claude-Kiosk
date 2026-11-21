#!/usr/bin/env python3
"""Create backend/.env from .env.example with freshly generated secrets.

Works the same on macOS, Linux and Windows. Refuses to overwrite an existing .env unless --force.

  python scripts/init_env.py                          # development defaults
  python scripts/init_env.py --production --public-url https://edu.detechtive.ca
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core.fsutil import restrict_to_owner  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--production", action="store_true", help="secure settings for a live server")
    ap.add_argument("--public-url", help="public HTTPS address, e.g. https://edu.detechtive.ca")
    ap.add_argument("--postgres-url", help="postgresql+asyncpg://user:pass@host:5432/db")
    ap.add_argument("--force", action="store_true", help="overwrite an existing .env (rotates secrets!)")
    args = ap.parse_args()

    env_path = BACKEND / ".env"
    if env_path.exists() and not args.force:
        print(f".env already exists at {env_path}; leaving it unchanged")
        return 0

    values = {
        "JWT_SECRET": secrets.token_urlsafe(48),
        "FIELD_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
    }
    if args.production:
        values.update({"ENVIRONMENT": "production", "SECURE_COOKIES": "true", "TRUST_PROXY_HEADERS": "true"})
    if args.public_url:
        url = args.public_url.rstrip("/")
        values.update({"PUBLIC_BASE_URL": url, "FRONTEND_BASE_URL": url, "CORS_ORIGINS": url})
    if args.postgres_url:
        values.update({"USE_SQLITE": "false", "DATABASE_URL": args.postgres_url})

    template = (BACKEND / ".env.example").read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    written: set[str] = set()
    for line in template:
        key = None
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
        if key in values:
            out.append(f"{key}={values[key]}")
            written.add(key)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in values.items() if k not in written]

    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    restrict_to_owner(env_path)
    print(f"wrote {env_path} (secrets generated; keep this file private)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
