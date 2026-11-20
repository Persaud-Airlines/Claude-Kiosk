"""Test fixtures: isolated SQLite DB per test session, real migrations, TestClient with lifespan."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

_tmp = tempfile.mkdtemp(prefix="detechtive-test-")
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "USE_SQLITE": "true",
        "SQLITE_PATH": os.path.join(_tmp, "test.db"),
        "BOOTSTRAP_SUPERSUDO_EMAIL": "root@test.local",
        "BOOTSTRAP_SUPERSUDO_PASSWORD": "Sup3r-Secret-Pass!",
        "STRIPE_WEBHOOK_SECRET": "whsec_test_secret",
        "FRONTEND_BASE_URL": "http://portal.test",
        "RATE_LIMIT_AUTH_PER_MINUTE": "1000",
        "ALEMBIC_SKIP_LOGGING": "1",
        "OCR_ENGINE": "tesseract",
    }
)

# Run the suite against PostgreSQL with: TEST_DATABASE_URL=postgresql+asyncpg://... pytest
if os.environ.get("TEST_DATABASE_URL"):
    os.environ.update({"USE_SQLITE": "false", "DATABASE_URL": os.environ["TEST_DATABASE_URL"]})

from fastapi.testclient import TestClient  # noqa: E402

from app.core.rate_limit import limiter  # noqa: E402
from app.main import create_app  # noqa: E402

SUPER = ("root@test.local", "Sup3r-Secret-Pass!")
PRINCIPAL_PW = "Principal-Pass-123!"
TEACHER_PW = "Teacher-Pass-123!"


@pytest.fixture(scope="session")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()
    yield


def login(client, email, password) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def super_headers(client):
    return login(client, *SUPER)


_counter = {"n": 0}


@pytest.fixture
def school(client, super_headers):
    """A fresh school with principal, teacher, two classrooms and a paired kiosk in Room 205."""
    _counter["n"] += 1
    n = _counter["n"]
    r = client.post(
        "/api/v1/admin/schools",
        headers=super_headers,
        json={
            "name": f"Lakeview Secondary {n}",
            "timezone": "America/Toronto",
            "board_name": "Test District Board",
            "principal_email": f"principal{n}@school.test",
            "principal_name": "Pat Principal",
            "principal_password": PRINCIPAL_PW,
        },
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    ph = login(client, f"principal{n}@school.test", PRINCIPAL_PW)
    r = client.post("/api/v1/users", headers=ph, json={"email": f"teacher{n}@school.test", "full_name": "Terry Teacher",
                                                       "role": "TEACHER", "password": TEACHER_PW})
    assert r.status_code == 201, r.text
    th = login(client, f"teacher{n}@school.test", TEACHER_PW)
    rooms = {}
    for num, name in (("205", "Homeroom 205"), ("112", "Science Lab")):
        r = client.post(f"/api/v1/schools/{sid}/classrooms", headers=ph, json={"room_number": num, "room_name": name})
        assert r.status_code == 201, r.text
        rooms[num] = r.json()["id"]
    kiosk205 = pair_kiosk(client, ph, rooms["205"], f"TESTUID{n:04d}A205")
    kiosk112 = pair_kiosk(client, ph, rooms["112"], f"TESTUID{n:04d}B112")
    return {"id": sid, "principal": ph, "teacher": th, "rooms": rooms, "k205": kiosk205, "k112": kiosk112, "n": n}


def pair_kiosk(client, admin_headers, classroom_id, uid) -> dict:
    r = client.post("/api/v1/kiosk/pair/init", json={"device_uid": uid, "firmware_version": "1.0.0"})
    assert r.status_code == 200, r.text
    init = r.json()
    secret = {"X-Pairing-Secret": init["pairing_secret"]}
    assert client.get(f"/api/v1/kiosk/pair/status/{uid}", headers=secret).json()["status"] == "pending"
    r = client.post("/api/v1/kiosks/claim", headers=admin_headers,
                    json={"pairing_code": init["pairing_code"].replace("-", "").lower(), "classroom_id": classroom_id})
    assert r.status_code == 200, r.text
    r = client.get(f"/api/v1/kiosk/pair/status/{uid}", headers=secret)
    body = r.json()
    assert body["status"] == "paired", body
    return {"X-Device-Token": body["device_api_token"], "X-Device-UID": uid, "_uid": uid, "_body": body}


def kh(k: dict) -> dict:
    return {k2: v for k2, v in k.items() if not k2.startswith("_")}
