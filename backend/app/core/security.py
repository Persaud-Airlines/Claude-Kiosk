"""Cryptographic primitives: Argon2id passwords, JWTs, device tokens, field encryption, TOTP."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

# OWASP-recommended Argon2id parameters (m=64 MiB, t=3, p=4)
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)

# Unambiguous alphabet for human-typed pairing codes (no 0/O, 1/I/L)
PAIRING_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; normalise any datetime read from the DB to aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def validate_password_strength(password: str) -> str | None:
    if len(password) < 12:
        return "Password must be at least 12 characters"
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        return "Password must contain at least 3 of: lowercase, uppercase, digit, symbol"
    return None


# ---------------------------------------------------------------------------------------- JWT
def create_token(subject: str, token_type: str, expires: timedelta, extra: dict[str, Any] | None = None) -> str:
    s = get_settings()
    now = utcnow()
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub", "typ"]})
    if payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


# ------------------------------------------------------------------------------ device tokens
def generate_device_token() -> str:
    """Long-lived kiosk API token. Only its SHA-256 digest is stored server side."""
    return "dtk_" + secrets.token_urlsafe(40)


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def generate_pairing_code() -> str:
    raw = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_pairing_code(code: str) -> str:
    cleaned = "".join(ch for ch in code.upper() if ch.isalnum())
    if len(cleaned) != 8:
        return ""
    return f"{cleaned[:4]}-{cleaned[4:]}"


# --------------------------------------------------------------------------- field encryption
def _fernet() -> Fernet:
    key = get_settings().field_encryption_key
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        # Derive a valid Fernet key from arbitrary secret material
        digest = hashlib.sha256(key.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_str(value: str | None) -> str | None:
    if value is None:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_str(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return "[unreadable: encryption key mismatch]"


# --------------------------------------------------------------------------------------- TOTP
def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="DE-TECH-TIVE")


def verify_totp(secret: str, code: str) -> bool:
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)
