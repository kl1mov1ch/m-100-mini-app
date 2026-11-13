import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Text, create_engine, select
from sqlalchemy.orm import Session, mapped_column

from .. import postgres, store
from ..orm_models import Base


class DocumentJob(Base):
    __tablename__ = "document_jobs"
    __table_args__: ClassVar[dict] = {"schema": "registry"}
    id = mapped_column(Text, primary_key=True)
    owner_id = mapped_column(
        Text, ForeignKey("registry.users.telegram_id"), nullable=False, index=True
    )
    name = mapped_column(Text, nullable=False)
    status = mapped_column(Text, nullable=False, index=True)
    pages = mapped_column(Integer, nullable=False, default=0)
    processed = mapped_column(Integer, nullable=False, default=0)
    payload = mapped_column(JSON, nullable=False, default=dict)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False)


@contextmanager
def session():
    if postgres.enabled():
        with (
            postgres.pool().begin() as connection,
            Session(bind=connection, expire_on_commit=False) as database,
        ):
            yield database
        return
    path = Path(os.getenv("APP_REGISTRY", str(store.base_path().with_suffix(".registry.sqlite3"))))
    engine = create_engine(
        "sqlite:///" + str(path), execution_options={"schema_translate_map": {"registry": None}}
    )
    try:
        DocumentJob.__table__.create(engine, checkfirst=True)
        with Session(engine, expire_on_commit=False) as database, database.begin():
            yield database
    finally:
        engine.dispose()


def version(value):
    return (
        value.replace(tzinfo=UTC).isoformat()
        if value.tzinfo is None
        else value.astimezone(UTC).isoformat()
    )


def public(job):
    result = {
        key: getattr(job, key) for key in ("id", "name", "status", "pages", "processed", "payload")
    } | {"created_at": version(job.created_at), "updated_at": version(job.updated_at)}
    result["payload"] = {
        key: value for key, value in job.payload.items() if not key.startswith("_")
    }
    return result


def owned(database, ident, owner):
    job = database.scalar(
        select(DocumentJob).where(DocumentJob.id == ident, DocumentJob.owner_id == owner)
    )
    if job is None:
        raise HTTPException(404, "Документ не найден")
    return job


def folder(ident):
    if len(ident) != 32 or any(char not in "0123456789abcdef" for char in ident):
        raise HTTPException(404, "Документ не найден")
    return store.ROOT / "data" / "document-jobs" / ident


def create(owner, name):
    now = datetime.now(UTC)
    return DocumentJob(
        id=uuid4().hex,
        owner_id=owner,
        name=name,
        status="queued",
        pages=0,
        processed=0,
        payload={"page_results": [], "works": [], "questions": []},
        created_at=now,
        updated_at=now,
    )
