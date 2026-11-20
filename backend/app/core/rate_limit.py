"""In-process sliding-window rate limiter.

Adequate for a single Mac Mini process. For multi-worker / multi-host deployments,
swap the backend for Redis (same interface) — see docs/SECURITY.md.
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock

from fastapi import HTTPException, Request, status

from .config import get_settings


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def hit(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._hits) > 50_000:  # crude memory guard
                self._hits = {k: v for k, v in self._hits.items() if v}
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        for header in ("cf-connecting-ip", "x-real-ip"):
            if v := request.headers.get(header):
                return v.strip()
        if xff := request.headers.get("x-forwarded-for"):
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce(request: Request, bucket: str, limit: int, key_suffix: str | None = None) -> None:
    key = f"{bucket}:{key_suffix or client_ip(request)}"
    if not limiter.hit(key, limit):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests, slow down", headers={"Retry-After": "60"})
