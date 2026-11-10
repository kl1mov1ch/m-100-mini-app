from fastapi.testclient import TestClient

from backend import speech_service


def test_private_speech_requires_token_and_validates_audio(monkeypatch):
    monkeypatch.setenv("SPEECH_SHARED_TOKEN", "test-token-" * 5)
    monkeypatch.setattr(speech_service, "recognize_audio", lambda content: "Кабель 15 метров")
    with TestClient(speech_service.app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.post("/transcribe").status_code == 401
        headers = {"Authorization": "Bearer " + "test-token-" * 5}
        assert client.post("/transcribe", headers=headers).status_code == 422
        response = client.post(
            "/transcribe", headers=headers, files={"file": ("voice.ogg", b"audio")}
        )
        assert response.json()["text"] == "Кабель 15 метров"
