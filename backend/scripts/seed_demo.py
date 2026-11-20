#!/usr/bin/env python3
"""Seed a demo school (principal, teacher, rooms, roster) for local evaluation.

  cd backend && python scripts/seed_demo.py
Prints the demo credentials. Safe to re-run (skips if the demo school exists).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.database import get_sessionmaker  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import run_migrations  # noqa: E402
from app.models import Classroom, OrganizationBoard, Role, School, Student, User  # noqa: E402
from app.services.students import normalize_name  # noqa: E402

ROSTER = [
    ("Jordan", "Taylor", "300123456", "205"), ("Avery", "Nguyen", "300123457", "205"),
    ("Priya", "Shah", "300123458", "205"), ("Lucas", "De Silva", "300123459", "112"),
    ("Émilie", "Tremblay", "300123460", "112"), ("Mateo", "García", "300123461", "112"),
    ("Sam", "Rivera", "300123462", "204"), ("Morgan", "Lee", "300123463", "204"),
]


async def main() -> None:
    run_migrations()
    async with get_sessionmaker()() as db:
        if (await db.execute(select(School).where(School.name == "Lakeview Secondary School"))).scalar_one_or_none():
            print("Demo school already exists.")
            return
        board = OrganizationBoard(name="Demo District School Board")
        db.add(board)
        await db.flush()
        school = School(name="Lakeview Secondary School", address="100 Lakeview Ave", timezone="America/Toronto",
                        board_id=board.id, kiosk_admin_pin_hash=hash_password("2468"))
        db.add(school)
        await db.flush()
        rooms = {}
        for num, name in (("204", "Grade 12 Physics"), ("205", "Grade 11 English"), ("112", "Science Lab"),
                          ("Lab B", "Computer Lab")):
            rooms[num] = Classroom(school_id=school.id, room_number=num, room_name=name)
            db.add(rooms[num])
        await db.flush()
        principal = User(email="principal@lakeview.example.com", full_name="Pat Principal", role=Role.PRINCIPAL,
                         school_id=school.id, password_hash=hash_password("Lakeview-Principal-2026!"))
        teacher = User(email="teacher@lakeview.example.com", full_name="Terry Teacher", role=Role.TEACHER,
                       school_id=school.id, password_hash=hash_password("Lakeview-Teacher-2026!"))
        db.add_all([principal, teacher])
        await db.flush()
        rooms["205"].assigned_teacher_id = teacher.id
        for first, last, num, hr in ROSTER:
            db.add(Student(school_id=school.id, first_name=first, last_name=last, student_number=num,
                           normalized_name=normalize_name(first, last), homeroom_classroom_id=rooms[hr].id))
        await db.commit()
    print("Seeded 'Lakeview Secondary School'")
    print("  Principal: principal@lakeview.example.com / Lakeview-Principal-2026!")
    print("  Teacher:   teacher@lakeview.example.com   / Lakeview-Teacher-2026!")
    print("  Kiosk admin PIN: 2468")


if __name__ == "__main__":
    asyncio.run(main())
