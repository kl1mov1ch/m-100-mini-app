import asyncio
import io
import os
import threading

from fastapi import APIRouter, HTTPException, Request

from . import store

router = APIRouter()
model_instance = None
model_lock = threading.Lock()


def get_model():
    global model_instance
    if model_instance is None:
        from faster_whisper import WhisperModel

        model_name = os.getenv("WHISPER_MODEL", "small")
        snapshot_root = (
            store.ROOT
            / "data"
            / "models"
            / f"models--Systran--faster-whisper-{model_name}"
            / "snapshots"
        )
        local_snapshots = [
            path for path in snapshot_root.glob("*") if (path / "model.bin").exists()
        ]
        model_location = str(local_snapshots[-1]) if local_snapshots else model_name
        model_instance = WhisperModel(
            model_location,
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            download_root=str(store.ROOT / "data" / "models"),
        )
    return model_instance


def recognize_audio(content):
    from faster_whisper.audio import decode_audio

    with model_lock:
        audio = decode_audio(io.BytesIO(content), sampling_rate=16000)
        if len(audio) > 16000 * 300:
            raise ValueError("Максимальная длительность сообщения — 5 минут")
        segments, details = get_model().transcribe(
            audio,
            language="ru",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt="Строительные работы. Медный фреонопровод, теплоизоляция, кабель, хомут, диаметр, метры, штуки.",
        )
        transcript = " ".join(segment.text.strip() for segment in segments).strip()
        if not transcript:
            raise ValueError("Речь не распознана. Запишите ближе к микрофону или введите текст.")
        return transcript


@router.post("/api/transcribe")
async def transcribe(request: Request):
    form = await request.form(max_files=1, max_part_size=21 * 1024 * 1024)
    audio_file = form.get("file")
    if not audio_file or not hasattr(audio_file, "read"):
        raise HTTPException(422, "Добавьте голосовое сообщение")
    content = await audio_file.read(20 * 1024 * 1024 + 1)
    if not content or len(content) > 20 * 1024 * 1024:
        raise HTTPException(422, "Размер аудио должен быть от 1 байта до 20 МБ")
    try:
        transcript = await asyncio.to_thread(recognize_audio, content)
        return {"text": transcript, "engine": "whisper-local"}
    except ValueError as error:
        raise HTTPException(422, str(error))
    except ImportError:
        raise HTTPException(503, "Распознавание голоса ещё не установлено на сервере")
    except Exception:
        raise HTTPException(
            503, "Не удалось распознать аудио. Проверьте файл или повторите запись."
        )
