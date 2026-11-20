"""Approved accommodations (exemptions) and behavioural flags.

Privacy model
  * Exemption category + notes are health / special-education information. They are encrypted at rest and
    only returned to PRINCIPAL / SCHOOL_ADMIN / SUPERSUDO, with every read audited (VIEW_STUDENT_EXEMPTION).
  * TEACHERs may *create* an exemption and see that an "Approved Accommodation on File" exists, but never the
    reason category or notes.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import audit
from ..core.database import get_db
from ..core.deps import ensure_same_school, is_admin, require_staff, resolve_school_id
from ..core.security import as_utc, utcnow
from ..models import FlagStatus, HallPassEvent, Student, StudentFlag, StudentFlagExemption, User
from ..services.flagging import exemption_covering
from ..schemas import ExemptionCreate, ExemptionOut, ExemptionUpdate, FlagOut, FlagUpdate

router = APIRouter(prefix="/api/v1", tags=["exemptions & flags"])


def _exemption_out(ex: StudentFlagExemption, viewer: User) -> ExemptionOut:
    full = is_admin(viewer)
    return ExemptionOut(
        id=ex.id,
        student_id=ex.student_id,
        applies_to_destinations=ex.applies_to_destinations,
        valid_from=ex.valid_from,
        valid_until=ex.valid_until,
        is_active=ex.is_active,
        created_at=ex.created_at,
        redacted=not full,
        reason_category=ex.reason_category if full else None,
        reason_notes=ex.reason_notes if full else None,
        created_by_user_id=ex.created_by_user_id if full else None,
    )


def _clean_destinations(dests: list[str]) -> list[str]:
    cleaned = [d.strip()[:24] for d in dests if d and d.strip()]
    if not cleaned:
        return ["ALL"]
    if any(d.upper() == "ALL" for d in cleaned):
        return ["ALL"]
    return cleaned


@router.get("/students/{student_id}/exemptions", response_model=list[ExemptionOut])
async def list_exemptions(
    student_id: uuid.UUID, request: Request, user: User = Depends(require_staff), db: AsyncSession = Depends(get_db)
):
    st = await db.get(Student, student_id)
    if st is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ensure_same_school(user, st.school_id)
    rows = (
        await db.execute(
            select(StudentFlagExemption)
            .where(StudentFlagExemption.student_id == student_id)
            .order_by(StudentFlagExemption.created_at.desc())
        )
    ).scalars().all()
    if is_admin(user) and rows:
        await audit(db, "VIEW_STUDENT_EXEMPTION", request=request, actor_user_id=user.id, school_id=st.school_id,
                    target=f"student:{student_id}", details={"count": len(rows)})
        await db.commit()
    return [_exemption_out(r, user) for r in rows]


@router.post("/exemptions", response_model=ExemptionOut, status_code=201)
async def create_exemption(
    body: ExemptionCreate, request: Request, user: User = Depends(require_staff), db: AsyncSession = Depends(get_db)
):
    st = await db.get(Student, body.student_id)
    if st is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ensure_same_school(user, st.school_id)
    valid_from = as_utc(body.valid_from) if body.valid_from else utcnow()
    valid_until = as_utc(body.valid_until) if body.valid_until else None
    if valid_until and valid_until <= valid_from:
        raise HTTPException(422, "valid_until must be after valid_from")
    ex = StudentFlagExemption(
        school_id=st.school_id,
        student_id=st.id,
        created_by_user_id=user.id,
        reason_category=body.reason_category,
        reason_notes=body.reason_notes,
        applies_to_destinations=_clean_destinations(body.applies_to_destinations),
        valid_from=valid_from,
        valid_until=valid_until,
    )
    db.add(ex)
    await db.flush()
    # Retroactively mark today's open flags for this student as covered when the scope matches.
    open_flags = (
        await db.execute(
            select(StudentFlag).where(StudentFlag.student_id == st.id, StudentFlag.status == FlagStatus.OPEN)
        )
    ).scalars().all()
    suppressed = 0
    for f in open_flags:
        related = await db.get(HallPassEvent, f.related_event_id) if f.related_event_id else None
        if exemption_covering([ex], related.destination if related else None) is None:
            continue
        suppressed += 1
        f.is_suppressed_by_exemption = True
        f.exemption_id = ex.id
        f.status = FlagStatus.SUPPRESSED_BY_EXEMPTION
    await audit(db, "CREATE_EXEMPTION", request=request, actor_user_id=user.id, school_id=st.school_id,
                target=f"student:{st.id}", details={"exemption_id": str(ex.id), "suppressed_flags": suppressed})
    await db.commit()
    return _exemption_out(ex, user)


@router.patch("/exemptions/{exemption_id}", response_model=ExemptionOut)
async def update_exemption(
    exemption_id: uuid.UUID,
    body: ExemptionUpdate,
    request: Request,
    user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    ex = await db.get(StudentFlagExemption, exemption_id)
    if ex is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ensure_same_school(user, ex.school_id)
    if not is_admin(user) and ex.created_by_user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators can modify this accommodation")
    data = body.model_dump(exclude_unset=True)
    if "applies_to_destinations" in data and data["applies_to_destinations"] is not None:
        data["applies_to_destinations"] = _clean_destinations(data["applies_to_destinations"])
    if "valid_until" in data and data["valid_until"] is not None:
        data["valid_until"] = as_utc(data["valid_until"])
    for k, v in data.items():
        setattr(ex, k, v)
    await audit(db, "UPDATE_EXEMPTION", request=request, actor_user_id=user.id, school_id=ex.school_id,
                target=f"exemption:{ex.id}", details={"fields": sorted(data)})
    await db.commit()
    return _exemption_out(ex, user)


# ------------------------------------------------------------------------------------ flags
@router.get("/flags", response_model=list[FlagOut])
async def list_flags(
    school_id: uuid.UUID | None = None,
    status_filter: FlagStatus | None = Query(default=None, alias="status"),
    student_id: uuid.UUID | None = None,
    include_suppressed: bool = False,
    limit: int = Query(default=200, le=1000),
    user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    sid = resolve_school_id(user, school_id)
    stmt = select(StudentFlag, Student).join(Student, Student.id == StudentFlag.student_id).where(StudentFlag.school_id == sid)
    if status_filter:
        stmt = stmt.where(StudentFlag.status == status_filter)
    elif not include_suppressed:
        stmt = stmt.where(StudentFlag.status != FlagStatus.SUPPRESSED_BY_EXEMPTION)
    if student_id:
        stmt = stmt.where(StudentFlag.student_id == student_id)
    rows = (await db.execute(stmt.order_by(StudentFlag.created_at.desc()).limit(limit))).all()
    return [
        FlagOut(
            id=f.id, student_id=f.student_id, student_name=f"{s.first_name} {s.last_name}", flag_type=f.flag_type,
            trigger_details=f.trigger_details, is_suppressed_by_exemption=f.is_suppressed_by_exemption,
            status=f.status, reviewed_by_user_id=f.reviewed_by_user_id, reviewed_at=f.reviewed_at,
            created_at=f.created_at,
        )
        for f, s in rows
    ]


@router.patch("/flags/{flag_id}", response_model=FlagOut)
async def update_flag(
    flag_id: uuid.UUID, body: FlagUpdate, request: Request, user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    f = await db.get(StudentFlag, flag_id)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ensure_same_school(user, f.school_id)
    if body.status == FlagStatus.SUPPRESSED_BY_EXEMPTION:
        raise HTTPException(422, "Add an exemption to suppress a flag")
    f.status = body.status
    f.reviewed_by_user_id = user.id
    f.reviewed_at = utcnow()
    await audit(db, "REVIEW_FLAG", request=request, actor_user_id=user.id, school_id=f.school_id,
                target=f"flag:{f.id}", details={"status": body.status.value})
    await db.commit()
    s = await db.get(Student, f.student_id)
    return FlagOut(
        id=f.id, student_id=f.student_id, student_name=f"{s.first_name} {s.last_name}", flag_type=f.flag_type,
        trigger_details=f.trigger_details, is_suppressed_by_exemption=f.is_suppressed_by_exemption, status=f.status,
        reviewed_by_user_id=f.reviewed_by_user_id, reviewed_at=f.reviewed_at, created_at=f.created_at,
    )
