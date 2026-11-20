"""Staff authentication: Argon2id passwords, JWT access + rotating refresh cookie, TOTP MFA, lockout."""
from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import audit
from ..core.config import get_settings
from ..core.database import get_db
from ..core.deps import get_current_user
from ..core.rate_limit import enforce
from ..core.security import (
    as_utc,
    create_token,
    decode_token,
    hash_password,
    new_totp_secret,
    password_needs_rehash,
    totp_uri,
    utcnow,
    validate_password_strength,
    verify_password,
    verify_totp,
)
from ..models import User
from ..schemas import (
    LoginRequest,
    MfaConfirm,
    MfaEnrollResponse,
    MfaVerifyRequest,
    PasswordChange,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
REFRESH_COOKIE = "dt_refresh"
# Pre-computed dummy hash: equalizes timing for unknown e-mails (prevents user enumeration)
_DUMMY_HASH = hash_password("dummy-password-for-timing-equalization!")


def _set_refresh_cookie(response: Response, user: User) -> None:
    s = get_settings()
    token = create_token(
        str(user.id), "refresh", timedelta(hours=s.refresh_token_hours), {"ver": user.token_version}
    )
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=s.refresh_token_hours * 3600,
        httponly=True,
        secure=s.secure_cookies,
        samesite="strict",
        path="/api/v1/auth",
    )


def _issue(user: User, response: Response) -> TokenResponse:
    s = get_settings()
    access = create_token(
        str(user.id),
        "access",
        timedelta(minutes=s.access_token_minutes),
        {"ver": user.token_version, "role": user.role.value, "sid": str(user.school_id) if user.school_id else None},
    )
    _set_refresh_cookie(response, user)
    return TokenResponse(
        access_token=access, expires_in=s.access_token_minutes * 60, user=UserOut.model_validate(user)
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    s = get_settings()
    enforce(request, "auth", s.rate_limit_auth_per_minute)
    email = body.email.lower().strip()
    user = (await db.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none()
    now = utcnow()
    generic = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    if user is None:
        verify_password(body.password, _DUMMY_HASH)
        await audit(db, "LOGIN_FAILED", request=request, target=f"email:{email}", commit=True)
        raise generic
    if user.locked_until and as_utc(user.locked_until) > now:
        await audit(db, "LOGIN_LOCKED", request=request, actor_user_id=user.id, school_id=user.school_id, commit=True)
        raise HTTPException(status.HTTP_423_LOCKED, "Account temporarily locked after repeated failures")
    if not verify_password(body.password, user.password_hash) or not user.is_active:
        user.failed_login_count += 1
        if user.failed_login_count >= s.login_max_attempts:
            user.locked_until = now + timedelta(minutes=s.login_lockout_minutes)
            user.failed_login_count = 0
        await audit(db, "LOGIN_FAILED", request=request, actor_user_id=user.id, school_id=user.school_id)
        await db.commit()
        raise generic

    user.failed_login_count = 0
    user.locked_until = None
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    if user.mfa_enabled and user.mfa_secret:
        await db.commit()
        mfa_token = create_token(str(user.id), "mfa", timedelta(minutes=s.mfa_token_minutes), {"ver": user.token_version})
        return TokenResponse(mfa_required=True, mfa_token=mfa_token)

    user.last_login_at = now
    await audit(db, "LOGIN_SUCCESS", request=request, actor_user_id=user.id, school_id=user.school_id)
    await db.commit()
    return _issue(user, response)


@router.post("/mfa/verify", response_model=TokenResponse)
async def mfa_verify(body: MfaVerifyRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    enforce(request, "auth", get_settings().rate_limit_auth_per_minute)
    try:
        payload = decode_token(body.mfa_token, "mfa")
        user = await db.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA session expired; sign in again")
    if user is None or not user.is_active or payload.get("ver") != user.token_version or not user.mfa_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA session invalid")
    if not verify_totp(user.mfa_secret, body.code):
        await audit(db, "MFA_FAILED", request=request, actor_user_id=user.id, school_id=user.school_id, commit=True)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication code")
    user.last_login_at = utcnow()
    await audit(db, "LOGIN_SUCCESS", request=request, actor_user_id=user.id, school_id=user.school_id, details={"mfa": True})
    await db.commit()
    return _issue(user, response)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    dt_refresh: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    enforce(request, "auth-refresh", 60)
    if not dt_refresh:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No session")
    try:
        payload = decode_token(dt_refresh, "refresh")
        user = await db.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    if user is None or not user.is_active or payload.get("ver") != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked")
    return _issue(user, response)


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


@router.post("/logout-all", status_code=204)
async def logout_all(
    request: Request, response: Response, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    user.token_version += 1
    await audit(db, "LOGOUT_ALL_SESSIONS", request=request, actor_user_id=user.id, school_id=user.school_id)
    await db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password", status_code=204)
async def change_password(
    body: PasswordChange, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if err := validate_password_strength(body.new_password):
        raise HTTPException(422, err)
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # revoke all other sessions
    await audit(db, "PASSWORD_CHANGED", request=request, actor_user_id=user.id, school_id=user.school_id)
    await db.commit()


@router.post("/mfa/enroll", response_model=MfaEnrollResponse)
async def mfa_enroll(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.mfa_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "MFA already enabled")
    secret = new_totp_secret()
    user.mfa_secret = secret
    await db.commit()
    return MfaEnrollResponse(secret=secret, otpauth_uri=totp_uri(secret, user.email))


@router.post("/mfa/confirm", status_code=204)
async def mfa_confirm(
    body: MfaConfirm, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    if not user.mfa_secret or not verify_totp(user.mfa_secret, body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")
    user.mfa_enabled = True
    await audit(db, "MFA_ENABLED", request=request, actor_user_id=user.id, school_id=user.school_id)
    await db.commit()


@router.post("/mfa/disable", status_code=204)
async def mfa_disable(
    body: MfaConfirm, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    if not user.mfa_enabled or not user.mfa_secret or not verify_totp(user.mfa_secret, body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")
    user.mfa_enabled = False
    user.mfa_secret = None
    user.token_version += 1
    await audit(db, "MFA_DISABLED", request=request, actor_user_id=user.id, school_id=user.school_id)
    await db.commit()
