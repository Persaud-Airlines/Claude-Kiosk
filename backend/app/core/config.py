"""Application configuration loaded from environment / .env file."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


# Resolved once, so the server behaves the same no matter which folder it is started from
# (Windows services and scheduled tasks usually start in C:\Windows\System32).
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # --- General -------------------------------------------------------------------
    app_name: str = "DE-TECH-TIVE TECHNOLOGIES Inc"
    environment: Literal["development", "production", "test"] = "development"
    public_base_url: str = "http://localhost:8000"  # used in pairing QR codes
    frontend_base_url: str = "http://localhost:5173"
    # Plain text on purpose: pydantic-settings would otherwise require JSON for list values from .env.
    # Use a comma-separated list, e.g. CORS_ORIGINS=https://edu.detechtive.ca,http://localhost:5173
    cors_origins: str = "http://localhost:5173"
    serve_frontend_dist: str | None = "../frontend/dist"  # serve built SPA if it exists

    # --- Database --------------------------------------------------------------------
    # Set USE_SQLITE=true for the 60-second Mac Mini quickstart.
    use_sqlite: bool = True
    sqlite_path: str = "data/detechtive.db"  # relative paths are resolved against the backend folder
    database_url: str = "postgresql+asyncpg://detechtive:detechtive@localhost:5432/detechtive"

    # --- Security ----------------------------------------------------------------------
    jwt_secret: str = "CHANGE-ME-dev-only-jwt-secret-please-rotate-0123456789"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_hours: int = 12
    mfa_token_minutes: int = 5
    # Fernet key (urlsafe base64, 32 bytes) used to encrypt sensitive columns (exemption notes, MFA secrets)
    field_encryption_key: str = "pV0eY2m3eYp0Zr6h0bq7lJm0Wq4p8i7rN1hS5aT9cXk="
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15
    rate_limit_kiosk_per_minute: int = 240
    rate_limit_auth_per_minute: int = 20
    trust_proxy_headers: bool = False  # set true behind Cloudflare Tunnel / nginx
    secure_cookies: bool = False  # true in production (HTTPS)

    # --- Kiosk pairing -----------------------------------------------------------------
    pairing_code_ttl_minutes: int = 15
    scan_session_ttl_hours: int = 24
    kiosk_online_window_seconds: int = 120
    max_upload_bytes: int = 2_500_000

    # --- OCR -----------------------------------------------------------------------------
    ocr_engine: Literal["auto", "paddle", "easyocr", "tesseract", "none"] = "auto"
    ocr_min_confidence: float = 0.60
    ocr_debug_dir: str | None = None  # never enable in production: stores card images
    # Full path to tesseract.exe / tesseract. Blank = auto-detect (PATH, then the default Windows install folder).
    tesseract_cmd: str | None = None

    # --- Flagging engine -------------------------------------------------------------
    flag_scan_interval_seconds: int = 60
    data_retention_days: int = 400

    # --- Stripe ------------------------------------------------------------------------
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_id_school_monthly: str | None = None
    school_monthly_price_cents: int = 1999

    # --- Bootstrap supersudo (created on first start if no users exist) ------------
    bootstrap_supersudo_email: str | None = "admin@detechtive.local"
    bootstrap_supersudo_password: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlite_file(self) -> Path:
        p = Path(self.sqlite_path)
        return p if p.is_absolute() else BACKEND_DIR / p

    @property
    def effective_database_url(self) -> str:
        if self.use_sqlite:
            # as_posix() keeps Windows drive letters valid inside the URL (sqlite+aiosqlite:///C:/...)
            return f"sqlite+aiosqlite:///{self.sqlite_file.as_posix()}"
        return self.database_url

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_production_settings(s: Settings) -> list[str]:
    """Return a list of fatal misconfigurations for production deployments."""
    problems: list[str] = []
    if not s.is_production:
        return problems
    if "CHANGE-ME" in s.jwt_secret or len(s.jwt_secret) < 32:
        problems.append("JWT_SECRET must be a random value of at least 32 characters")
    if s.field_encryption_key == Settings.model_fields["field_encryption_key"].default:
        problems.append("FIELD_ENCRYPTION_KEY must be rotated from the development default")
    if not s.secure_cookies:
        problems.append("SECURE_COOKIES must be true in production")
    if s.ocr_debug_dir:
        problems.append("OCR_DEBUG_DIR must be unset in production (student images would be stored)")
    return problems
