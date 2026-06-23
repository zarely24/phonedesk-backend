"""Database tables (SQLAlchemy 2.0). Trimmed for the single-organization MVP:
no per-owner accounts — one org (yours) with users (admin + VAs), agents, devices.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


def _short_id() -> str:
    return uuid.uuid4().hex[:10]


def _now() -> datetime:
    # naive UTC — keeps SQLite/Postgres comparisons simple and consistent
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    """A human who logs in: the admin (you) or a VA."""
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    full_name: Mapped[str] = mapped_column(String, default="")
    role: Mapped[str] = mapped_column(String, default="va")       # admin | va
    status: Mapped[str] = mapped_column(String, default="active")  # active | suspended
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Agent(Base):
    """A desktop-app install on an owner's computer. Holds the device token."""
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    label: Mapped[str] = mapped_column(String, default="")
    os: Mapped[str] = mapped_column(String, default="")            # win | mac
    app_version: Mapped[str] = mapped_column(String, default="")
    device_token_hash: Mapped[str] = mapped_column(String, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Device(Base):
    """A registered phone. One token -> one Agent row -> one Device, so a computer running
    many phones pairs each one separately (its own token + phone-home socket). Up to 15
    phones on a single computer is supported this way."""
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    public_id: Mapped[str] = mapped_column(String, unique=True, index=True, default=_short_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    name: Mapped[str] = mapped_column(String, default="New phone")
    brand: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    android_version: Mapped[str] = mapped_column(String, default="")
    serial: Mapped[str] = mapped_column(String, default="")
    # Battery charge limiting (keeps the phone plugged in 24/7 without swelling the cell):
    # the agent stops charging at charge_stop% and resumes at charge_resume%, keeping the
    # USB-C data/control link alive throughout. Defaults: stop 80, resume 25.
    charge_limit_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    charge_stop: Mapped[int] = mapped_column(Integer, default=80)
    charge_resume: Mapped[int] = mapped_column(Integer, default=25)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PairingCode(Base):
    """Short-lived code the admin generates; the agent types it to bind a device."""
    __tablename__ = "pairing_codes"
    code: Mapped[str] = mapped_column(String, primary_key=True)
    created_by: Mapped[str] = mapped_column(String, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class Assignment(Base):
    """Which VA may use which device (admin sees all; VAs see only assigned)."""
    __tablename__ = "assignments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    can_control: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
