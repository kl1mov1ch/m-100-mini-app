from typing import ClassVar

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    __table_args__: ClassVar[dict] = {"schema": "registry"}
    version = mapped_column(Integer, primary_key=True)


class User(Base):
    __tablename__ = "users"
    __table_args__: ClassVar[dict] = {"schema": "registry"}
    telegram_id = mapped_column(Text, primary_key=True)
    name = mapped_column(Text, nullable=False)
    role = mapped_column(Text, nullable=False)
    enabled = mapped_column(SmallInteger, nullable=False)
    avatar_url = mapped_column(Text, nullable=False)
    username = mapped_column(Text, nullable=False)
    custom_name = mapped_column(SmallInteger, nullable=False)


class Project(Base):
    __tablename__ = "projects"
    __table_args__: ClassVar[dict] = {"schema": "registry"}
    id = mapped_column(Text, primary_key=True)
    owner_id = mapped_column(Text, ForeignKey("registry.users.telegram_id"), nullable=False)
    name = mapped_column(Text, nullable=False)
    db_path = mapped_column(Text, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)


class SharedSetting(Base):
    __tablename__ = "shared_settings"
    __table_args__: ClassVar[dict] = {"schema": "registry"}
    key = mapped_column(Text, primary_key=True)
    value = mapped_column(Text, nullable=False)


class ReminderDelivery(Base):
    __tablename__ = "reminder_deliveries"
    __table_args__: ClassVar[dict] = {"schema": "registry"}
    telegram_id = mapped_column(Text, primary_key=True)
    day = mapped_column(Date, primary_key=True)
    run_key = mapped_column(Text, primary_key=True)
    status = mapped_column(Text, nullable=False)
    error = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)


class ProfileAvatar(Base):
    __tablename__ = "profile_avatars"
    __table_args__: ClassVar[dict] = {"schema": "registry"}
    telegram_id = mapped_column(Text, primary_key=True)
    content = mapped_column(LargeBinary, nullable=False)
    mime = mapped_column(Text, nullable=False)
    checked_at = mapped_column(BigInteger, nullable=False)


class Position(Base):
    __tablename__ = "positions"
    __table_args__: ClassVar[dict] = {"schema": "journal"}
    project_id = mapped_column(Text, ForeignKey("registry.projects.id"), primary_key=True)
    id = mapped_column(Text, primary_key=True)
    name = mapped_column(Text, nullable=False)
    section = mapped_column(Text, nullable=False)
    unit = mapped_column(Text, nullable=False)
    planned = mapped_column(Numeric(24, 8), nullable=False)
    rate = mapped_column(Numeric(24, 8), nullable=False)
    baseline = mapped_column(Numeric(24, 8), nullable=False, default=0)
    source_row = mapped_column(Integer, nullable=True)
    source_sheet = mapped_column(Text, nullable=False)


class Entry(Base):
    __tablename__ = "entries"
    __table_args__: ClassVar[dict] = {"schema": "journal"}
    project_id = mapped_column(Text, ForeignKey("registry.projects.id"), primary_key=True)
    item_id = mapped_column(Text, primary_key=True)
    quantity = mapped_column(Numeric(24, 8), nullable=False)
    date = mapped_column(Date, primary_key=True)


class Report(Base):
    __tablename__ = "reports"
    __table_args__: ClassVar[dict] = {"schema": "journal"}
    project_id = mapped_column(Text, ForeignKey("registry.projects.id"), primary_key=True)
    date = mapped_column(Date, primary_key=True)
    revision = mapped_column(Integer, nullable=False)
    text = mapped_column(Text, nullable=True)
    updated_at = mapped_column(DateTime(timezone=True), nullable=True)
    sync_status = mapped_column(Text, nullable=False)
    crew_count = mapped_column(Integer, nullable=False)
    sync_error = mapped_column(Text, nullable=False)
    author_id = mapped_column(Text, nullable=False)
    sync_attempts = mapped_column(Integer, nullable=False)
    retry_at = mapped_column(Text, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit"
    __table_args__: ClassVar[dict] = {"schema": "journal"}
    project_id = mapped_column(Text, ForeignKey("registry.projects.id"), primary_key=True)
    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date = mapped_column(Date, nullable=False)
    payload = mapped_column(JSONB, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectSetting(Base):
    __tablename__ = "settings"
    __table_args__: ClassVar[dict] = {"schema": "journal"}
    project_id = mapped_column(Text, ForeignKey("registry.projects.id"), primary_key=True)
    key = mapped_column(Text, primary_key=True)
    value = mapped_column(Text, nullable=True)


class DaySnapshot(Base):
    __tablename__ = "day_snapshots"
    __table_args__: ClassVar[dict] = {"schema": "journal"}
    project_id = mapped_column(Text, ForeignKey("registry.projects.id"), primary_key=True)
    date = mapped_column(Date, primary_key=True)
    payload = mapped_column(JSONB, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)
