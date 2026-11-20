"""In-process pub/sub hub that fans out live events to portal WebSocket clients per school."""
from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class RealtimeHub:
    def __init__(self) -> None:
        self._clients: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, school_id: uuid.UUID, ws: WebSocket) -> None:
        async with self._lock:
            self._clients[school_id].add(ws)

    async def disconnect(self, school_id: uuid.UUID, ws: WebSocket) -> None:
        async with self._lock:
            self._clients[school_id].discard(ws)

    async def publish(self, school_id: uuid.UUID, message: dict[str, Any]) -> None:
        payload = json.dumps(message, default=str)
        async with self._lock:
            targets = list(self._clients.get(school_id, ()))
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001 - client went away
                dead.append(ws)
        for ws in dead:
            await self.disconnect(school_id, ws)

    def client_count(self, school_id: uuid.UUID) -> int:
        return len(self._clients.get(school_id, ()))


hub = RealtimeHub()
