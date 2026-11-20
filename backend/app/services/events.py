"""Recording sign-in / sign-out events (shared by kiosk and staff-entered paths)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.security import as_utc, utcnow
from ..models import (
    CardScanSession,
    Classroom,
    EntryMethod,
    EventType,
    HallPassEvent,
    KioskDevice,
    School,
    Student,
    StudentFlag,
)
from .flagging import evaluate_sign_out, publish_flags
from .locator import previous_event
from .realtime import hub
from .students import clean_person_name, resolve_or_create_student
from .timeutil import format_local

ONLINE_SKEW = timedelta(minutes=5)
OFFLINE_MAX_AGE = timedelta(hours=72)
FUTURE_TOLERANCE = timedelta(minutes=2)


class EventRejected(Exception):
    pass


@dataclass
class RecordedEvent:
    event: HallPassEvent
    duplicate: bool
    flags: list[StudentFlag]


def validate_client_time(client_ts: datetime | None, offline: bool, now: datetime) -> tuple[datetime, str | None]:
    """Return (occurred_at, note). Trust the kiosk NTP clock only within sane bounds."""
    if client_ts is None:
        return now, None
    ts = as_utc(client_ts)
    if ts > now + FUTURE_TOLERANCE:
        return now, "client clock ahead of server; server time used"
    if offline:
        if now - ts > OFFLINE_MAX_AGE:
            return now, "offline event older than 72h; server time used"
        return ts, None
    if abs(now - ts) > ONLINE_SKEW:
        return now, "client clock skew > 5 min; server time used"
    return ts, None


async def compute_cross_room(
    db: AsyncSession, student: Student, classroom_id: uuid.UUID, event_type: EventType, at: datetime
) -> bool:
    if event_type != EventType.SIGN_IN:
        return False
    prev = await previous_event(db, student.id, at)
    if prev is not None and prev.event_type == EventType.SIGN_OUT and prev.classroom_id != classroom_id:
        return True
    if student.homeroom_classroom_id and student.homeroom_classroom_id != classroom_id:
        if prev is None or prev.classroom_id != classroom_id:
            return True
    return False


async def record_event(
    db: AsyncSession,
    *,
    school: School,
    classroom: Classroom,
    event_type: EventType,
    first_name: str,
    last_name: str,
    destination: str | None,
    device: KioskDevice | None = None,
    student: Student | None = None,
    scan_session_id: uuid.UUID | None = None,
    client_timestamp: datetime | None = None,
    client_event_id: str | None = None,
    offline: bool = False,
    entry_method: EntryMethod = EntryMethod.CARD_OCR,
    notes: str | None = None,
) -> RecordedEvent:
    now = utcnow()
    if device is not None and client_event_id:
        existing = (
            await db.execute(
                select(HallPassEvent).where(
                    HallPassEvent.kiosk_device_id == device.id, HallPassEvent.client_event_id == client_event_id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return RecordedEvent(existing, True, [])

    note_parts: list[str] = [notes] if notes else []
    student_number = None
    if scan_session_id is not None:
        scan = await db.get(CardScanSession, scan_session_id)
        if scan is None or (device is not None and scan.kiosk_device_id != device.id):
            if not offline:
                raise EventRejected("Unknown scan session")
            note_parts.append("scan session not found")
        else:
            age = now - as_utc(scan.created_at)
            if age > timedelta(hours=get_settings().scan_session_ttl_hours):
                note_parts.append("scan session expired")
            if scan.consumed and not offline:
                raise EventRejected("Scan session already used")
            scan.consumed = True
            student_number = scan.student_number
            if student is None and scan.matched_student_id is not None:
                student = await db.get(Student, scan.matched_student_id)
    elif entry_method == EntryMethod.CARD_OCR and device is not None and not offline:
        raise EventRejected("scan_session_id is required for card sign-ins")

    if event_type == EventType.SIGN_OUT:
        destination = (destination or "").strip()[:60] or "Other"
        if destination.lower() not in {d.lower() for d in school.kiosk_destinations_json or []}:
            note_parts.append("destination not in school's current list")
    else:
        destination = None

    first_c, last_c = clean_person_name(first_name), clean_person_name(last_name)
    if not first_c or not last_c:
        raise EventRejected("Invalid student name")
    if student is None:
        student = await resolve_or_create_student(
            db,
            school.id,
            first_c,
            last_c,
            student_number,
            homeroom_classroom_id=classroom.id if event_type == EventType.SIGN_OUT else None,
        )

    occurred_at, time_note = validate_client_time(client_timestamp, offline, now)
    if time_note:
        note_parts.append(time_note)
    cross = await compute_cross_room(db, student, classroom.id, event_type, occurred_at)

    event = HallPassEvent(
        school_id=school.id,
        classroom_id=classroom.id,
        kiosk_device_id=device.id if device else None,
        student_id=student.id,
        scan_session_id=scan_session_id,
        client_event_id=client_event_id,
        scanned_first_name=first_c,
        scanned_last_name=last_c,
        event_type=event_type,
        destination=destination,
        entry_method=entry_method,
        recorded_at_utc=now,
        client_timestamp_utc=as_utc(client_timestamp) if client_timestamp else None,
        occurred_at_utc=occurred_at,
        was_offline_queued=offline,
        is_lockdown_cross_room=cross,
        during_lockdown=school.lockdown_active,
        notes="; ".join(note_parts)[:500] or None,
    )
    db.add(event)
    await db.flush()
    flags: list[StudentFlag] = []
    if event_type == EventType.SIGN_OUT:
        flags = await evaluate_sign_out(db, school, event)
    return RecordedEvent(event, False, flags)


async def broadcast_event(school: School, classroom: Classroom, rec: RecordedEvent, student: Student) -> None:
    e = rec.event
    await hub.publish(
        school.id,
        {
            "type": "event",
            "event_id": str(e.id),
            "event_type": e.event_type.value,
            "student_id": str(student.id),
            "first_name": student.first_name,
            "last_name": student.last_name,
            "classroom_id": str(classroom.id),
            "room_number": classroom.room_number,
            "destination": e.destination,
            "occurred_at_utc": e.occurred_at_utc.isoformat(),
            "local_time": format_local(e.occurred_at_utc, school.timezone),
            "is_lockdown_cross_room": e.is_lockdown_cross_room,
            "during_lockdown": e.during_lockdown,
        },
    )
    await publish_flags(school.id, rec.flags)
