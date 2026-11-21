"""The platform operator (SUPERSUDO) must never see school records: students, sign-ins, staff, audit logs."""
from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect


@pytest.mark.parametrize("path", [
    "/api/v1/schools/{sid}/classrooms",
    "/api/v1/schools/{sid}/dashboard",
    "/api/v1/schools/{sid}/events",
    "/api/v1/schools/{sid}/out-now",
    "/api/v1/schools/{sid}/roll-call",
    "/api/v1/schools/{sid}/locate?q=ab",
    "/api/v1/students?school_id={sid}",
    "/api/v1/flags?school_id={sid}",
    "/api/v1/audit-logs?school_id={sid}",
    "/api/v1/users?school_id={sid}",
    "/api/v1/kiosks?school_id={sid}",
    "/api/v1/schools/current?school_id={sid}",
])
def test_platform_operator_blocked_from_school_records(client, school, super_headers, path):
    r = client.get(path.format(sid=school["id"]), headers=super_headers)
    assert r.status_code in (403, 404), (path, r.status_code, r.text)


def test_platform_operator_can_see_aggregate_and_billing_only(client, school, super_headers):
    assert client.get("/api/v1/admin/overview", headers=super_headers).status_code == 200
    assert client.get(f"/api/v1/billing/status?school_id={school['id']}", headers=super_headers).status_code == 200
    diag = client.get(f"/api/v1/admin/kiosks?school_id={school['id']}", headers=super_headers)
    assert diag.status_code == 200
    rows = diag.json()
    assert len(rows) == 2
    # diagnostics contain device health only: no student names, no events
    assert all("first_name" not in row and "student" not in str(row).lower() for row in rows)


def test_platform_operator_cannot_open_live_feed(client, school, super_headers):
    with client.websocket_connect(f"/api/v1/ws/schools/{school['id']}") as ws:
        ws.send_text('{"token": "%s"}' % super_headers["Authorization"].split(" ", 1)[1])
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 4401
