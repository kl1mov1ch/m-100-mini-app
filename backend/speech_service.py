import asyncio
import hmac
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from .audio import recognize_audio


@asynccontextmanager
async def lifespan(app):
    if len(os.getenv("SPEECH_SHARED_TOKEN", "")) < 32:
        raise RuntimeError("Set a private SPEECH_SHARED_TOKEN")
    yield


app = FastAPI(title="Private speech service", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.post("/transcribe")
async def transcribe(request: Request):
    expected = "Bearer " + os.environ["SPEECH_SHARED_TOKEN"]
    if not hmac.compare_digest(request.headers.get("Authorization", ""), expected):
        raise HTTPException(401, "Unauthorized")
    form = await request.form(max_files=1, max_part_size=21 * 1024 * 1024)
    file = form.get("file")
    if not file or not hasattr(file, "read"):
        raise HTTPException(422, "Добавьте аудио")
    content = await file.read(20 * 1024 * 1024 + 1)
    if not content or len(content) > 20 * 1024 * 1024:
        raise HTTPException(422, "Размер аудио — до 20 МБ")
    try:
        text = await asyncio.to_thread(recognize_audio, content)
        return {"text": text}
    except ValueError as error:
        raise HTTPException(422, str(error))
    except Exception:
        raise HTTPException(503, "Распознавание временно недоступно")
