"""WebSocket live feed for portals (per-school channel)."""
from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..core.database import get_sessionmaker
from ..core.deps import user_from_access_token
from ..models import Role
from ..services.realtime import hub

router = APIRouter(tags=["realtime"])


@router.websocket("/api/v1/ws/schools/{school_id}")
async def school_feed(ws: WebSocket, school_id: uuid.UUID):
    """Browsers cannot set headers on WebSockets, so the access token is sent as the first message
    ({"token": "..."}) rather than in the URL (keeps tokens out of proxy / access logs)."""
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_text(), timeout=10)
        token = json.loads(first).get("token", "")
        async with get_sessionmaker()() as db:
            user = await user_from_access_token(token, db)
        # Live sign-in/out data is school data: the platform operator is never allowed in.
        if user.role == Role.SUPERSUDO or user.school_id != school_id:
            raise HTTPException(403)
    except (asyncio.TimeoutError, json.JSONDecodeError, HTTPException, WebSocketDisconnect, AttributeError):
        await ws.close(code=4401)
        return

    await hub.connect(school_id, ws)
    await ws.send_text(json.dumps({"type": "hello", "school_id": str(school_id)}))
    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(school_id, ws)
