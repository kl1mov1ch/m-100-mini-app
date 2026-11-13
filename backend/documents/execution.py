import asyncio
import subprocess
import time
from contextvars import ContextVar

from sqlalchemy import select

from .repository import DocumentJob, session

current_job = ContextVar("document_job", default=None)


class JobDeleted(RuntimeError):
    pass


def check_active():
    ident = current_job.get()
    if ident:
        with session() as database:
            if database.scalar(select(DocumentJob.id).where(DocumentJob.id == ident)) is None:
                raise JobDeleted()


def run(command, **kwargs):
    if current_job.get() is None:
        return subprocess.run(command, **kwargs)
    check_active()
    timeout = kwargs.pop("timeout", None)
    check = kwargs.pop("check", False)
    capture = kwargs.pop("capture_output", False)
    data = kwargs.pop("input", None)
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if data is not None:
        kwargs["stdin"] = subprocess.PIPE
    start = time.monotonic()
    with subprocess.Popen(command, **kwargs) as process:
        first = True
        try:
            while True:
                try:
                    out, err = process.communicate(input=data if first else None, timeout=0.8)
                    break
                except subprocess.TimeoutExpired:
                    first = False
                    check_active()
                    if timeout and time.monotonic() - start >= timeout:
                        raise subprocess.TimeoutExpired(command, timeout)
        except BaseException:
            process.kill()
            process.communicate()
            raise
        if check and process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, out, err)
        return subprocess.CompletedProcess(command, process.returncode, out, err)


async def cancellable(awaitable):
    task = asyncio.create_task(awaitable)
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.8)
            check_active()
        return await task
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
