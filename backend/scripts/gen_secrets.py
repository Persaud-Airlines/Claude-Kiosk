#!/usr/bin/env python3
"""Print fresh production secrets for backend/.env."""
import secrets

from cryptography.fernet import Fernet

print(f"JWT_SECRET={secrets.token_urlsafe(48)}")
print(f"FIELD_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
