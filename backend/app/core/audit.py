"""Security audit logging helper."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SecurityAuditLog
from .rate_limit import client_ip


async def audit(
    db: AsyncSession,
    action: str,
    *,
    request: Request | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_device_id: uuid.UUID | None = None,
    school_id: uuid.UUID | None = None,
    target: str | None = None,
    details: dict[str, Any] | None = None,
    commit: bool = False,
) -> None:
    entry = SecurityAuditLog(
        action=action,
        actor_user_id=actor_user_id,
        actor_device_id=actor_device_id,
        school_id=school_id,
        target_resource=target,
        details=details,
        ip_address=client_ip(request) if request else None,
        user_agent=(request.headers.get("user-agent", "")[:300] if request else None),
    )
    db.add(entry)
    if commit:
        await db.commit()
