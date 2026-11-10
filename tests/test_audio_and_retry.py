import io
import wave

import httpx

from backend import audio, store, workspaces
from test_workspaces import client, create


def test_audio_upload_stays_in_selected_object(client, monkeypatch):
    object_id = create(client)
    monkeypatch.setattr(audio, "recognize_audio", lambda content: "Медь 6-ка 15 метров")
    response = client.post(
        "/api/transcribe",
        files={"file": ("voice.ogg", b"example-audio", "audio/ogg")},
        headers={"X-Project-Id": object_id},
    )
    assert response.status_code == 200
    assert response.json()["text"] == "Медь 6-ка 15 метров"


def test_transient_bitrix_error_preserves_report_and_schedules_retry(client, monkeypatch):
    object_id = create(client)
    project = workspaces.project(workspaces.user("local-admin"), object_id)
    with store.connect(project["db_path"]) as database:
        store.set_setting(database, "source", "bitrix")
        store.set_setting(database, "webhook", "configured")

    async def unavailable(*args):
        raise httpx.ConnectError("Temporary network error")

    monkeypatch.setattr("backend.bitrix.upload_day", unavailable)
    from backend.clock import today

    response = client.post(
        "/api/reports",
        json={
            "date": today(),
            "revision": 0,
            "crew_count": 5,
            "lines": [{"item_id": "excel-17", "quantity": 15}],
        },
        headers={"X-Project-Id": object_id},
    )
    assert response.status_code == 200
    report = response.json()
    assert (
        report["sync_status"] == "pending" and report["sync_attempts"] == 1 and report["retry_at"]
    )
    assert report["payroll"]["amount"] == 150 and report["payroll"]["per_person"] == 30
