"""Staff account management and audit log access."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import audit
from ..core.database import get_db
from ..core.deps import ensure_same_school, require_admin, resolve_school_id
from ..core.security import hash_password, validate_password_strength
from ..models import Role, SecurityAuditLog, User
from ..schemas import AuditOut, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/api/v1", tags=["users"])

# Which roles each role may create / manage
MANAGEABLE = {
    Role.SUPERSUDO: {Role.SUPERSUDO, Role.PRINCIPAL, Role.SCHOOL_ADMIN, Role.TEACHER},
    Role.PRINCIPAL: {Role.SCHOOL_ADMIN, Role.TEACHER, Role.PRINCIPAL},
    Role.SCHOOL_ADMIN: {Role.TEACHER},
}


def _can_manage(actor: User, role: Role) -> bool:
    return role in MANAGEABLE.get(actor.role, set())


@router.get("/users", response_model=list[UserOut])
async def list_users(
    school_id: uuid.UUID | None = None, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    if user.role == Role.SUPERSUDO and school_id is None:
        rows = (await db.execute(select(User).order_by(User.role, User.full_name))).scalars().all()
        return rows
    sid = resolve_school_id(user, school_id)
    return (await db.execute(select(User).where(User.school_id == sid).order_by(User.role, User.full_name))).scalars().all()


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, request: Request, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if not _can_manage(user, body.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{user.role.value} cannot create {body.role.value} accounts")
    if body.role == Role.SUPERSUDO:
        school_id = None
    else:
        school_id = resolve_school_id(user, body.school_id)
    if err := validate_password_strength(body.password):
        raise HTTPException(422, err)
    email = body.email.lower().strip()
    if (await db.execute(select(User.id).where(func.lower(User.email) == email))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use")
    new = User(email=email, full_name=body.full_name.strip(), role=body.role, school_id=school_id,
               password_hash=hash_password(body.password))
    db.add(new)
    await db.flush()
    await audit(db, "CREATE_USER", request=request, actor_user_id=user.id, school_id=school_id,
                target=f"user:{new.id}", details={"role": body.role.value})
    await db.commit()
    return new


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, request: Request, user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if target.role == Role.SUPERSUDO and user.role != Role.SUPERSUDO:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if target.role != Role.SUPERSUDO:
        ensure_same_school(user, target.school_id)
    if not _can_manage(user, target.role) and target.id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
    data = body.model_dump(exclude_unset=True)
    if "role" in data and data["role"] is not None and not _can_manage(user, data["role"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot assign that role")
    if target.id == user.id and (data.get("is_active") is False or ("role" in data and data["role"] != user.role)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate or demote yourself")
    if pw := data.pop("password", None):
        if err := validate_password_strength(pw):
            raise HTTPException(422, err)
        target.password_hash = hash_password(pw)
        target.token_version += 1
    if data.get("is_active") is False or "role" in data:
        target.token_version += 1  # revoke live sessions on privilege change
    for k, v in data.items():
        if v is not None:
            setattr(target, k, v)
    await audit(db, "UPDATE_USER", request=request, actor_user_id=user.id, school_id=target.school_id,
                target=f"user:{target.id}", details={"fields": sorted(list(data) + (["password"] if pw else []))})
    await db.commit()
    return target


@router.get("/audit-logs", response_model=list[AuditOut])
async def audit_logs(
    school_id: uuid.UUID | None = None,
    action: str | None = Query(default=None, max_length=64),
    since: datetime | None = None,
    limit: int = Query(default=200, le=1000),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SecurityAuditLog)
    if user.role == Role.SUPERSUDO and school_id is None:
        pass
    else:
        stmt = stmt.where(SecurityAuditLog.school_id == resolve_school_id(user, school_id))
    if action:
        stmt = stmt.where(SecurityAuditLog.action == action)
    if since:
        stmt = stmt.where(SecurityAuditLog.created_at >= since)
    return (await db.execute(stmt.order_by(SecurityAuditLog.created_at.desc()).limit(limit))).scalars().all()
