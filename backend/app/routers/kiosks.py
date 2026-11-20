"""Portal-side kiosk management: claim a pairing code, list, reassign, revoke."""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import audit
from ..core.config import get_settings
from ..core.database import get_db
from ..core.deps import ensure_same_school, require_admin, resolve_school_id
from ..core.rate_limit import enforce
from ..core.security import as_utc, generate_device_token, hash_device_token, normalize_pairing_code, utcnow
from ..models import Classroom, KioskDevice, PairingStatus, User
from ..schemas import KioskDeviceOut, KioskReassign, PairClaimRequest

router = APIRouter(prefix="/api/v1/kiosks", tags=["kiosks"])


def is_online(device: KioskDevice) -> bool:
    if device.last_seen_at is None:
        return False
    return utcnow() - as_utc(device.last_seen_at) < timedelta(seconds=get_settings().kiosk_online_window_seconds)


def device_out(d: KioskDevice, room_number: str | None = None) -> KioskDeviceOut:
    out = KioskDeviceOut.model_validate(d)
    out.online = is_online(d)
    out.room_number = room_number
    return out


@router.post("/claim", response_model=KioskDeviceOut)
async def claim_pairing_code(
    body: PairClaimRequest, request: Request, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    """Admin enters the XXXX-XXXX code shown on the kiosk and assigns it to a room."""
    enforce(request, "pair-claim", 15, key_suffix=str(user.id))
    school_id = resolve_school_id(user, body.school_id)
    code = normalize_pairing_code(body.pairing_code)
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pairing code must be 8 characters (XXXX-XXXX)")
    q = select(KioskDevice).where(KioskDevice.pairing_code == code)
    if body.device_uid:
        q = q.where(KioskDevice.device_uid == body.device_uid)
    device = (await db.execute(q)).scalar_one_or_none()
    if device is None or device.pairing_code_expires_at is None or as_utc(device.pairing_code_expires_at) < utcnow():
        await audit(db, "PAIR_KIOSK_FAILED", request=request, actor_user_id=user.id, school_id=school_id,
                    target=f"code:{code}", commit=True)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pairing code not found or expired")
    if device.school_id and device.school_id != school_id and device.pairing_status == PairingStatus.paired:
        raise HTTPException(status.HTTP_409_CONFLICT, "Kiosk is paired to another school; revoke it there first")

    if body.classroom_id:
        room = await db.get(Classroom, body.classroom_id)
        if room is None or room.school_id != school_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Classroom not found")
    elif body.new_room_number:
        room = (
            await db.execute(
                select(Classroom).where(Classroom.school_id == school_id, Classroom.room_number == body.new_room_number.strip())
            )
        ).scalar_one_or_none()
        if room is None:
            room = Classroom(school_id=school_id, room_number=body.new_room_number.strip(), room_name=body.new_room_name)
            db.add(room)
            await db.flush()
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a classroom or enter a new room number")

    token = generate_device_token()
    device.school_id = school_id
    device.classroom_id = room.id
    device.api_token_hash = hash_device_token(token)
    device.pending_token_encrypted = token
    device.pairing_status = PairingStatus.paired
    device.pairing_code = None
    device.pairing_code_expires_at = None
    device.paired_at = utcnow()
    device.paired_by_user_id = user.id
    await audit(db, "PAIR_KIOSK", request=request, actor_user_id=user.id, school_id=school_id,
                target=f"device:{device.device_uid}", details={"room": room.room_number})
    await db.commit()
    return device_out(device, room.room_number)


@router.get("", response_model=list[KioskDeviceOut])
async def list_kiosks(
    school_id: uuid.UUID | None = None, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    sid = resolve_school_id(user, school_id)
    rows = (
        await db.execute(
            select(KioskDevice, Classroom.room_number)
            .outerjoin(Classroom, Classroom.id == KioskDevice.classroom_id)
            .where(KioskDevice.school_id == sid)
            .order_by(Classroom.room_number)
        )
    ).all()
    return [device_out(d, rn) for d, rn in rows]


@router.patch("/{device_id}", response_model=KioskDeviceOut)
async def reassign_kiosk(
    device_id: uuid.UUID,
    body: KioskReassign,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    device = await db.get(KioskDevice, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ensure_same_school(user, device.school_id)
    room = await db.get(Classroom, body.classroom_id)
    if room is None or room.school_id != device.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Classroom not found")
    device.classroom_id = room.id
    await audit(db, "REASSIGN_KIOSK", request=request, actor_user_id=user.id, school_id=device.school_id,
                target=f"device:{device.device_uid}", details={"room": room.room_number})
    await db.commit()
    return device_out(device, room.room_number)


@router.post("/{device_id}/revoke", response_model=KioskDeviceOut)
async def revoke_kiosk(
    device_id: uuid.UUID, request: Request, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    device = await db.get(KioskDevice, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ensure_same_school(user, device.school_id)
    device.pairing_status = PairingStatus.revoked
    device.api_token_hash = None
    device.pending_token_encrypted = None
    await audit(db, "REVOKE_KIOSK", request=request, actor_user_id=user.id, school_id=device.school_id,
                target=f"device:{device.device_uid}")
    await db.commit()
    return device_out(device)
