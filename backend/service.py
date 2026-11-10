import asyncio
import os
from contextlib import asynccontextmanager, suppress

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import store, workspaces
from .api import accounts, bitrix, reports
from .audio import router as audio_router
from .clock import now
from .clock import today as today
from .imports import register
from .reporting import ai_settings
from .runtime import configure_runtime
from .security import access
from .synchronization import retry_pending_reports
from .table_editing import router as table_editing_router

load_dotenv(store.ROOT / ".env")


@asynccontextmanager
async def lifespan(app):
    configure_runtime()
    store.init(seed=os.getenv("APP_ENV", "development") == "development")
    workspaces.init()
    retry_task = asyncio.create_task(retry_pending_reports())
    try:
        yield
    finally:
        retry_task.cancel()
        with suppress(asyncio.CancelledError):
            await retry_task


app = FastAPI(title="Журнал работ", lifespan=lifespan)


@app.get("/healthz", include_in_schema=False)
def health():
    return {"status": "ok"}


app.middleware("http")(access)
app.include_router(accounts.router)
app.include_router(reports.router)
app.include_router(bitrix.router)
app.include_router(audio_router)
app.include_router(table_editing_router)
register(app, ai_settings, now)
dist = store.ROOT / "frontend/dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
