"""SUPERSUDO (board / platform) portal: global overview, MRR, school provisioning."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import audit
from ..core.config import get_settings
from ..core.database import get_db
from ..core.deps import get_school_or_404, require_supersudo
from ..core.security import hash_password, utcnow, validate_password_strength
from ..models import (
    Classroom,
    HallPassEvent,
    KioskDevice,
    OrganizationBoard,
    PairingStatus,
    Role,
    School,
    SubscriptionStatus,
    User,
)
from ..schemas import SchoolCreate, SchoolOut
from ..services.timeutil import is_valid_timezone
from .kiosks import is_online

router = APIRouter(prefix="/api/v1/admin", tags=["supersudo"])


@router.get("/overview")
async def overview(_: User = Depends(require_supersudo), db: AsyncSession = Depends(get_db)):
    from datetime import timedelta

    s = get_settings()
    schools = (await db.execute(select(School).order_by(School.name))).scalars().all()
    devices = (await db.execute(select(KioskDevice).where(KioskDevice.pairing_status == PairingStatus.paired))).scalars().all()
    since = utcnow() - timedelta(hours=24)
    volume = dict(
        (
            await db.execute(
                select(HallPassEvent.school_id, func.count())
                .where(HallPassEvent.occurred_at_utc >= since)
                .group_by(HallPassEvent.school_id)
            )
        ).all()
    )
    boards = {b.id: b.name for b in (await db.execute(select(OrganizationBoard))).scalars()}
    rows = []
    for sc in schools:
        mine = [d for d in devices if d.school_id == sc.id]
        rows.append(
            {
                "id": str(sc.id),
                "name": sc.name,
                "board": boards.get(sc.board_id),
                "timezone": sc.timezone,
                "subscription_status": sc.subscription_status.value,
                "current_period_end": sc.subscription_current_period_end,
                "kiosks_total": len(mine),
                "kiosks_online": sum(1 for d in mine if is_online(d)),
                "events_24h": volume.get(sc.id, 0),
                "lockdown_active": sc.lockdown_active,
            }
        )
    paying = sum(1 for sc in schools if sc.subscription_status == SubscriptionStatus.active)
    return {
        "schools_total": len(schools),
        "schools_active": paying,
        "schools_past_due": sum(1 for sc in schools if sc.subscription_status == SubscriptionStatus.past_due),
        "kiosks_total": len(devices),
        "kiosks_online": sum(1 for d in devices if is_online(d)),
        "events_24h": sum(volume.values()),
        "mrr_cents": paying * s.school_monthly_price_cents,
        "schools": rows,
    }


@router.get("/schools", response_model=list[SchoolOut])
async def all_schools(_: User = Depends(require_supersudo), db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(School).order_by(School.name))).scalars().all()


@router.get("/kiosks")
async def kiosk_diagnostics(school_id: uuid.UUID, _: User = Depends(require_supersudo), db: AsyncSession = Depends(get_db)):
    """Device health only (no students, no sign-in events): for support and diagnostics."""
    await get_school_or_404(db, school_id)
    devices = (
        await db.execute(select(KioskDevice).where(KioskDevice.school_id == school_id).order_by(KioskDevice.device_uid))
    ).scalars().all()
    rooms = {r.id: r.room_number for r in (await db.execute(select(Classroom).where(Classroom.school_id == school_id))).scalars()}
    return [
        {
            "id": str(d.id),
            "device_uid": d.device_uid,
            "room_number": rooms.get(d.classroom_id),
            "pairing_status": d.pairing_status.value,
            "online": is_online(d),
            "firmware_version": d.firmware_version,
            "ip_address": d.ip_address,
            "wifi_rssi": d.wifi_rssi,
            "offline_queue_depth": d.offline_queue_depth,
            "last_seen_at": d.last_seen_at,
            "paired_at": d.paired_at,
        }
        for d in devices
    ]


@router.get("/boards")
async def boards(_: User = Depends(require_supersudo), db: AsyncSession = Depends(get_db)):
    return [{"id": str(b.id), "name": b.name} for b in (await db.execute(select(OrganizationBoard).order_by(OrganizationBoard.name))).scalars()]


@router.post("/schools", response_model=SchoolOut, status_code=201)
async def provision_school(
    body: SchoolCreate, request: Request, user: User = Depends(require_supersudo), db: AsyncSession = Depends(get_db)
):
    if not is_valid_timezone(body.timezone):
        raise HTTPException(422, "Unknown IANA timezone")
    board_id = body.board_id
    if board_id is None and body.board_name:
        board = (await db.execute(select(OrganizationBoard).where(OrganizationBoard.name == body.board_name.strip()))).scalar_one_or_none()
        if board is None:
            board = OrganizationBoard(name=body.board_name.strip())
            db.add(board)
            await db.flush()
        board_id = board.id
    school = School(name=body.name.strip(), address=body.address, timezone=body.timezone, board_id=board_id)
    db.add(school)
    await db.flush()
    if body.principal_email:
        if not body.principal_password or not body.principal_name:
            raise HTTPException(422, "Principal name and password are required")
        if err := validate_password_strength(body.principal_password):
            raise HTTPException(422, err)
        email = body.principal_email.lower()
        if (await db.execute(select(User.id).where(func.lower(User.email) == email))).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "Principal email already in use")
        db.add(User(email=email, full_name=body.principal_name, role=Role.PRINCIPAL, school_id=school.id,
                    password_hash=hash_password(body.principal_password)))
    await audit(db, "PROVISION_SCHOOL", request=request, actor_user_id=user.id, school_id=school.id,
                target=f"school:{school.id}")
    await db.commit()
    return school


@router.get("/schools/{school_id}/classroom-count")
async def classroom_count(school_id, _: User = Depends(require_supersudo), db: AsyncSession = Depends(get_db)):
    n = (await db.execute(select(func.count()).select_from(Classroom).where(Classroom.school_id == school_id))).scalar_one()
    return {"count": n}
