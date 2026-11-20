"""Rule engine for excessive sign-out flags with medical / approved-accommodation exemptions."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import get_sessionmaker
from ..core.security import utcnow
from ..models import (
    EventType,
    FlagStatus,
    FlagType,
    HallPassEvent,
    School,
    Student,
    StudentFlag,
    StudentFlagExemption,
)
from .locator import latest_events, overdue_outs
from .realtime import hub
from .timeutil import local_day_bounds_utc, local_week_start_utc

log = logging.getLogger("detechtive.flags")


async def active_exemptions(
    db: AsyncSession, student_id: uuid.UUID, at: datetime | None = None
) -> list[StudentFlagExemption]:
    at = at or utcnow()
    rows = (
        await db.execute(
            select(StudentFlagExemption).where(
                StudentFlagExemption.student_id == student_id,
                StudentFlagExemption.is_active.is_(True),
                StudentFlagExemption.valid_from <= at,
                or_(StudentFlagExemption.valid_until.is_(None), StudentFlagExemption.valid_until >= at),
            )
        )
    ).scalars()
    return list(rows)


def exemption_covering(exemptions: list[StudentFlagExemption], destination: str | None) -> StudentFlagExemption | None:
    dest = (destination or "").strip().lower()
    for ex in exemptions:
        scope = [d.strip().lower() for d in (ex.applies_to_destinations or ["ALL"])]
        if "all" in scope or (dest and dest in scope):
            return ex
    return None


async def _create_flag(
    db: AsyncSession,
    *,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    flag_type: FlagType,
    details: str,
    dedupe_key: str,
    related_event_id: uuid.UUID | None,
    exemption: StudentFlagExemption | None,
) -> StudentFlag | None:
    existing = (await db.execute(select(StudentFlag).where(StudentFlag.dedupe_key == dedupe_key))).scalar_one_or_none()
    if existing is not None:
        # Escalation of an existing daily flag: refresh the human-readable detail only.
        if existing.trigger_details != details and existing.status != FlagStatus.RESOLVED:
            existing.trigger_details = details
        if existing.status == FlagStatus.SUPPRESSED_BY_EXEMPTION and exemption is None:
            # Non-exempt activity alone now exceeds the threshold: the accommodation no longer explains it.
            existing.status = FlagStatus.OPEN
            existing.is_suppressed_by_exemption = False
            existing.exemption_id = None
            return existing
        return None
    flag = StudentFlag(
        school_id=school_id,
        student_id=student_id,
        flag_type=flag_type,
        trigger_details=details,
        dedupe_key=dedupe_key,
        related_event_id=related_event_id,
        is_suppressed_by_exemption=exemption is not None,
        exemption_id=exemption.id if exemption else None,
        status=FlagStatus.SUPPRESSED_BY_EXEMPTION if exemption else FlagStatus.OPEN,
    )
    try:
        async with db.begin_nested():
            db.add(flag)
    except IntegrityError:
        return None
    return flag


async def evaluate_sign_out(db: AsyncSession, school: School, event: HallPassEvent) -> list[StudentFlag]:
    """Run frequency rules immediately after a SIGN_OUT is recorded (caller commits)."""
    created: list[StudentFlag] = []
    exemptions = await active_exemptions(db, event.student_id, event.occurred_at_utc)
    covered = {e.id for e in exemptions}

    async def _count(since: datetime) -> tuple[int, int]:
        rows = (
            await db.execute(
                select(HallPassEvent.destination).where(
                    HallPassEvent.student_id == event.student_id,
                    HallPassEvent.event_type == EventType.SIGN_OUT,
                    HallPassEvent.occurred_at_utc >= since,
                )
            )
        ).scalars().all()
        total = len(rows)
        non_exempt = sum(1 for d in rows if exemption_covering(exemptions, d) is None)
        return total, non_exempt

    day_start, _ = local_day_bounds_utc(school.timezone, event.occurred_at_utc)
    week_start = local_week_start_utc(school.timezone, event.occurred_at_utc)
    rules = [
        ("day", day_start, school.flag_threshold_count, "today"),
        ("week", week_start, school.flag_threshold_weekly_count, "this week"),
    ]
    for period, since, threshold, label in rules:
        if threshold <= 0:
            continue
        total, non_exempt = await _count(since)
        if total <= threshold:
            continue
        exemption = None
        if non_exempt <= threshold and covered:
            exemption = exemption_covering(exemptions, event.destination) or exemptions[0]
        details = f"Signed out {total} times {label} (threshold: {threshold})"
        if exemption:
            details += f"; {total - non_exempt} covered by approved accommodation"
        flag = await _create_flag(
            db,
            school_id=school.id,
            student_id=event.student_id,
            flag_type=FlagType.EXCESSIVE_FREQUENCY,
            details=details,
            dedupe_key=f"freq:{period}:{event.student_id}:{since.date().isoformat()}",
            related_event_id=event.id,
            exemption=exemption,
        )
        if flag:
            created.append(flag)
    return created


async def scan_school(db: AsyncSession, school: School) -> list[StudentFlag]:
    """Periodic rules: extended duration (still out) and unreturned sessions from prior days."""
    created: list[StudentFlag] = []
    for event, student, minutes in await overdue_outs(db, school):
        exemption = exemption_covering(await active_exemptions(db, student.id), event.destination)
        flag = await _create_flag(
            db,
            school_id=school.id,
            student_id=student.id,
            flag_type=FlagType.EXTENDED_DURATION,
            details=f"Out to {event.destination or 'unspecified'} for {minutes} min (limit: {school.flag_duration_minutes} min)",
            dedupe_key=f"dur:{event.id}",
            related_event_id=event.id,
            exemption=exemption,
        )
        if flag:
            created.append(flag)

    # Unreturned: latest event of yesterday (local) was a SIGN_OUT with no later event.
    today_start, _ = local_day_bounds_utc(school.timezone)
    yesterday_start = today_start - timedelta(days=1)
    latest_y = await latest_events(db, school.id, yesterday_start)
    for sid, ev in latest_y.items():
        if ev.event_type != EventType.SIGN_OUT or ev.occurred_at_utc >= today_start:
            continue
        exemption = exemption_covering(await active_exemptions(db, sid), ev.destination)
        flag = await _create_flag(
            db,
            school_id=school.id,
            student_id=sid,
            flag_type=FlagType.UNRETURNED_SESSION,
            details=f"Signed out to {ev.destination or 'unspecified'} and never signed back in",
            dedupe_key=f"unret:{ev.id}",
            related_event_id=ev.id,
            exemption=exemption,
        )
        if flag:
            created.append(flag)
    return created


async def publish_flags(school_id: uuid.UUID, flags: list[StudentFlag]) -> None:
    for f in flags:
        await hub.publish(
            school_id,
            {
                "type": "flag",
                "flag_id": str(f.id),
                "student_id": str(f.student_id),
                "flag_type": f.flag_type.value,
                "status": f.status.value,
                "suppressed": f.is_suppressed_by_exemption,
            },
        )


async def run_scan_once() -> int:
    total = 0
    async with get_sessionmaker()() as db:
        schools = (await db.execute(select(School))).scalars().all()
        for school in schools:
            flags = await scan_school(db, school)
            await db.commit()
            await publish_flags(school.id, flags)
            total += len(flags)
    return total


async def purge_expired_data() -> None:
    """Data-minimization: drop events, scan sessions and flags beyond the retention window."""
    from ..models import CardScanSession

    s = get_settings()
    cutoff = utcnow() - timedelta(days=s.data_retention_days)
    scan_cutoff = utcnow() - timedelta(hours=s.scan_session_ttl_hours)
    from sqlalchemy import delete

    async with get_sessionmaker()() as db:
        await db.execute(delete(StudentFlag).where(StudentFlag.created_at < cutoff))
        await db.execute(delete(HallPassEvent).where(HallPassEvent.occurred_at_utc < cutoff))
        await db.execute(delete(CardScanSession).where(CardScanSession.created_at < scan_cutoff))
        await db.commit()


async def background_loop(stop: asyncio.Event) -> None:
    interval = get_settings().flag_scan_interval_seconds
    ticks = 0
    while not stop.is_set():
        try:
            n = await run_scan_once()
            if n:
                log.info("flag scan raised %d flag(s)", n)
            if ticks % 60 == 0:
                await purge_expired_data()
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("flag scan failed")
        ticks += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def open_flag_counts(db: AsyncSession, school_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(StudentFlag).where(
                and_(StudentFlag.school_id == school_id, StudentFlag.status == FlagStatus.OPEN)
            )
        )
    ).scalar_one()


__all__ = [
    "active_exemptions",
    "exemption_covering",
    "evaluate_sign_out",
    "scan_school",
    "run_scan_once",
    "background_loop",
    "publish_flags",
    "open_flag_counts",
    "Student",
]
