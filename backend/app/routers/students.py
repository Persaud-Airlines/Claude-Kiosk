"""Student roster, CSV import, live feeds, and the emergency / lockdown locator."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import audit
from ..core.database import get_db
from ..core.deps import ensure_same_school, get_school_or_404, require_admin, require_staff, resolve_school_id
from ..models import (
    Classroom,
    EntryMethod,
    EventType,
    HallPassEvent,
    School,
    Student,
    User,
)
from ..schemas import (
    EventOut,
    LocateResult,
    OutNowItem,
    RosterImportResult,
    StaffEventIn,
    StudentCreate,
    StudentOut,
    StudentUpdate,
)
from ..services.events import EventRejected, broadcast_event, record_event
from ..services.flagging import active_exemptions
from ..services.locator import currently_out, latest_events, roll_call, student_timeline
from ..services.students import clean_person_name, normalize_name
from ..services.timeutil import format_local, local_day_bounds_utc

router = APIRouter(prefix="/api/v1", tags=["students"])


async def _accommodation_ids(db: AsyncSession, student_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    from ..core.security import utcnow
    from ..models import StudentFlagExemption

    if not student_ids:
        return set()
    now = utcnow()
    rows = (
        await db.execute(
            select(StudentFlagExemption.student_id).where(
                StudentFlagExemption.student_id.in_(student_ids),
                StudentFlagExemption.is_active.is_(True),
                StudentFlagExemption.valid_from <= now,
                or_(StudentFlagExemption.valid_until.is_(None), StudentFlagExemption.valid_until >= now),
            )
        )
    ).scalars()
    return set(rows)


def _student_out(s: Student, accommodated: set[uuid.UUID]) -> StudentOut:
    out = StudentOut.model_validate(s)
    out.has_accommodation = s.id in accommodated
    return out


async def _events_out(db: AsyncSession, events: list[HallPassEvent]) -> list[EventOut]:
    room_ids = {e.classroom_id for e in events}
    st_ids = {e.student_id for e in events}
    rooms = {r.id: r for r in (await db.execute(select(Classroom).where(Classroom.id.in_(room_ids)))).scalars()} if room_ids else {}
    studs = {s.id: s for s in (await db.execute(select(Student).where(Student.id.in_(st_ids)))).scalars()} if st_ids else {}
    out = []
    for e in events:
        item = EventOut.model_validate(e)
        item.room_number = rooms[e.classroom_id].room_number if e.classroom_id in rooms else None
        s = studs.get(e.student_id)
        item.student_name = f"{s.first_name} {s.last_name}" if s else None
        out.append(item)
    return out


# --------------------------------------------------------------------------------- roster
@router.get("/students", response_model=list[StudentOut])
async def list_students(
    school_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=100),
    include_inactive: bool = False,
    limit: int = Query(default=200, le=1000),
    offset: int = 0,
    user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    sid = resolve_school_id(user, school_id)
    stmt = select(Student).where(Student.school_id == sid)
    if not include_inactive:
        stmt = stmt.where(Student.is_active.is_(True))
    if q:
        like = f"%{normalize_name(q, '').strip()}%"
        stmt = stmt.where(or_(Student.normalized_name.like(like), Student.student_number == q.strip()))
    rows = (await db.execute(stmt.order_by(Student.last_name, Student.first_name).limit(limit).offset(offset))).scalars().all()
    acc = await _accommodation_ids(db, [r.id for r in rows])
    return [_student_out(r, acc) for r in rows]


@router.post("/students", response_model=StudentOut, status_code=201)
async def create_student(
    body: StudentCreate,
    request: Request,
    school_id: uuid.UUID | None = None,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    sid = resolve_school_id(user, school_id)
    first, last = clean_person_name(body.first_name), clean_person_name(body.last_name)
    if body.homeroom_classroom_id:
        await _check_room(db, sid, body.homeroom_classroom_id)
    st = Student(
        school_id=sid, first_name=first, last_name=last, normalized_name=normalize_name(first, last),
        student_number=(body.student_number or "").strip() or None, homeroom_classroom_id=body.homeroom_classroom_id,
        grade=body.grade,
    )
    db.add(st)
    await db.flush()
    await audit(db, "CREATE_STUDENT", request=request, actor_user_id=user.id, school_id=sid, target=f"student:{st.id}")
    await db.commit()
    return _student_out(st, set())


@router.patch("/students/{student_id}", response_model=StudentOut)
async def update_student(
    student_id: uuid.UUID,
    body: StudentUpdate,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    st = await db.get(Student, student_id)
    if st is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ensure_same_school(user, st.school_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("homeroom_classroom_id"):
        await _check_room(db, st.school_id, data["homeroom_classroom_id"])
    for k, v in data.items():
        if k in ("first_name", "last_name") and v:
            v = clean_person_name(v)
        setattr(st, k, v)
    st.normalized_name = normalize_name(st.first_name, st.last_name)
    await audit(db, "UPDATE_STUDENT", request=request, actor_user_id=user.id, school_id=st.school_id,
                target=f"student:{st.id}", details={"fields": sorted(data)})
    await db.commit()
    return _student_out(st, await _accommodation_ids(db, [st.id]))


@router.post("/students/import", response_model=RosterImportResult)
async def import_roster(
    request: Request,
    file: UploadFile = File(...),
    school_id: uuid.UUID | None = None,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """CSV columns: first_name,last_name[,student_number][,homeroom][,grade] (header row required)."""
    sid = resolve_school_id(user, school_id)
    raw = await file.read(5_000_001)
    if len(raw) > 5_000_000:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "CSV larger than 5 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    headers = {h.strip().lower().replace(" ", "_") for h in (reader.fieldnames or [])}
    if not {"first_name", "last_name"} <= headers:
        raise HTTPException(422, "CSV must have first_name and last_name columns")
    rooms = {
        r.room_number.lower(): r.id
        for r in (await db.execute(select(Classroom).where(Classroom.school_id == sid))).scalars()
    }
    existing_by_num = {
        s.student_number: s
        for s in (await db.execute(select(Student).where(Student.school_id == sid, Student.student_number.is_not(None)))).scalars()
    }
    existing_by_name = {
        s.normalized_name: s for s in (await db.execute(select(Student).where(Student.school_id == sid))).scalars()
    }
    created = updated = skipped = 0
    errors: list[str] = []
    for line_no, row in enumerate(reader, start=2):
        row = {(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in row.items()}
        first, last = clean_person_name(row.get("first_name", "")), clean_person_name(row.get("last_name", ""))
        if not first or not last:
            skipped += 1
            if len(errors) < 50:
                errors.append(f"line {line_no}: missing name")
            continue
        number = row.get("student_number") or None
        homeroom = rooms.get(row.get("homeroom", "").lower()) if row.get("homeroom") else None
        if row.get("homeroom") and homeroom is None and len(errors) < 50:
            errors.append(f"line {line_no}: unknown homeroom '{row['homeroom']}' (left blank)")
        norm = normalize_name(first, last)
        st = existing_by_num.get(number) if number else None
        st = st or existing_by_name.get(norm)
        if st:
            st.first_name, st.last_name, st.normalized_name = first, last, norm
            st.student_number = number or st.student_number
            st.homeroom_classroom_id = homeroom or st.homeroom_classroom_id
            st.grade = row.get("grade") or st.grade
            st.is_active = True
            st.auto_registered = False
            updated += 1
        else:
            st = Student(school_id=sid, first_name=first, last_name=last, normalized_name=norm, student_number=number,
                         homeroom_classroom_id=homeroom, grade=row.get("grade") or None)
            db.add(st)
            existing_by_name[norm] = st
            if number:
                existing_by_num[number] = st
            created += 1
    await audit(db, "IMPORT_ROSTER", request=request, actor_user_id=user.id, school_id=sid,
                details={"created": created, "updated": updated, "skipped": skipped})
    await db.commit()
    return RosterImportResult(created=created, updated=updated, skipped=skipped, errors=errors)


async def _check_room(db: AsyncSession, school_id: uuid.UUID, room_id: uuid.UUID) -> Classroom:
    room = await db.get(Classroom, room_id)
    if room is None or room.school_id != school_id:
        raise HTTPException(422, "Classroom must belong to this school")
    return room


# ---------------------------------------------------------------------------- live feeds
@router.get("/classrooms/{classroom_id}/events", response_model=list[EventOut])
async def classroom_events(
    classroom_id: uuid.UUID,
    since: datetime | None = None,
    limit: int = Query(default=100, le=500),
    user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    room = await db.get(Classroom, classroom_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ensure_same_school(user, room.school_id)
    school = await db.get(School, room.school_id)
    since = since or local_day_bounds_utc(school.timezone)[0]
    rows = (
        await db.execute(
            select(HallPassEvent)
            .where(HallPassEvent.classroom_id == classroom_id, HallPassEvent.occurred_at_utc >= since)
            .order_by(HallPassEvent.occurred_at_utc.desc())
            .limit(limit)
        )
    ).scalars().all()
    return await _events_out(db, list(rows))


@router.get("/schools/{school_id}/events", response_model=list[EventOut])
async def school_events(
    school_id: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    cross_room_only: bool = False,
    limit: int = Query(default=200, le=1000),
    user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    ensure_same_school(user, school_id)
    school = await get_school_or_404(db, school_id)
    since = since or local_day_bounds_utc(school.timezone)[0]
    stmt = select(HallPassEvent).where(HallPassEvent.school_id == school_id, HallPassEvent.occurred_at_utc >= since)
    if until:
        stmt = stmt.where(HallPassEvent.occurred_at_utc <= until)
    if cross_room_only:
        stmt = stmt.where(HallPassEvent.is_lockdown_cross_room.is_(True))
    rows = (await db.execute(stmt.order_by(HallPassEvent.occurred_at_utc.desc()).limit(limit))).scalars().all()
    return await _events_out(db, list(rows))


@router.get("/schools/{school_id}/out-now", response_model=list[OutNowItem])
async def out_now(
    school_id: uuid.UUID,
    classroom_id: uuid.UUID | None = None,
    user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    ensure_same_school(user, school_id)
    school = await get_school_or_404(db, school_id)
    rows = await currently_out(db, school, classroom_id)
    rooms = {r.id: r for r in (await db.execute(select(Classroom).where(Classroom.school_id == school_id))).scalars()}
    acc = await _accommodation_ids(db, [s.id for _, s, _ in rows])
    return [
        OutNowItem(
            event_id=e.id, student_id=s.id, first_name=s.first_name, last_name=s.last_name, destination=e.destination,
            classroom_id=e.classroom_id, room_number=rooms[e.classroom_id].room_number if e.classroom_id in rooms else None,
            signed_out_at_utc=e.occurred_at_utc, minutes_out=m, overdue=m > school.flag_duration_minutes,
            has_accommodation=s.id in acc,
        )
        for e, s, m in rows
    ]


@router.post("/events/staff", response_model=EventOut, status_code=201)
async def staff_event(
    body: StaffEventIn, request: Request, user: User = Depends(require_staff), db: AsyncSession = Depends(get_db)
):
    """Manual sign-in/out by staff (e.g. kiosk offline, student has no card)."""
    st = await db.get(Student, body.student_id)
    room = await db.get(Classroom, body.classroom_id)
    if st is None or room is None or st.school_id != room.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ensure_same_school(user, st.school_id)
    school = await db.get(School, st.school_id)
    try:
        rec = await record_event(
            db, school=school, classroom=room, event_type=body.event_type, first_name=st.first_name,
            last_name=st.last_name, destination=body.destination, student=st, entry_method=EntryMethod.STAFF,
            notes=f"Entered by {user.full_name}" + (f": {body.notes}" if body.notes else ""),
        )
    except EventRejected as exc:
        raise HTTPException(422, str(exc))
    await audit(db, "STAFF_EVENT", request=request, actor_user_id=user.id, school_id=school.id,
                target=f"student:{st.id}", details={"type": body.event_type.value, "room": room.room_number})
    await db.commit()
    await broadcast_event(school, room, rec, st)
    return (await _events_out(db, [rec.event]))[0]


# -------------------------------------------------------------------- emergency locator
async def _locate(db: AsyncSession, school: School, st: Student) -> LocateResult:
    day_start = local_day_bounds_utc(school.timezone)[0]
    latest = (await latest_events(db, school.id, day_start, [st.id])).get(st.id)
    rooms = {r.id: r for r in (await db.execute(select(Classroom).where(Classroom.school_id == school.id))).scalars()}
    timeline = await student_timeline(db, st.id, limit=50)
    acc = await _accommodation_ids(db, [st.id])
    cur_room = rooms.get(latest.classroom_id) if latest else None
    state = "NO_ACTIVITY" if latest is None else ("OUT" if latest.event_type == EventType.SIGN_OUT else "IN_ROOM")
    return LocateResult(
        student=_student_out(st, acc),
        state=state,
        current_room_number=cur_room.room_number if cur_room else None,
        current_room_name=cur_room.room_name if cur_room else None,
        current_classroom_id=cur_room.id if cur_room else None,
        destination=latest.destination if latest else None,
        last_event_type=latest.event_type if latest else None,
        last_event_at_utc=latest.occurred_at_utc if latest else None,
        last_event_local=format_local(latest.occurred_at_utc, school.timezone) if latest else None,
        homeroom_number=rooms[st.homeroom_classroom_id].room_number if st.homeroom_classroom_id in rooms else None,
        is_cross_room=bool(latest and latest.is_lockdown_cross_room),
        timeline=await _events_out(db, timeline),
    )


@router.get("/schools/{school_id}/locate", response_model=list[LocateResult])
async def locate_students(
    school_id: uuid.UUID,
    request: Request,
    q: str = Query(min_length=2, max_length=100),
    user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """'Where is this student right now?' — never gated by billing status."""
    ensure_same_school(user, school_id)
    school = await get_school_or_404(db, school_id)
    needle = normalize_name(q, "").strip()
    tokens = needle.split()
    stmt = select(Student).where(Student.school_id == school_id)
    for t in tokens:
        stmt = stmt.where(Student.normalized_name.like(f"%{t}%"))
    if q.strip().isdigit():
        stmt = select(Student).where(Student.school_id == school_id, Student.student_number == q.strip())
    students = (await db.execute(stmt.order_by(Student.is_active.desc(), Student.last_name).limit(10))).scalars().all()
    await audit(db, "LOCKDOWN_SEARCH", request=request, actor_user_id=user.id, school_id=school_id,
                details={"query_len": len(q), "results": len(students)})
    await db.commit()
    return [await _locate(db, school, s) for s in students]


@router.get("/students/{student_id}/locate", response_model=LocateResult)
async def locate_one(student_id: uuid.UUID, user: User = Depends(require_staff), db: AsyncSession = Depends(get_db)):
    st = await db.get(Student, student_id)
    if st is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ensure_same_school(user, st.school_id)
    return await _locate(db, await db.get(School, st.school_id), st)


@router.get("/schools/{school_id}/roll-call")
async def lockdown_roll_call(
    school_id: uuid.UUID, request: Request, user: User = Depends(require_staff), db: AsyncSession = Depends(get_db)
):
    ensure_same_school(user, school_id)
    school = await get_school_or_404(db, school_id)
    data = await roll_call(db, school)
    await audit(db, "LOCKDOWN_ROLL_CALL_VIEW", request=request, actor_user_id=user.id, school_id=school_id)
    await db.commit()
    return data


@router.get("/schools/{school_id}/stats/students")
async def student_stats(
    school_id: uuid.UUID, days: int = Query(default=7, ge=1, le=90), user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from datetime import timedelta

    from ..core.security import utcnow

    ensure_same_school(user, school_id)
    since = utcnow() - timedelta(days=days)
    rows = (
        await db.execute(
            select(Student.id, Student.first_name, Student.last_name, func.count(HallPassEvent.id))
            .join(HallPassEvent, HallPassEvent.student_id == Student.id)
            .where(HallPassEvent.school_id == school_id, HallPassEvent.event_type == EventType.SIGN_OUT,
                   HallPassEvent.occurred_at_utc >= since)
            .group_by(Student.id, Student.first_name, Student.last_name)
            .order_by(func.count(HallPassEvent.id).desc())
            .limit(25)
        )
    ).all()
    return [{"student_id": str(r[0]), "name": f"{r[1]} {r[2]}", "sign_outs": r[3]} for r in rows]


__all__ = ["router", "active_exemptions"]
