"""School settings, classrooms, lockdown mode and school-scoped dashboards."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import audit
from ..core.database import get_db
from ..core.deps import ensure_same_school, get_school_or_404, require_admin, require_staff, resolve_school_id
from ..core.security import hash_password, utcnow
from ..models import Classroom, EventType, HallPassEvent, KioskDevice, PairingStatus, School, User
from ..schemas import ClassroomCreate, ClassroomOut, ClassroomUpdate, SchoolOut, SchoolSettingsUpdate
from ..services.flagging import open_flag_counts
from ..services.locator import currently_out
from ..services.realtime import hub
from ..services.timeutil import common_timezones, is_valid_timezone, local_day_bounds_utc
from .kiosks import is_online

router = APIRouter(prefix="/api/v1/schools", tags=["schools"])


@router.get("/timezones", response_model=list[str])
async def timezones(_: User = Depends(require_staff)):
    return common_timezones()


@router.get("/current", response_model=SchoolOut)
async def current_school(
    school_id: uuid.UUID | None = None, user: User = Depends(require_staff), db: AsyncSession = Depends(get_db)
):
    return await get_school_or_404(db, resolve_school_id(user, school_id))


@router.patch("/{school_id}", response_model=SchoolOut)
async def update_school(
    school_id: uuid.UUID,
    body: SchoolSettingsUpdate,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ensure_same_school(user, school_id)
    school = await get_school_or_404(db, school_id)
    data = body.model_dump(exclude_unset=True)
    if "timezone" in data and not is_valid_timezone(data["timezone"]):
        raise HTTPException(422, "Unknown IANA timezone")
    pin = data.pop("kiosk_admin_pin", None)
    if pin:
        school.kiosk_admin_pin_hash = hash_password(pin)
    for k, v in data.items():
        setattr(school, k, v)
    await audit(db, "UPDATE_SCHOOL_SETTINGS", request=request, actor_user_id=user.id, school_id=school_id,
                details={"fields": sorted(list(data.keys()) + (["kiosk_admin_pin"] if pin else []))})
    await db.commit()
    return school


@router.post("/{school_id}/lockdown", response_model=SchoolOut)
async def set_lockdown(
    school_id: uuid.UUID,
    active: bool,
    request: Request,
    user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Any staff member can START a lockdown roll-call; only admins can END one."""
    ensure_same_school(user, school_id)
    school = await get_school_or_404(db, school_id)
    if not active and user.role.value == "TEACHER":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators can end a lockdown")
    if active and not school.lockdown_active:
        school.lockdown_active = True
        school.lockdown_started_at = utcnow()
    elif not active:
        school.lockdown_active = False
    await audit(db, "LOCKDOWN_START" if active else "LOCKDOWN_END", request=request, actor_user_id=user.id,
                school_id=school_id)
    await db.commit()
    await hub.publish(school_id, {"type": "lockdown", "active": school.lockdown_active})
    return school


@router.get("/{school_id}/dashboard")
async def dashboard(school_id: uuid.UUID, user: User = Depends(require_staff), db: AsyncSession = Depends(get_db)):
    ensure_same_school(user, school_id)
    school = await get_school_or_404(db, school_id)
    start, _ = local_day_bounds_utc(school.timezone)
    counts = dict(
        (
            await db.execute(
                select(HallPassEvent.event_type, func.count())
                .where(HallPassEvent.school_id == school_id, HallPassEvent.occurred_at_utc >= start)
                .group_by(HallPassEvent.event_type)
            )
        ).all()
    )
    devices = (
        await db.execute(
            select(KioskDevice).where(KioskDevice.school_id == school_id, KioskDevice.pairing_status == PairingStatus.paired)
        )
    ).scalars().all()
    out_now = await currently_out(db, school)
    return {
        "school_id": str(school_id),
        "sign_outs_today": counts.get(EventType.SIGN_OUT, 0),
        "sign_ins_today": counts.get(EventType.SIGN_IN, 0),
        "currently_out": len(out_now),
        "overdue": sum(1 for _, _, m in out_now if m > school.flag_duration_minutes),
        "open_flags": await open_flag_counts(db, school_id),
        "kiosks_total": len(devices),
        "kiosks_online": sum(1 for d in devices if is_online(d)),
        "lockdown_active": school.lockdown_active,
        "subscription_status": school.subscription_status.value,
    }


# ----------------------------------------------------------------------------------- rooms
@router.get("/{school_id}/classrooms", response_model=list[ClassroomOut])
async def list_classrooms(school_id: uuid.UUID, user: User = Depends(require_staff), db: AsyncSession = Depends(get_db)):
    ensure_same_school(user, school_id)
    school = await get_school_or_404(db, school_id)
    rooms = (
        await db.execute(select(Classroom).where(Classroom.school_id == school_id).order_by(Classroom.room_number))
    ).scalars().all()
    out_now = await currently_out(db, school)
    devices = (
        await db.execute(
            select(KioskDevice).where(KioskDevice.school_id == school_id, KioskDevice.pairing_status == PairingStatus.paired)
        )
    ).scalars().all()
    by_room = {d.classroom_id: d for d in devices}
    result = []
    for r in rooms:
        item = ClassroomOut.model_validate(r)
        item.out_count = sum(1 for e, _, _ in out_now if e.classroom_id == r.id)
        item.kiosk_online = is_online(by_room[r.id]) if r.id in by_room else None
        result.append(item)
    return result


@router.post("/{school_id}/classrooms", response_model=ClassroomOut, status_code=201)
async def create_classroom(
    school_id: uuid.UUID,
    body: ClassroomCreate,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ensure_same_school(user, school_id)
    await get_school_or_404(db, school_id)
    if body.assigned_teacher_id:
        await _check_teacher(db, school_id, body.assigned_teacher_id)
    room = Classroom(school_id=school_id, **body.model_dump())
    db.add(room)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Room number already exists")
    await audit(db, "CREATE_CLASSROOM", request=request, actor_user_id=user.id, school_id=school_id,
                target=f"classroom:{room.id}")
    await db.commit()
    return room


@router.patch("/classrooms/{classroom_id}", response_model=ClassroomOut)
async def update_classroom(
    classroom_id: uuid.UUID,
    body: ClassroomUpdate,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    room = await db.get(Classroom, classroom_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ensure_same_school(user, room.school_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("assigned_teacher_id"):
        await _check_teacher(db, room.school_id, data["assigned_teacher_id"])
    for k, v in data.items():
        setattr(room, k, v)
    try:
        await audit(db, "UPDATE_CLASSROOM", request=request, actor_user_id=user.id, school_id=room.school_id,
                    target=f"classroom:{room.id}")
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Room number already exists")
    return room


@router.delete("/classrooms/{classroom_id}", status_code=204)
async def delete_classroom(
    classroom_id: uuid.UUID, request: Request, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    room = await db.get(Classroom, classroom_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ensure_same_school(user, room.school_id)
    has_events = (await db.execute(select(HallPassEvent.id).where(HallPassEvent.classroom_id == classroom_id).limit(1))).first()
    if has_events:
        raise HTTPException(status.HTTP_409_CONFLICT, "Classroom has audit history and cannot be deleted; rename it instead")
    await audit(db, "DELETE_CLASSROOM", request=request, actor_user_id=user.id, school_id=room.school_id,
                target=f"classroom:{room.id}")
    await db.delete(room)
    await db.commit()


async def _check_teacher(db: AsyncSession, school_id: uuid.UUID, teacher_id: uuid.UUID) -> None:
    t = await db.get(User, teacher_id)
    if t is None or t.school_id != school_id:
        raise HTTPException(422, "Teacher must belong to this school")


__all__ = ["router", "School"]
