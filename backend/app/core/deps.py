"""FastAPI dependencies: authenticated staff users, RBAC, tenant scoping, kiosk devices."""
from __future__ import annotations

import uuid
from collections.abc import Iterable

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import KioskDevice, PairingStatus, Role, School, User
from .config import get_settings
from .database import get_db
from .rate_limit import enforce
from .security import decode_token, hash_device_token, utcnow

bearer = HTTPBearer(auto_error=False)

ADMIN_ROLES = {Role.SUPERSUDO, Role.PRINCIPAL, Role.SCHOOL_ADMIN}
STAFF_ROLES = ADMIN_ROLES | {Role.TEACHER}


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return await user_from_access_token(creds.credentials, db)


async def user_from_access_token(token: str, db: AsyncSession) -> User:
    try:
        payload = decode_token(token, "access")
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = await db.get(User, user_id)
    if user is None or not user.is_active or payload.get("ver") != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked")
    return user


def require_roles(*roles: Role):
    allowed = set(roles)

    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return _dep


require_staff = require_roles(*STAFF_ROLES)
require_admin = require_roles(*ADMIN_ROLES)
require_supersudo = require_roles(Role.SUPERSUDO)


def is_admin(user: User) -> bool:
    return user.role in ADMIN_ROLES


def resolve_school_id(user: User, requested: uuid.UUID | None) -> uuid.UUID:
    """Tenant isolation: non-supersudo users are hard-pinned to their own school."""
    if user.role == Role.SUPERSUDO:
        if requested is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "school_id is required for SUPERSUDO requests")
        return requested
    if user.school_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is not assigned to a school")
    if requested is not None and requested != user.school_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-school access denied")
    return user.school_id


def ensure_same_school(user: User, school_id: uuid.UUID | None) -> None:
    if user.role == Role.SUPERSUDO:
        return
    if school_id is None or school_id != user.school_id:
        # 404 rather than 403 avoids leaking existence of other tenants' resources
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


async def get_school_or_404(db: AsyncSession, school_id: uuid.UUID) -> School:
    school = await db.get(School, school_id)
    if school is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    return school


async def get_paired_device(
    request: Request,
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
    x_device_uid: str | None = Header(default=None, alias="X-Device-UID"),
    db: AsyncSession = Depends(get_db),
) -> KioskDevice:
    if not x_device_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing device token")
    enforce(request, "kiosk", get_settings().rate_limit_kiosk_per_minute, key_suffix=x_device_token[-16:])
    token_hash = hash_device_token(x_device_token)
    device = (
        await db.execute(select(KioskDevice).where(KioskDevice.api_token_hash == token_hash))
    ).scalar_one_or_none()
    if device is None or device.pairing_status != PairingStatus.paired or device.classroom_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Device not paired or token revoked")
    if x_device_uid and x_device_uid != device.device_uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Device identity mismatch")
    device.last_seen_at = utcnow()
    return device


def only_fields(obj: dict, fields: Iterable[str]) -> dict:
    return {k: obj[k] for k in fields if k in obj}
