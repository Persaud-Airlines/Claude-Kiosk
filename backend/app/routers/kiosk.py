"""Kiosk-facing API: pairing handshake, config/heartbeat, card scanning, event submission."""
from __future__ import annotations

import asyncio
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import audit
from ..core.config import get_settings
from ..core.database import get_db
from ..core.deps import get_paired_device
from ..core.rate_limit import client_ip, enforce
from ..core.security import (
    as_utc,
    constant_time_equals,
    generate_pairing_code,
    hash_device_token,
    utcnow,
    verify_password,
)
from ..models import CardScanSession, Classroom, KioskDevice, PairingStatus, School, Student
from ..schemas import (
    HeartbeatRequest,
    KioskBatchIn,
    KioskConfig,
    KioskEventIn,
    KioskEventResult,
    PairInitRequest,
    PairInitResponse,
    PairStatusResponse,
    PinVerifyRequest,
    ScanResponse,
)
from ..services.events import EventRejected, broadcast_event, record_event
from ..services.ocr import analyze_card_image
from ..services.students import clean_person_name, find_student, fuzzy_roster_match
from ..services.timeutil import format_local, posix_tz_for

router = APIRouter(prefix="/api/v1/kiosk", tags=["kiosk"])
_ocr_slots = asyncio.Semaphore(2)


# ---------------------------------------------------------------------------------- pairing
@router.post("/pair/init", response_model=PairInitResponse)
async def pair_init(body: PairInitRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Unauthenticated: a fresh kiosk asks for an 8-character code to show on screen."""
    s = get_settings()
    enforce(request, "pair-init", 10)
    device = (await db.execute(select(KioskDevice).where(KioskDevice.device_uid == body.device_uid))).scalar_one_or_none()
    if device is None:
        device = KioskDevice(device_uid=body.device_uid, pairing_status=PairingStatus.unpaired)
        db.add(device)
    elif device.pairing_status == PairingStatus.revoked:
        device.pairing_status = PairingStatus.unpaired

    for _ in range(10):  # avoid collisions with other live codes
        code = generate_pairing_code()
        clash = (
            await db.execute(
                select(KioskDevice.id).where(
                    KioskDevice.pairing_code == code, KioskDevice.pairing_code_expires_at > utcnow()
                )
            )
        ).first()
        if not clash:
            break
    pairing_secret = secrets.token_urlsafe(24)
    expires = utcnow() + timedelta(minutes=s.pairing_code_ttl_minutes)
    device.pairing_code = code
    device.pairing_code_expires_at = expires
    device.pending_token_encrypted = None
    # The kiosk must present this secret while polling, so knowing a device_uid is not enough to steal a token.
    device.pairing_secret_hash = hash_device_token(pairing_secret)
    device.firmware_version = body.firmware_version
    device.ip_address = client_ip(request)
    await db.flush()
    await audit(db, "PAIR_INIT", request=request, actor_device_id=device.id, target=f"device:{device.device_uid}")
    await db.commit()
    url = f"{s.frontend_base_url.rstrip('/')}/pair?code={code}&uid={device.device_uid}"
    return PairInitResponse(
        pairing_code=code,
        pairing_secret=pairing_secret,
        expires_at=expires,
        expires_in_seconds=s.pairing_code_ttl_minutes * 60,
        pairing_url=url,
    )


@router.get("/pair/status/{device_uid}", response_model=PairStatusResponse)
async def pair_status(
    device_uid: str,
    request: Request,
    x_pairing_secret: str | None = Header(default=None, alias="X-Pairing-Secret"),
    db: AsyncSession = Depends(get_db),
):
    enforce(request, "pair-status", 90)
    device = (await db.execute(select(KioskDevice).where(KioskDevice.device_uid == device_uid))).scalar_one_or_none()
    if (
        device is None
        or not x_pairing_secret
        or not device.pairing_secret_hash
        or not constant_time_equals(device.pairing_secret_hash, hash_device_token(x_pairing_secret))
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid pairing secret; restart pairing")
    if device.pending_token_encrypted:
        token = device.pending_token_encrypted
        device.pending_token_encrypted = None  # one-time delivery
        school = await db.get(School, device.school_id)
        room = await db.get(Classroom, device.classroom_id)
        await audit(db, "PAIR_TOKEN_DELIVERED", request=request, actor_device_id=device.id, school_id=device.school_id)
        device.pairing_secret_hash = None
        await db.commit()
        return PairStatusResponse(
            status="paired",
            device_api_token=token,
            school_name=school.name,
            school_id=school.id,
            room_number=room.room_number,
            room_name=room.room_name,
            classroom_id=room.id,
            timezone=school.timezone,
            posix_tz=posix_tz_for(school.timezone),
            destinations=school.kiosk_destinations_json,
        )
    if device.pairing_status == PairingStatus.revoked:
        return PairStatusResponse(status="revoked")
    if device.pairing_code_expires_at is None or as_utc(device.pairing_code_expires_at) < utcnow():
        return PairStatusResponse(status="expired")
    return PairStatusResponse(status="pending")


# -------------------------------------------------------------------------- config / heartbeat
async def _config_for(db: AsyncSession, device: KioskDevice) -> KioskConfig:
    school = await db.get(School, device.school_id)
    room = await db.get(Classroom, device.classroom_id)
    if school is None or room is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Device assignment missing; re-pair")
    return KioskConfig(
        school_name=school.name,
        room_number=room.room_number,
        room_name=room.room_name,
        timezone=school.timezone,
        posix_tz=posix_tz_for(school.timezone),
        destinations=school.kiosk_destinations_json,
        lockdown_active=school.lockdown_active,
        server_time_utc=utcnow(),
    )


@router.get("/config", response_model=KioskConfig)
async def kiosk_config(device: KioskDevice = Depends(get_paired_device), db: AsyncSession = Depends(get_db)):
    cfg = await _config_for(db, device)
    await db.commit()
    return cfg


@router.post("/heartbeat", response_model=KioskConfig)
async def heartbeat(
    body: HeartbeatRequest,
    request: Request,
    device: KioskDevice = Depends(get_paired_device),
    db: AsyncSession = Depends(get_db),
):
    device.firmware_version = body.firmware_version or device.firmware_version
    device.ip_address = body.ip_address or client_ip(request)
    device.wifi_rssi = body.wifi_rssi
    device.offline_queue_depth = body.offline_queue_depth
    cfg = await _config_for(db, device)
    await db.commit()
    return cfg


@router.post("/verify-pin")
async def verify_pin(
    body: PinVerifyRequest,
    request: Request,
    device: KioskDevice = Depends(get_paired_device),
    db: AsyncSession = Depends(get_db),
):
    """Room-admin PIN gate for the hidden diagnostics / factory reset menu."""
    enforce(request, "kiosk-pin", 5, key_suffix=str(device.id))
    school = await db.get(School, device.school_id)
    ok = bool(school and school.kiosk_admin_pin_hash and verify_password(body.pin, school.kiosk_admin_pin_hash))
    await audit(db, "KIOSK_PIN_OK" if ok else "KIOSK_PIN_FAILED", request=request, actor_device_id=device.id,
                school_id=device.school_id)
    await db.commit()
    if not ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Incorrect PIN")
    return {"ok": True}


@router.post("/unpair", status_code=204)
async def self_unpair(request: Request, device: KioskDevice = Depends(get_paired_device), db: AsyncSession = Depends(get_db)):
    """Called by the kiosk after a PIN-protected factory reset."""
    device.pairing_status = PairingStatus.unpaired
    device.api_token_hash = None
    device.classroom_id = None
    await audit(db, "KIOSK_FACTORY_RESET", request=request, actor_device_id=device.id, school_id=device.school_id)
    await db.commit()


# -------------------------------------------------------------------------------- card scan
@router.post("/scan-card", response_model=ScanResponse)
async def scan_card(request: Request, device: KioskDevice = Depends(get_paired_device), db: AsyncSession = Depends(get_db)):
    """Body: raw `image/jpeg` bytes (preferred for the ESP32) or multipart field `image`."""
    s = get_settings()
    ctype = request.headers.get("content-type", "")
    declared = int(request.headers.get("content-length") or 0)
    if declared > s.max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Image too large")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("image")
        if upload is None or isinstance(upload, str):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing image field")
        data = await upload.read(s.max_upload_bytes + 1)
    else:
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > s.max_upload_bytes:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Image too large")
        data = bytes(data)
    if len(data) > s.max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Image too large")

    async with _ocr_slots:
        result = await run_in_threadpool(analyze_card_image, data)
    await db.commit()  # persist last_seen_at

    if not result.detected:
        return ScanResponse(detected=False, card_found=result.card_found, reason=result.reason)

    first, last = clean_person_name(result.first_name or ""), clean_person_name(result.last_name or "")
    confidence = result.confidence
    matched: Student | None = await find_student(db, device.school_id, first, last, result.student_number)
    if matched is None:
        cands = [(c.first, c.last) for c in result.candidates] or [(first, last)]
        fm = await fuzzy_roster_match(db, device.school_id, cands)
        if fm is not None:
            matched = fm.student
            confidence = max(confidence, min(0.99, 0.5 + fm.score / 2))
    else:
        confidence = max(confidence, 0.9)
    if matched is not None:
        first, last = matched.first_name, matched.last_name

    if confidence < s.ocr_min_confidence or not first or not last:
        return ScanResponse(detected=False, card_found=result.card_found, confidence=confidence, reason="low_confidence")

    scan = CardScanSession(
        kiosk_device_id=device.id,
        school_id=device.school_id,
        first_name=first,
        last_name=last,
        student_number=result.student_number,
        matched_student_id=matched.id if matched else None,
        confidence=confidence,
        engine=result.engine,
    )
    db.add(scan)
    await db.commit()
    return ScanResponse(
        detected=True,
        first_name=first,
        last_name=last,
        student_number=result.student_number,
        confidence=round(confidence, 3),
        scan_session_id=scan.id,
        card_found=result.card_found,
        roster_match=matched is not None,
    )


# ----------------------------------------------------------------------------------- events
async def _submit(db: AsyncSession, device: KioskDevice, body: KioskEventIn) -> KioskEventResult:
    if body.device_uid and body.device_uid != device.device_uid:
        return KioskEventResult(accepted=False, error="device_uid mismatch")
    if body.room_id and body.room_id != device.classroom_id:
        # A kiosk that was re-assigned while offline: record against its *current* room assignment is wrong,
        # so record against the room it was in when the event happened, if it belongs to the same school.
        room = await db.get(Classroom, body.room_id)
        if room is None or room.school_id != device.school_id:
            return KioskEventResult(accepted=False, error="room mismatch")
    else:
        room = await db.get(Classroom, device.classroom_id)
    school = await db.get(School, device.school_id)
    try:
        rec = await record_event(
            db,
            school=school,
            classroom=room,
            event_type=body.event_type,
            first_name=body.first_name,
            last_name=body.last_name,
            destination=body.destination,
            device=device,
            scan_session_id=body.scan_session_id,
            client_timestamp=body.client_timestamp_utc,
            client_event_id=body.client_event_id,
            offline=body.was_offline_queued,
            entry_method=body.entry_method,
        )
    except EventRejected as exc:
        await db.rollback()
        return KioskEventResult(accepted=False, error=str(exc))
    await db.commit()
    student = await db.get(Student, rec.event.student_id)
    if not rec.duplicate:
        await broadcast_event(school, room, rec, student)
    return KioskEventResult(
        accepted=True,
        event_id=rec.event.id,
        duplicate=rec.duplicate,
        recorded_at_utc=rec.event.occurred_at_utc,
        local_time=format_local(rec.event.occurred_at_utc, school.timezone),
        is_lockdown_cross_room=rec.event.is_lockdown_cross_room,
    )


@router.post("/events", response_model=KioskEventResult)
async def submit_event(
    body: KioskEventIn, device: KioskDevice = Depends(get_paired_device), db: AsyncSession = Depends(get_db)
):
    """Never blocked by billing status: student safety first."""
    res = await _submit(db, device, body)
    if not res.accepted:
        raise HTTPException(422, res.error or "rejected")
    return res


@router.post("/events/batch", response_model=list[KioskEventResult])
async def submit_batch(
    body: KioskBatchIn, device: KioskDevice = Depends(get_paired_device), db: AsyncSession = Depends(get_db)
):
    """Offline-queue flush: events are replayed in original chronological order, idempotently."""
    device_id = device.id
    ordered = sorted(body.events, key=lambda e: as_utc(e.client_timestamp_utc) if e.client_timestamp_utc else utcnow())
    results = []
    for ev in ordered:
        device = await db.get(KioskDevice, device_id)
        results.append(await _submit(db, device, ev))
    return results
