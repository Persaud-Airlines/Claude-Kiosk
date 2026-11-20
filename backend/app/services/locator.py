"""Student whereabouts: current status, out-of-room lists, lockdown roll-call, movement timelines."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..core.security import utcnow
from ..models import Classroom, EventType, HallPassEvent, School, Student
from .timeutil import local_day_bounds_utc


@dataclass
class StudentStatus:
    student: Student
    last_event: HallPassEvent | None
    classroom: Classroom | None

    @property
    def state(self) -> str:
        if self.last_event is None:
            return "NO_ACTIVITY"
        return "OUT" if self.last_event.event_type == EventType.SIGN_OUT else "IN_ROOM"


async def latest_events(
    db: AsyncSession, school_id: uuid.UUID, since: datetime | None, student_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, HallPassEvent]:
    """Most recent event per student (by occurred time) since `since`."""
    conds = [HallPassEvent.school_id == school_id]
    if since is not None:
        conds.append(HallPassEvent.occurred_at_utc >= since)
    if student_ids is not None:
        if not student_ids:
            return {}
        conds.append(HallPassEvent.student_id.in_(student_ids))
    ranked = (
        select(
            HallPassEvent.id.label("eid"),
            func.row_number()
            .over(
                partition_by=HallPassEvent.student_id,
                order_by=(HallPassEvent.occurred_at_utc.desc(), HallPassEvent.recorded_at_utc.desc()),
            )
            .label("rn"),
        )
        .where(and_(*conds))
        .subquery()
    )
    ev = aliased(HallPassEvent)
    rows = (await db.execute(select(ev).join(ranked, ranked.c.eid == ev.id).where(ranked.c.rn == 1))).scalars().all()
    return {e.student_id: e for e in rows}


async def school_day_start(db: AsyncSession, school: School) -> datetime:
    start, _ = local_day_bounds_utc(school.timezone)
    return start


async def currently_out(
    db: AsyncSession, school: School, classroom_id: uuid.UUID | None = None
) -> list[tuple[HallPassEvent, Student, int]]:
    """Students whose latest event today is a SIGN_OUT; returns (event, student, minutes_out)."""
    since = await school_day_start(db, school)
    latest = await latest_events(db, school.id, since)
    now = utcnow()
    out: list[tuple[HallPassEvent, Student, int]] = []
    ids = [sid for sid, e in latest.items() if e.event_type == EventType.SIGN_OUT]
    if not ids:
        return out
    students = {s.id: s for s in (await db.execute(select(Student).where(Student.id.in_(ids)))).scalars()}
    for sid in ids:
        e = latest[sid]
        if classroom_id is not None and e.classroom_id != classroom_id:
            continue
        minutes = int((now - e.occurred_at_utc).total_seconds() // 60)
        out.append((e, students[sid], minutes))
    out.sort(key=lambda t: t[0].occurred_at_utc)
    return out


async def student_timeline(
    db: AsyncSession, student_id: uuid.UUID, since: datetime | None = None, limit: int = 200
) -> list[HallPassEvent]:
    q = select(HallPassEvent).where(HallPassEvent.student_id == student_id)
    if since is not None:
        q = q.where(HallPassEvent.occurred_at_utc >= since)
    q = q.order_by(HallPassEvent.occurred_at_utc.desc()).limit(limit)
    return list((await db.execute(q)).scalars())


async def previous_event(db: AsyncSession, student_id: uuid.UUID, before: datetime) -> HallPassEvent | None:
    return (
        await db.execute(
            select(HallPassEvent)
            .where(HallPassEvent.student_id == student_id, HallPassEvent.occurred_at_utc <= before)
            .order_by(HallPassEvent.occurred_at_utc.desc(), HallPassEvent.recorded_at_utc.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def roll_call(db: AsyncSession, school: School) -> dict:
    """Lockdown roll-call: who has checked in where since lockdown began (or since start of day)."""
    since = school.lockdown_started_at if school.lockdown_active and school.lockdown_started_at else None
    day_start = await school_day_start(db, school)
    window_start = since or day_start
    latest_today = await latest_events(db, school.id, day_start)
    classrooms = {
        c.id: c for c in (await db.execute(select(Classroom).where(Classroom.school_id == school.id))).scalars()
    }
    students = list(
        (
            await db.execute(
                select(Student)
                .where(Student.school_id == school.id, Student.is_active.is_(True))
                .order_by(Student.last_name, Student.first_name)
            )
        ).scalars()
    )
    rooms: dict[str, dict] = {
        str(cid): {"classroom_id": str(cid), "room_number": c.room_number, "room_name": c.room_name, "students": []}
        for cid, c in classrooms.items()
    }
    out_list, unaccounted = [], []
    accounted = 0
    for st in students:
        e = latest_today.get(st.id)
        entry = {
            "student_id": str(st.id),
            "first_name": st.first_name,
            "last_name": st.last_name,
            "student_number": st.student_number,
            "homeroom": classrooms[st.homeroom_classroom_id].room_number
            if st.homeroom_classroom_id in classrooms
            else None,
        }
        if e is not None:
            entry["last_event_type"] = e.event_type.value
            entry["last_event_at"] = e.occurred_at_utc.isoformat()
            entry["room_number"] = classrooms[e.classroom_id].room_number if e.classroom_id in classrooms else None
            entry["destination"] = e.destination
            entry["is_cross_room"] = e.is_lockdown_cross_room
        if e is not None and e.event_type == EventType.SIGN_IN and e.occurred_at_utc >= window_start:
            accounted += 1
            rooms[str(e.classroom_id)]["students"].append(entry)
        elif e is not None and e.event_type == EventType.SIGN_OUT:
            out_list.append(entry)
        else:
            unaccounted.append(entry)
    return {
        "lockdown_active": school.lockdown_active,
        "window_start_utc": window_start.isoformat(),
        "total_students": len(students),
        "accounted_count": accounted,
        "out_of_room_count": len(out_list),
        "unaccounted_count": len(unaccounted),
        "rooms": sorted(rooms.values(), key=lambda r: r["room_number"]),
        "out_of_room": out_list,
        "unaccounted": unaccounted,
    }


async def overdue_outs(db: AsyncSession, school: School) -> list[tuple[HallPassEvent, Student, int]]:
    limit = timedelta(minutes=school.flag_duration_minutes)
    now = utcnow()
    return [t for t in await currently_out(db, school) if now - t[0].occurred_at_utc > limit]
