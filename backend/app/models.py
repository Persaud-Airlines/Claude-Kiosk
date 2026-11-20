"""SQLAlchemy ORM models — normalized, auditable schema."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .core.database import Base
from .core.security import decrypt_str, encrypt_str, utcnow

DEFAULT_DESTINATIONS = ["Washroom", "Office", "Library", "Guidance", "Water", "Other"]


class EncryptedText(TypeDecorator):
    """Transparently Fernet-encrypts a text column at rest."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_str(value)

    def process_result_value(self, value, dialect):
        return decrypt_str(value)


class TZDateTime(TypeDecorator):
    """Timezone-aware UTC datetime on every backend (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            raise ValueError("naive datetime is not allowed; use UTC-aware datetimes")
        return value

    def process_result_value(self, value, dialect):
        from .core.security import as_utc

        return as_utc(value)


class Role(str, enum.Enum):
    SUPERSUDO = "SUPERSUDO"
    PRINCIPAL = "PRINCIPAL"
    SCHOOL_ADMIN = "SCHOOL_ADMIN"
    TEACHER = "TEACHER"


class SubscriptionStatus(str, enum.Enum):
    none = "none"
    trialing = "trialing"
    active = "active"
    past_due = "past_due"
    canceled = "canceled"
    unpaid = "unpaid"
    incomplete = "incomplete"


class PairingStatus(str, enum.Enum):
    unpaired = "unpaired"
    paired = "paired"
    revoked = "revoked"


class EventType(str, enum.Enum):
    SIGN_OUT = "SIGN_OUT"
    SIGN_IN = "SIGN_IN"


class EntryMethod(str, enum.Enum):
    CARD_OCR = "CARD_OCR"
    MANUAL = "MANUAL"
    STAFF = "STAFF"


class ExemptionCategory(str, enum.Enum):
    MEDICAL = "Medical Accommodation"
    IEP = "IEP / Special Education"
    ADMIN_PASS = "Administrative Pass"
    COUNSELING = "Counseling / Guidance"
    OTHER = "Other"


class FlagType(str, enum.Enum):
    EXCESSIVE_FREQUENCY = "EXCESSIVE_FREQUENCY"
    EXTENDED_DURATION = "EXTENDED_DURATION"
    UNRETURNED_SESSION = "UNRETURNED_SESSION"


class FlagStatus(str, enum.Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    SUPPRESSED_BY_EXEMPTION = "SUPPRESSED_BY_EXEMPTION"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x], native_enum=False, length=40)


class OrganizationBoard(Base):
    __tablename__ = "organizations_boards"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    schools: Mapped[list[School]] = relationship(back_populates="board")


class School(Base):
    __tablename__ = "schools"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    board_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations_boards.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(400))
    timezone: Mapped[str] = mapped_column(String(64), default="America/Toronto")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), index=True)
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        _enum(SubscriptionStatus, "subscription_status"), default=SubscriptionStatus.none
    )
    subscription_current_period_end: Mapped[datetime | None] = mapped_column(TZDateTime)
    kiosk_destinations_json: Mapped[list[str]] = mapped_column(JSON, default=lambda: list(DEFAULT_DESTINATIONS))
    flag_threshold_count: Mapped[int] = mapped_column(Integer, default=3)  # sign-outs per day
    flag_threshold_weekly_count: Mapped[int] = mapped_column(Integer, default=8)  # sign-outs per week
    flag_duration_minutes: Mapped[int] = mapped_column(Integer, default=15)
    kiosk_admin_pin_hash: Mapped[str | None] = mapped_column(String(200))
    lockdown_active: Mapped[bool] = mapped_column(Boolean, default=False)
    lockdown_started_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    board: Mapped[OrganizationBoard | None] = relationship(back_populates="schools")
    classrooms: Mapped[list[Classroom]] = relationship(back_populates="school", cascade="all, delete-orphan")


class Classroom(Base):
    __tablename__ = "classrooms"
    __table_args__ = (UniqueConstraint("school_id", "room_number", name="uq_classroom_room"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), index=True)
    room_number: Mapped[str] = mapped_column(String(40))
    room_name: Mapped[str | None] = mapped_column(String(200))
    assigned_teacher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    school: Mapped[School] = relationship(back_populates="classrooms")


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"))
    school_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), index=True)
    mfa_secret: Mapped[str | None] = mapped_column(EncryptedText)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class KioskDevice(Base):
    __tablename__ = "kiosk_devices"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    device_uid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    school_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("schools.id", ondelete="SET NULL"), index=True)
    classroom_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("classrooms.id", ondelete="SET NULL"))
    pairing_code: Mapped[str | None] = mapped_column(String(9), index=True)
    pairing_code_expires_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    pairing_status: Mapped[PairingStatus] = mapped_column(
        _enum(PairingStatus, "pairing_status"), default=PairingStatus.unpaired
    )
    pairing_secret_hash: Mapped[str | None] = mapped_column(String(64))
    # One-time delivery of the plaintext token to the polling kiosk; cleared once delivered.
    pending_token_encrypted: Mapped[str | None] = mapped_column(EncryptedText)
    api_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    firmware_version: Mapped[str | None] = mapped_column(String(32))
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    wifi_rssi: Mapped[int | None] = mapped_column(Integer)
    offline_queue_depth: Mapped[int] = mapped_column(Integer, default=0)
    paired_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    paired_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    classroom: Mapped[Classroom | None] = relationship()
    school: Mapped[School | None] = relationship()


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        Index("ix_students_school_name", "school_id", "normalized_name"),
        UniqueConstraint("school_id", "student_number", name="uq_student_number"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), index=True)
    student_number: Mapped[str | None] = mapped_column(String(40))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    normalized_name: Mapped[str] = mapped_column(String(220))
    homeroom_classroom_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("classrooms.id", ondelete="SET NULL"))
    grade: Mapped[str | None] = mapped_column(String(20))
    auto_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    homeroom: Mapped[Classroom | None] = relationship()


class CardScanSession(Base):
    """Result of an OCR pass. The image itself is never persisted (data minimization)."""

    __tablename__ = "card_scan_sessions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kiosk_device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kiosk_devices.id", ondelete="CASCADE"), index=True)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    student_number: Mapped[str | None] = mapped_column(String(40))
    matched_student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("students.id", ondelete="SET NULL"))
    confidence: Mapped[float] = mapped_column(Float)
    engine: Mapped[str] = mapped_column(String(32))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class HallPassEvent(Base):
    """Immutable audit log of every sign-in / sign-out (no UPDATE/DELETE API is exposed)."""

    __tablename__ = "hall_pass_events"
    __table_args__ = (
        Index("ix_events_school_time", "school_id", "occurred_at_utc"),
        Index("ix_events_student_time", "student_id", "occurred_at_utc"),
        Index("ix_events_classroom_time", "classroom_id", "occurred_at_utc"),
        UniqueConstraint("kiosk_device_id", "client_event_id", name="uq_event_client_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"))
    classroom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"))
    kiosk_device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kiosk_devices.id", ondelete="SET NULL"))
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    scan_session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    client_event_id: Mapped[str | None] = mapped_column(String(64))  # idempotency key for offline replay
    scanned_first_name: Mapped[str] = mapped_column(String(100))
    scanned_last_name: Mapped[str] = mapped_column(String(100))
    event_type: Mapped[EventType] = mapped_column(_enum(EventType, "event_type"))
    destination: Mapped[str | None] = mapped_column(String(60))
    entry_method: Mapped[EntryMethod] = mapped_column(_enum(EntryMethod, "entry_method"), default=EntryMethod.CARD_OCR)
    recorded_at_utc: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    client_timestamp_utc: Mapped[datetime | None] = mapped_column(TZDateTime)
    # Validated time the student actually acted (kiosk NTP clock for offline replays, else server time)
    occurred_at_utc: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    was_offline_queued: Mapped[bool] = mapped_column(Boolean, default=False)
    is_lockdown_cross_room: Mapped[bool] = mapped_column(Boolean, default=False)
    during_lockdown: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(String(500))

    student: Mapped[Student] = relationship()
    classroom: Mapped[Classroom] = relationship()



class StudentFlagExemption(Base):
    __tablename__ = "student_flag_exemptions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason_category: Mapped[ExemptionCategory] = mapped_column(_enum(ExemptionCategory, "exemption_category"))
    reason_notes: Mapped[str | None] = mapped_column(EncryptedText)
    applies_to_destinations: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["ALL"])
    valid_from: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(TZDateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class StudentFlag(Base):
    __tablename__ = "student_flags"
    __table_args__ = (Index("ix_flags_school_status", "school_id", "status"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"))
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    flag_type: Mapped[FlagType] = mapped_column(_enum(FlagType, "flag_type"))
    trigger_details: Mapped[str] = mapped_column(String(500))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    related_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hall_pass_events.id", ondelete="SET NULL"))
    is_suppressed_by_exemption: Mapped[bool] = mapped_column(Boolean, default=False)
    exemption_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("student_flag_exemptions.id", ondelete="SET NULL")
    )
    status: Mapped[FlagStatus] = mapped_column(_enum(FlagStatus, "flag_status"), default=FlagStatus.OPEN)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    student: Mapped[Student] = relationship()


class SecurityAuditLog(Base):
    __tablename__ = "security_audit_logs"
    __table_args__ = (Index("ix_audit_school_time", "school_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kiosk_devices.id", ondelete="SET NULL"))
    school_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("schools.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_resource: Mapped[str | None] = mapped_column(String(300))
    details: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class StripeWebhookEvent(Base):
    """Idempotency ledger for Stripe webhook deliveries."""

    __tablename__ = "stripe_webhook_events"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80))
    received_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
