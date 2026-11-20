"""Student roster resolution, auto-registration and fuzzy matching."""
from __future__ import annotations

import difflib
import re
import unicodedata
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Student

_ws = re.compile(r"\s+")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_name(first: str, last: str) -> str:
    joined = f"{first} {last}".strip().lower()
    joined = strip_accents(joined)
    joined = re.sub(r"[^a-z' -]", "", joined)
    return _ws.sub(" ", joined).strip()


def clean_person_name(value: str) -> str:
    """Trim, collapse whitespace and title-case a name while preserving Mc/O'/hyphenation."""
    value = _ws.sub(" ", value.strip())
    value = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ' -]", "", value)[:100]

    def cap(token: str) -> str:
        if not token:
            return token
        parts = re.split(r"([-'])", token)
        out = []
        for p in parts:
            if p in ("-", "'"):
                out.append(p)
            elif p:
                t = p[0].upper() + p[1:].lower()
                if t.startswith("Mc") and len(t) > 2:
                    t = "Mc" + t[2].upper() + t[3:]
                out.append(t)
        return "".join(out)

    return " ".join(cap(t) for t in value.split(" ")).strip()


@dataclass
class RosterMatch:
    student: Student
    score: float


async def find_student(
    db: AsyncSession, school_id: uuid.UUID, first: str, last: str, student_number: str | None = None
) -> Student | None:
    norm = normalize_name(first, last)
    if student_number:
        st = (
            await db.execute(
                select(Student).where(Student.school_id == school_id, Student.student_number == student_number)
            )
        ).scalar_one_or_none()
        # An OCR-misread digit must never attribute a card to a different student: the printed name has to agree.
        if st and difflib.SequenceMatcher(None, st.normalized_name, norm).ratio() >= 0.75:
            return st
    return (
        await db.execute(
            select(Student)
            .where(Student.school_id == school_id, Student.normalized_name == norm)
            .order_by(Student.is_active.desc(), Student.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()


async def resolve_or_create_student(
    db: AsyncSession,
    school_id: uuid.UUID,
    first: str,
    last: str,
    student_number: str | None = None,
    homeroom_classroom_id: uuid.UUID | None = None,
) -> Student:
    first_c, last_c = clean_person_name(first), clean_person_name(last)
    st = await find_student(db, school_id, first_c, last_c, student_number)
    if st:
        if not st.is_active:
            st.is_active = True
        return st
    if student_number:
        taken = (
            await db.execute(
                select(Student.id).where(Student.school_id == school_id, Student.student_number == student_number)
            )
        ).first()
        if taken:  # number already belongs to someone else (likely an OCR misread): don't copy it
            student_number = None
    st = Student(
        school_id=school_id,
        first_name=first_c,
        last_name=last_c,
        normalized_name=normalize_name(first_c, last_c),
        student_number=student_number or None,
        homeroom_classroom_id=homeroom_classroom_id,
        auto_registered=True,
    )
    db.add(st)
    await db.flush()
    return st


async def fuzzy_roster_match(
    db: AsyncSession, school_id: uuid.UUID, candidates: list[tuple[str, str]], cutoff: float = 0.82
) -> RosterMatch | None:
    """Correct OCR noise (e.g. 'J0rdan Tay1or') against the enrolled roster."""
    rows = (
        await db.execute(select(Student).where(Student.school_id == school_id, Student.is_active.is_(True)))
    ).scalars().all()
    if not rows:
        return None
    by_norm = {s.normalized_name: s for s in rows}
    keys = list(by_norm.keys())
    best: RosterMatch | None = None
    for first, last in candidates:
        for probe in (normalize_name(first, last), normalize_name(last, first)):
            if not probe:
                continue
            for hit in difflib.get_close_matches(probe, keys, n=1, cutoff=cutoff):
                score = difflib.SequenceMatcher(None, probe, hit).ratio()
                if best is None or score > best.score:
                    best = RosterMatch(by_norm[hit], score)
    return best
