import os
import time
from datetime import UTC, datetime

from sqlalchemy import select

from .. import store
from .metadata import page_count
from .repository import DocumentJob, folder, session


def notify_queue():
    path = store.ROOT / "data" / "document-queue.signal"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time_ns()), encoding="ascii")


def heartbeat(ident):
    with session() as database:
        job = database.scalar(select(DocumentJob).where(DocumentJob.id == ident).with_for_update())
        if job is None:
            return False
        job.updated_at = datetime.now(UTC)
    return True


def recover_interrupted():
    with session() as database:
        for job in database.scalars(
            select(DocumentJob)
            .where(DocumentJob.status.in_(["queued", "ai_queued", "extracting", "analysing"]))
            .with_for_update()
        ):
            job.status = "ai_queued" if job.status in {"analysing", "ai_queued"} else "queued"
            if not job.pages:
                try:
                    source = folder(job.id) / "source.pdf"
                    job.pages = page_count(source)
                    job.payload = {**job.payload, "file_bytes": source.stat().st_size}
                except ValueError as error:
                    job.status = "failed"
                    job.payload = {**job.payload, "notice": str(error)}
            job.updated_at = datetime.now(UTC)


def worker_lock():
    path = store.ROOT / "data" / "document-worker.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a")
    if os.name == "posix":
        import fcntl

        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return None
    return handle
