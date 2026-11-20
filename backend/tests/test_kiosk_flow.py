"""End-to-end kiosk flows: pairing, OCR scan, confirm, offline replay, lockdown locator."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from make_test_card import make_card_jpeg

from .conftest import kh, pair_kiosk


def scan(client, kiosk, **kw):
    data = make_card_jpeg(size=(640, 480), quality=80, **kw)
    r = client.post("/api/v1/kiosk/scan-card", headers={**kh(kiosk), "Content-Type": "image/jpeg"}, content=data)
    assert r.status_code == 200, r.text
    return r.json()


def confirm(client, kiosk, scan_res, event_type, destination=None, **extra):
    body = {
        "event_type": event_type,
        "destination": destination,
        "first_name": scan_res["first_name"],
        "last_name": scan_res["last_name"],
        "scan_session_id": scan_res["scan_session_id"],
        "client_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    return client.post("/api/v1/kiosk/events", headers=kh(kiosk), json=body)


def test_pairing_payload(client, school):
    body = school["k205"]["_body"]
    assert body["room_number"] == "205"
    assert body["timezone"] == "America/Toronto"
    assert body["posix_tz"].startswith("EST5EDT")
    assert body["destinations"] == ["Washroom", "Office", "Library", "Guidance", "Water", "Other"]
    # token is delivered exactly once
    r = client.get(f"/api/v1/kiosk/pair/status/{school['k205']['_uid']}", headers={"X-Pairing-Secret": "x"})
    assert r.status_code == 401


def test_pair_status_requires_secret(client):
    r = client.post("/api/v1/kiosk/pair/init", json={"device_uid": "STEALTEST0001"})
    assert r.status_code == 200
    assert client.get("/api/v1/kiosk/pair/status/STEALTEST0001").status_code == 401
    assert client.get("/api/v1/kiosk/pair/status/STEALTEST0001", headers={"X-Pairing-Secret": "guess"}).status_code == 401


def test_heartbeat_and_config(client, school):
    r = client.post("/api/v1/kiosk/heartbeat", headers=kh(school["k205"]),
                    json={"firmware_version": "1.0.1", "wifi_rssi": -55, "offline_queue_depth": 2})
    assert r.status_code == 200, r.text
    assert r.json()["room_number"] == "205"
    assert client.get("/api/v1/kiosk/config", headers={"X-Device-Token": "dtk_bogus"}).status_code == 401


def test_scan_and_sign_out_and_in(client, school):
    k = school["k205"]
    res = scan(client, k)
    assert res["detected"] is True
    assert (res["first_name"], res["last_name"]) == ("Jordan", "Taylor")
    assert res["confidence"] >= 0.6
    r = confirm(client, k, res, "SIGN_OUT", "Washroom")
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True

    out = client.get(f"/api/v1/schools/{school['id']}/out-now", headers=school["teacher"]).json()
    assert [o["first_name"] for o in out] == ["Jordan"]
    assert out[0]["destination"] == "Washroom"

    # reusing a scan session is rejected
    r = confirm(client, k, res, "SIGN_IN")
    assert r.status_code == 422

    res2 = scan(client, k)
    r = confirm(client, k, res2, "SIGN_IN")
    assert r.status_code == 200
    assert r.json()["is_lockdown_cross_room"] is False
    assert client.get(f"/api/v1/schools/{school['id']}/out-now", headers=school["teacher"]).json() == []


def test_blank_frame_not_detected(client, school):
    import cv2
    import numpy as np

    blank = cv2.imencode(".jpg", np.full((480, 640, 3), 60, np.uint8))[1].tobytes()
    r = client.post("/api/v1/kiosk/scan-card", headers={**kh(school["k205"]), "Content-Type": "image/jpeg"}, content=blank)
    assert r.status_code == 200
    assert r.json()["detected"] is False


def test_non_image_rejected(client, school):
    r = client.post("/api/v1/kiosk/scan-card", headers={**kh(school["k205"]), "Content-Type": "image/jpeg"},
                    content=b"not an image" * 20)
    assert r.json()["detected"] is False


def test_lockdown_cross_room_locator(client, school):
    """Student from homeroom 205 signs out, then ducks into Room 112 during a lockdown."""
    sid = school["id"]
    r = client.post(f"/api/v1/schools/{sid}/lockdown?active=true", headers=school["teacher"])
    assert r.status_code == 200 and r.json()["lockdown_active"] is True

    res = scan(client, school["k205"], first="Avery", last="Nguyen")
    assert confirm(client, school["k205"], res, "SIGN_OUT", "Library").status_code == 200
    res = scan(client, school["k112"], first="Avery", last="Nguyen")
    r = confirm(client, school["k112"], res, "SIGN_IN")
    assert r.status_code == 200
    assert r.json()["is_lockdown_cross_room"] is True

    found = client.get(f"/api/v1/schools/{sid}/locate", params={"q": "avery ngu"}, headers=school["teacher"]).json()
    assert len(found) == 1
    loc = found[0]
    assert loc["state"] == "IN_ROOM"
    assert loc["current_room_number"] == "112"
    assert loc["current_room_name"] == "Science Lab"
    assert loc["last_event_type"] == "SIGN_IN"
    assert loc["is_cross_room"] is True
    assert [e["event_type"] for e in loc["timeline"]] == ["SIGN_IN", "SIGN_OUT"]

    rc = client.get(f"/api/v1/schools/{sid}/roll-call", headers=school["teacher"]).json()
    room112 = next(r for r in rc["rooms"] if r["room_number"] == "112")
    assert [s["first_name"] for s in room112["students"]] == ["Avery"]
    assert rc["accounted_count"] >= 1

    # teachers cannot end a lockdown, principals can
    assert client.post(f"/api/v1/schools/{sid}/lockdown?active=false", headers=school["teacher"]).status_code == 403
    assert client.post(f"/api/v1/schools/{sid}/lockdown?active=false", headers=school["principal"]).status_code == 200


def test_offline_batch_replay_is_idempotent_and_keeps_timestamps(client, school):
    k = school["k205"]
    t0 = datetime.now(timezone.utc) - timedelta(minutes=40)
    events = [
        {"event_type": "SIGN_IN", "first_name": "Sam", "last_name": "Rivera", "entry_method": "MANUAL",
         "client_timestamp_utc": (t0 + timedelta(minutes=10)).isoformat(), "client_event_id": "evt-b",
         "was_offline_queued": True},
        {"event_type": "SIGN_OUT", "destination": "Water", "first_name": "Sam", "last_name": "Rivera",
         "entry_method": "MANUAL", "client_timestamp_utc": t0.isoformat(), "client_event_id": "evt-a",
         "was_offline_queued": True},
    ]
    r = client.post("/api/v1/kiosk/events/batch", headers=kh(k), json={"events": events})
    assert r.status_code == 200, r.text
    results = r.json()
    assert all(x["accepted"] for x in results)
    assert not any(x["duplicate"] for x in results)
    first_time = datetime.fromisoformat(results[0]["recorded_at_utc"].replace("Z", "+00:00"))
    assert abs((first_time - t0).total_seconds()) < 1  # original timestamp preserved, replayed in order

    again = client.post("/api/v1/kiosk/events/batch", headers=kh(k), json={"events": events}).json()
    assert all(x["duplicate"] for x in again)

    feed = client.get(f"/api/v1/classrooms/{school['rooms']['205']}/events", headers=school["teacher"]).json()
    sam = [e for e in feed if e["student_name"] == "Sam Rivera"]
    assert len(sam) == 2 and all(e["was_offline_queued"] for e in sam)


def test_future_client_time_is_clamped(client, school):
    k = school["k205"]
    future = datetime.now(timezone.utc) + timedelta(days=2)
    r = client.post("/api/v1/kiosk/events", headers=kh(k), json={
        "event_type": "SIGN_IN", "first_name": "Clock", "last_name": "Skew", "entry_method": "MANUAL",
        "client_timestamp_utc": future.isoformat(), "was_offline_queued": True, "client_event_id": "skew-1"})
    assert r.status_code == 200
    rec = datetime.fromisoformat(r.json()["recorded_at_utc"].replace("Z", "+00:00"))
    assert rec < datetime.now(timezone.utc) + timedelta(minutes=1)


def test_card_event_requires_scan_session_when_online(client, school):
    r = client.post("/api/v1/kiosk/events", headers=kh(school["k205"]),
                    json={"event_type": "SIGN_IN", "first_name": "No", "last_name": "Scan"})
    assert r.status_code == 422


def test_revoked_kiosk_is_locked_out(client, school):
    k = pair_kiosk(client, school["principal"], school["rooms"]["112"], f"REVOKE{school['n']:04d}XX")
    devices = client.get("/api/v1/kiosks", headers=school["principal"]).json()
    dev = next(d for d in devices if d["device_uid"] == k["_uid"])
    assert client.post(f"/api/v1/kiosks/{dev['id']}/revoke", headers=school["principal"]).status_code == 200
    assert client.get("/api/v1/kiosk/config", headers=kh(k)).status_code == 401


def test_kiosk_pin(client, school):
    sid = school["id"]
    assert client.patch(f"/api/v1/schools/{sid}", headers=school["principal"], json={"kiosk_admin_pin": "4321"}).status_code == 200
    assert client.post("/api/v1/kiosk/verify-pin", headers=kh(school["k205"]), json={"pin": "0000"}).status_code == 403
    assert client.post("/api/v1/kiosk/verify-pin", headers=kh(school["k205"]), json={"pin": "4321"}).status_code == 200


def test_destinations_configurable(client, school):
    sid = school["id"]
    r = client.patch(f"/api/v1/schools/{sid}", headers=school["principal"],
                     json={"kiosk_destinations_json": ["Washroom", "Nurse", "Office"]})
    assert r.status_code == 200
    cfg = client.get("/api/v1/kiosk/config", headers=kh(school["k205"])).json()
    assert cfg["destinations"] == ["Washroom", "Nurse", "Office"]
    bad = client.patch(f"/api/v1/schools/{sid}", headers=school["principal"],
                       json={"kiosk_destinations_json": ["a", "b", "c", "d", "e", "f", "g"]})
    assert bad.status_code == 422
