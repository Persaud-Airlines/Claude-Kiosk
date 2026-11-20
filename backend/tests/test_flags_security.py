"""Flag engine + exemptions, RBAC / tenant isolation, auth hardening, roster import, Stripe webhooks."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

from .conftest import PRINCIPAL_PW, kh, login


def manual(client, kiosk, etype, first, last, dest=None):
    r = client.post("/api/v1/kiosk/events", headers=kh(kiosk), json={
        "event_type": etype, "destination": dest, "first_name": first, "last_name": last,
        "entry_method": "MANUAL", "client_event_id": uuid.uuid4().hex, "was_offline_queued": True})
    assert r.status_code == 200, r.text
    return r.json()


def flags_for(client, headers, school_id, name, include_suppressed=True):
    fl = client.get("/api/v1/flags", headers=headers,
                    params={"school_id": school_id, "include_suppressed": include_suppressed}).json()
    return [f for f in fl if f["student_name"] == name]


def test_excessive_frequency_flag(client, school):
    for _ in range(4):
        manual(client, school["k205"], "SIGN_OUT", "Riley", "Frequent", "Washroom")
        manual(client, school["k205"], "SIGN_IN", "Riley", "Frequent")
    fl = flags_for(client, school["teacher"], school["id"], "Riley Frequent")
    assert len(fl) == 1
    assert fl[0]["flag_type"] == "EXCESSIVE_FREQUENCY"
    assert fl[0]["status"] == "OPEN"
    assert "4 times today (threshold: 3)" in fl[0]["trigger_details"]
    r = client.patch(f"/api/v1/flags/{fl[0]['id']}", headers=school["teacher"], json={"status": "ACKNOWLEDGED"})
    assert r.status_code == 200 and r.json()["status"] == "ACKNOWLEDGED"


def test_medical_exemption_suppresses_flag_and_redacts_for_teachers(client, school):
    ph, th = school["principal"], school["teacher"]
    manual(client, school["k205"], "SIGN_OUT", "Morgan", "Medical", "Washroom")
    st = client.get("/api/v1/students", headers=th, params={"q": "morgan"}).json()[0]
    r = client.post("/api/v1/exemptions", headers=ph, json={
        "student_id": st["id"], "reason_category": "Medical Accommodation",
        "reason_notes": "Approved medical accommodation: frequent washroom access required",
        "applies_to_destinations": ["Washroom"]})
    assert r.status_code == 201, r.text
    for _ in range(4):
        manual(client, school["k205"], "SIGN_IN", "Morgan", "Medical")
        manual(client, school["k205"], "SIGN_OUT", "Morgan", "Medical", "Washroom")
    fl = flags_for(client, ph, school["id"], "Morgan Medical")
    assert fl and all(f["status"] == "SUPPRESSED_BY_EXEMPTION" and f["is_suppressed_by_exemption"] for f in fl)
    assert flags_for(client, th, school["id"], "Morgan Medical", include_suppressed=False) == []

    # Non-exempt destination still counts toward a real flag
    for _ in range(4):
        manual(client, school["k205"], "SIGN_IN", "Morgan", "Medical")
        manual(client, school["k205"], "SIGN_OUT", "Morgan", "Medical", "Library")

    fl = flags_for(client, th, school["id"], "Morgan Medical", include_suppressed=False)
    assert any(f["status"] == "OPEN" and f["flag_type"] == "EXCESSIVE_FREQUENCY" for f in fl)

    teacher_view = client.get(f"/api/v1/students/{st['id']}/exemptions", headers=th).json()
    assert teacher_view[0]["redacted"] is True
    assert teacher_view[0]["reason_notes"] is None and teacher_view[0]["reason_category"] is None
    admin_view = client.get(f"/api/v1/students/{st['id']}/exemptions", headers=ph).json()
    assert admin_view[0]["reason_notes"].startswith("Approved medical")
    students = client.get("/api/v1/students", headers=th, params={"q": "morgan"}).json()
    assert students[0]["has_accommodation"] is True
    logs = client.get("/api/v1/audit-logs", headers=ph, params={"action": "VIEW_STUDENT_EXEMPTION"}).json()
    assert len(logs) >= 1


def test_exemption_notes_encrypted_at_rest(client, school):
    import asyncio

    from sqlalchemy import text

    from app.core.database import get_sessionmaker

    st = client.post("/api/v1/students", headers=school["principal"],
                     json={"first_name": "Secret", "last_name": "Notes"}).json()
    client.post("/api/v1/exemptions", headers=school["principal"], json={
        "student_id": st["id"], "reason_category": "IEP / Special Education", "reason_notes": "Very private detail"})

    async def raw():
        async with get_sessionmaker()() as db:
            return (await db.execute(text("SELECT reason_notes FROM student_flag_exemptions"))).scalars().all()

    values = asyncio.run(raw())
    assert values and all("Very private detail" not in (v or "") for v in values)


def test_extended_duration_flag(client, school):
    import asyncio
    from datetime import datetime, timedelta, timezone

    from app.services.flagging import run_scan_once

    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    r = client.post("/api/v1/kiosk/events", headers=kh(school["k205"]), json={
        "event_type": "SIGN_OUT", "destination": "Office", "first_name": "Dana", "last_name": "Overdue",
        "entry_method": "MANUAL", "client_timestamp_utc": old, "was_offline_queued": True, "client_event_id": "od-1"})
    assert r.status_code == 200
    out = client.get(f"/api/v1/schools/{school['id']}/out-now", headers=school["teacher"]).json()
    assert any(o["first_name"] == "Dana" and o["overdue"] for o in out)
    asyncio.run(run_scan_once())
    fl = flags_for(client, school["teacher"], school["id"], "Dana Overdue")
    assert [f["flag_type"] for f in fl] == ["EXTENDED_DURATION"]


def test_tenant_isolation(client, school, super_headers):
    other = client.post("/api/v1/admin/schools", headers=super_headers,
                        json={"name": f"Other School {uuid.uuid4().hex[:6]}"}).json()
    th = school["teacher"]
    assert client.get(f"/api/v1/schools/{other['id']}/classrooms", headers=th).status_code == 404
    assert client.get(f"/api/v1/schools/{other['id']}/locate", headers=th, params={"q": "ab"}).status_code == 404
    assert client.get("/api/v1/students", headers=th, params={"school_id": other["id"]}).status_code == 403
    assert client.get("/api/v1/admin/overview", headers=th).status_code == 403
    assert client.get("/api/v1/admin/overview", headers=school["principal"]).status_code == 403
    assert client.post("/api/v1/users", headers=th, json={"email": "x@y.test", "full_name": "X", "role": "TEACHER",
                                                          "password": "Abcdefgh123!"}).status_code == 403
    assert client.post("/api/v1/users", headers=school["principal"], json={
        "email": "evil@y.test", "full_name": "X", "role": "SUPERSUDO", "password": "Abcdefgh123!"}).status_code == 403


def test_auth_hardening(client, school):
    email = f"principal{school['n']}@school.test"
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PRINCIPAL_PW})
    assert r.status_code == 423  # locked out

    # weak passwords refused
    r = client.post("/api/v1/users", headers=school["principal"],
                    json={"email": f"weak{school['n']}@t.test", "full_name": "W", "role": "TEACHER", "password": "aaaaaaaaaaaa"})
    assert r.status_code == 422


def test_mfa_flow(client, super_headers):
    import pyotp

    email = f"mfa{uuid.uuid4().hex[:6]}@t.test"
    pw = "Mfa-User-Pass-1!"
    sch = client.post("/api/v1/admin/schools", headers=super_headers, json={
        "name": f"MFA School {uuid.uuid4().hex[:5]}", "principal_email": email, "principal_name": "M F A",
        "principal_password": pw}).json()
    assert sch["id"]
    h = login(client, email, pw)
    secret = client.post("/api/v1/auth/mfa/enroll", headers=h).json()["secret"]
    assert client.post("/api/v1/auth/mfa/confirm", headers=h, json={"code": pyotp.TOTP(secret).now()}).status_code == 204
    r = client.post("/api/v1/auth/login", json={"email": email, "password": pw}).json()
    assert r["mfa_required"] and r["access_token"] is None
    bad = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": r["mfa_token"], "code": "000000"})
    assert bad.status_code == 401
    ok = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": r["mfa_token"], "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200 and ok.json()["access_token"]


def test_refresh_and_logout_all(client, school):
    email = f"teacher{school['n']}@school.test"
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "Teacher-Pass-123!"})
    assert "dt_refresh" in r.cookies or client.cookies.get("dt_refresh")
    access = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.post("/api/v1/auth/refresh").status_code == 200
    assert client.post("/api/v1/auth/logout-all", headers=access).status_code == 204
    assert client.get("/api/v1/auth/me", headers=access).status_code == 401


def test_roster_import_and_fuzzy_match(client, school):
    csv_data = "first_name,last_name,student_number,homeroom,grade\nJordan,Taylor,300123456,205,11\nPriya,Shah,300999111,112,10\n,Missing,1,,\n"
    r = client.post("/api/v1/students/import", headers=school["principal"],
                    files={"file": ("roster.csv", csv_data, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["created"] >= 1 and r.json()["skipped"] == 1


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"


def _stripe_sig(payload: str, secret: str = "whsec_test_secret") -> str:
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def test_stripe_webhook_updates_status_without_blocking_kiosks(client, school):
    sid = school["id"]
    evt = {"id": f"evt_{uuid.uuid4().hex}", "object": "event", "type": "checkout.session.completed",
           "data": {"object": {"id": "cs_1", "object": "checkout.session", "customer": "cus_123",
                               "subscription": "sub_123", "client_reference_id": sid,
                               "metadata": {"school_id": sid}, "payment_status": "paid"}}}
    payload = json.dumps(evt)
    assert client.post("/api/v1/billing/webhook", content=payload, headers={"Stripe-Signature": "t=1,v1=bad"}).status_code == 400
    r = client.post("/api/v1/billing/webhook", content=payload, headers={"Stripe-Signature": _stripe_sig(payload)})
    assert r.status_code == 200, r.text
    st = client.get("/api/v1/billing/status", headers=school["principal"]).json()
    assert st["subscription_status"] == "active" and st["banner"] is False
    dup = client.post("/api/v1/billing/webhook", content=payload, headers={"Stripe-Signature": _stripe_sig(payload)})
    assert dup.json().get("duplicate") is True

    fail = {"id": f"evt_{uuid.uuid4().hex}", "object": "event", "type": "invoice.payment_failed",
            "data": {"object": {"id": "in_1", "object": "invoice", "customer": "cus_123", "subscription": "sub_123"}}}
    p2 = json.dumps(fail)
    client.post("/api/v1/billing/webhook", content=p2, headers={"Stripe-Signature": _stripe_sig(p2)})
    st = client.get("/api/v1/billing/status", headers=school["principal"]).json()
    assert st["subscription_status"] == "past_due" and st["banner"] is True

    # Safety-first grace policy: kiosks and locator keep working while past_due
    manual(client, school["k205"], "SIGN_IN", "Grace", "Policy")
    assert client.get(f"/api/v1/schools/{sid}/locate", params={"q": "grace"}, headers=school["teacher"]).json()

    deleted = {"id": f"evt_{uuid.uuid4().hex}", "object": "event", "type": "customer.subscription.deleted",
               "data": {"object": {"id": "sub_123", "object": "subscription", "customer": "cus_123", "status": "canceled",
                                   "metadata": {"school_id": sid}}}}
    p3 = json.dumps(deleted)
    client.post("/api/v1/billing/webhook", content=p3, headers={"Stripe-Signature": _stripe_sig(p3)})
    assert client.get("/api/v1/billing/status", headers=school["principal"]).json()["subscription_status"] == "canceled"


def test_supersudo_overview(client, school, super_headers):
    ov = client.get("/api/v1/admin/overview", headers=super_headers).json()
    assert ov["schools_total"] >= 1
    assert any(s["id"] == school["id"] and s["kiosks_total"] == 2 for s in ov["schools"])


def test_posix_tz():
    from app.services.timeutil import posix_tz_for

    assert posix_tz_for("America/Toronto") == "EST5EDT,M3.2.0,M11.1.0"
    assert posix_tz_for("America/Regina") == "CST6"


def test_student_number_requires_matching_name(client, school):
    """A card whose number belongs to someone else (OCR misread) must resolve by name, not number."""
    ph = school["principal"]
    client.post("/api/v1/students", headers=ph, json={"first_name": "Number", "last_name": "Owner", "student_number": "555000111"})
    import asyncio

    from app.core.database import get_sessionmaker
    from app.services.students import find_student

    async def run():
        async with get_sessionmaker()() as db:
            import uuid as _u
            return await find_student(db, _u.UUID(school["id"]), "Someone", "Else", "555000111")

    assert asyncio.run(run()) is None
