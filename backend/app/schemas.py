"""Pydantic request / response schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from .models import (
    EntryMethod,
    EventType,
    ExemptionCategory,
    FlagStatus,
    FlagType,
    PairingStatus,
    Role,
    SubscriptionStatus,
)

NAME_FIELD = Field(min_length=1, max_length=100)
_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


def _email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 320 or not _EMAIL_RE.match(v):
        raise ValueError("Invalid email address")
    return v


# Permits on-prem domains such as admin@detechtive.local (pydantic's EmailStr rejects special-use TLDs)
EmailStr = Annotated[str, AfterValidator(_email)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=8)


class TokenResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int = 0
    mfa_required: bool = False
    mfa_token: str | None = None
    user: UserOut | None = None


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    school_id: uuid.UUID | None
    mfa_enabled: bool
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: Role
    password: str = Field(min_length=12, max_length=256)
    school_id: uuid.UUID | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class MfaEnrollResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MfaConfirm(BaseModel):
    code: str


# ---------------------------------------------------------------------------- schools / rooms
class SchoolOut(ORM):
    id: uuid.UUID
    board_id: uuid.UUID | None
    name: str
    address: str | None
    timezone: str
    subscription_status: SubscriptionStatus
    subscription_current_period_end: datetime | None
    kiosk_destinations_json: list[str]
    flag_threshold_count: int
    flag_threshold_weekly_count: int
    flag_duration_minutes: int
    lockdown_active: bool
    lockdown_started_at: datetime | None
    created_at: datetime


class SchoolCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    address: str | None = Field(default=None, max_length=400)
    timezone: str = "America/Toronto"
    board_id: uuid.UUID | None = None
    board_name: str | None = Field(default=None, max_length=200)
    principal_email: EmailStr | None = None
    principal_name: str | None = None
    principal_password: str | None = Field(default=None, min_length=12, max_length=256)


class SchoolSettingsUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    address: str | None = Field(default=None, max_length=400)
    timezone: str | None = None
    kiosk_destinations_json: list[str] | None = None
    flag_threshold_count: int | None = Field(default=None, ge=0, le=50)
    flag_threshold_weekly_count: int | None = Field(default=None, ge=0, le=200)
    flag_duration_minutes: int | None = Field(default=None, ge=1, le=240)
    kiosk_admin_pin: str | None = Field(default=None, pattern=r"^\d{4,8}$")

    @field_validator("kiosk_destinations_json")
    @classmethod
    def _dest(cls, v: list[str] | None):
        if v is None:
            return v
        cleaned = [d.strip()[:24] for d in v if d and d.strip()]
        if not 1 <= len(cleaned) <= 6:
            raise ValueError("Between 1 and 6 destinations are required")
        if len({d.lower() for d in cleaned}) != len(cleaned):
            raise ValueError("Destinations must be unique")
        return cleaned


class ClassroomCreate(BaseModel):
    room_number: str = Field(min_length=1, max_length=40)
    room_name: str | None = Field(default=None, max_length=200)
    assigned_teacher_id: uuid.UUID | None = None


class ClassroomUpdate(BaseModel):
    room_number: str | None = Field(default=None, min_length=1, max_length=40)
    room_name: str | None = Field(default=None, max_length=200)
    assigned_teacher_id: uuid.UUID | None = None


class ClassroomOut(ORM):
    id: uuid.UUID
    school_id: uuid.UUID
    room_number: str
    room_name: str | None
    assigned_teacher_id: uuid.UUID | None
    created_at: datetime
    out_count: int = 0
    kiosk_online: bool | None = None


# ----------------------------------------------------------------------------------- kiosk
class PairInitRequest(BaseModel):
    device_uid: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-:]+$")
    firmware_version: str | None = Field(default=None, max_length=32)
    locale: str | None = Field(default=None, max_length=8)


class PairInitResponse(BaseModel):
    pairing_code: str
    pairing_secret: str
    expires_at: datetime
    expires_in_seconds: int
    pairing_url: str
    poll_interval_seconds: int = 2


class PairStatusResponse(BaseModel):
    status: str  # pending | paired | expired | revoked
    device_api_token: str | None = None
    school_name: str | None = None
    school_id: uuid.UUID | None = None
    room_number: str | None = None
    room_name: str | None = None
    classroom_id: uuid.UUID | None = None
    timezone: str | None = None
    posix_tz: str | None = None
    destinations: list[str] | None = None


class PairClaimRequest(BaseModel):
    pairing_code: str = Field(min_length=8, max_length=12)
    device_uid: str | None = None
    school_id: uuid.UUID | None = None
    classroom_id: uuid.UUID | None = None
    new_room_number: str | None = Field(default=None, max_length=40)
    new_room_name: str | None = Field(default=None, max_length=200)


class HeartbeatRequest(BaseModel):
    firmware_version: str | None = Field(default=None, max_length=32)
    ip_address: str | None = Field(default=None, max_length=64)
    wifi_rssi: int | None = Field(default=None, ge=-127, le=0)
    offline_queue_depth: int = Field(default=0, ge=0, le=100000)


class KioskConfig(BaseModel):
    school_name: str
    room_number: str
    room_name: str | None
    timezone: str
    posix_tz: str
    destinations: list[str]
    lockdown_active: bool
    server_time_utc: datetime
    paired: bool = True


class PinVerifyRequest(BaseModel):
    pin: str = Field(pattern=r"^\d{4,8}$")


class ScanResponse(BaseModel):
    detected: bool
    first_name: str | None = None
    last_name: str | None = None
    student_number: str | None = None
    confidence: float = 0.0
    scan_session_id: uuid.UUID | None = None
    card_found: bool = False
    reason: str | None = None
    roster_match: bool = False


class KioskEventIn(BaseModel):
    event_type: EventType
    destination: str | None = Field(default=None, max_length=60)
    first_name: str = NAME_FIELD
    last_name: str = NAME_FIELD
    scan_session_id: uuid.UUID | None = None
    client_timestamp_utc: datetime | None = None
    client_event_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    was_offline_queued: bool = False
    entry_method: EntryMethod = EntryMethod.CARD_OCR
    device_uid: str | None = None
    room_id: uuid.UUID | None = None


class KioskEventResult(BaseModel):
    accepted: bool
    event_id: uuid.UUID | None = None
    duplicate: bool = False
    recorded_at_utc: datetime | None = None
    local_time: str | None = None
    is_lockdown_cross_room: bool = False
    error: str | None = None


class KioskBatchIn(BaseModel):
    events: list[KioskEventIn] = Field(max_length=200)


class KioskDeviceOut(ORM):
    id: uuid.UUID
    device_uid: str
    school_id: uuid.UUID | None
    classroom_id: uuid.UUID | None
    pairing_status: PairingStatus
    firmware_version: str | None
    last_seen_at: datetime | None
    ip_address: str | None
    wifi_rssi: int | None
    offline_queue_depth: int
    paired_at: datetime | None
    online: bool = False
    room_number: str | None = None


class KioskReassign(BaseModel):
    classroom_id: uuid.UUID


# ---------------------------------------------------------------------------------- events
class EventOut(ORM):
    id: uuid.UUID
    school_id: uuid.UUID
    classroom_id: uuid.UUID
    student_id: uuid.UUID
    scanned_first_name: str
    scanned_last_name: str
    event_type: EventType
    destination: str | None
    entry_method: EntryMethod
    recorded_at_utc: datetime
    client_timestamp_utc: datetime | None
    occurred_at_utc: datetime
    was_offline_queued: bool
    is_lockdown_cross_room: bool
    during_lockdown: bool
    notes: str | None
    room_number: str | None = None
    student_name: str | None = None


class StaffEventIn(BaseModel):
    student_id: uuid.UUID
    classroom_id: uuid.UUID
    event_type: EventType
    destination: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=500)


class OutNowItem(BaseModel):
    event_id: uuid.UUID
    student_id: uuid.UUID
    first_name: str
    last_name: str
    destination: str | None
    classroom_id: uuid.UUID
    room_number: str | None
    signed_out_at_utc: datetime
    minutes_out: int
    overdue: bool
    has_accommodation: bool


# --------------------------------------------------------------------------------- students
class StudentOut(ORM):
    id: uuid.UUID
    school_id: uuid.UUID
    student_number: str | None
    first_name: str
    last_name: str
    homeroom_classroom_id: uuid.UUID | None
    grade: str | None
    auto_registered: bool
    is_active: bool
    created_at: datetime
    has_accommodation: bool = False


class StudentCreate(BaseModel):
    first_name: str = NAME_FIELD
    last_name: str = NAME_FIELD
    student_number: str | None = Field(default=None, max_length=40)
    homeroom_classroom_id: uuid.UUID | None = None
    grade: str | None = Field(default=None, max_length=20)


class StudentUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    student_number: str | None = Field(default=None, max_length=40)
    homeroom_classroom_id: uuid.UUID | None = None
    grade: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None


class RosterImportResult(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[str]


class LocateResult(BaseModel):
    student: StudentOut
    state: str  # IN_ROOM | OUT | NO_ACTIVITY
    current_room_number: str | None
    current_room_name: str | None
    current_classroom_id: uuid.UUID | None
    destination: str | None
    last_event_type: EventType | None
    last_event_at_utc: datetime | None
    last_event_local: str | None
    homeroom_number: str | None
    is_cross_room: bool
    timeline: list[EventOut]


# ------------------------------------------------------------------------ exemptions / flags
class ExemptionCreate(BaseModel):
    student_id: uuid.UUID
    reason_category: ExemptionCategory
    reason_notes: str | None = Field(default=None, max_length=2000)
    applies_to_destinations: list[str] = Field(default_factory=lambda: ["ALL"], min_length=1, max_length=7)
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class ExemptionUpdate(BaseModel):
    is_active: bool | None = None
    valid_until: datetime | None = None
    reason_notes: str | None = Field(default=None, max_length=2000)
    applies_to_destinations: list[str] | None = None


class ExemptionOut(BaseModel):
    """Redacted unless the viewer holds an admin role (category + notes are health information)."""

    id: uuid.UUID
    student_id: uuid.UUID
    applies_to_destinations: list[str]
    valid_from: datetime
    valid_until: datetime | None
    is_active: bool
    created_at: datetime
    redacted: bool
    reason_category: ExemptionCategory | None = None
    reason_notes: str | None = None
    created_by_user_id: uuid.UUID | None = None


class FlagOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    flag_type: FlagType
    trigger_details: str
    is_suppressed_by_exemption: bool
    status: FlagStatus
    reviewed_by_user_id: uuid.UUID | None
    reviewed_at: datetime | None
    created_at: datetime


class FlagUpdate(BaseModel):
    status: FlagStatus


# ----------------------------------------------------------------------------------- billing
class CheckoutRequest(BaseModel):
    school_id: uuid.UUID | None = None


class UrlResponse(BaseModel):
    url: str


class AuditOut(ORM):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_device_id: uuid.UUID | None
    school_id: uuid.UUID | None
    action: str
    target_resource: str | None
    details: dict | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


TokenResponse.model_rebuild()
