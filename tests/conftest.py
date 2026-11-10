from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def independent_demo_data(monkeypatch):
    monkeypatch.setenv("APP_SEED_FILE", str(Path(__file__).parent / "fixtures/demo.json"))
    monkeypatch.delenv("APP_REGISTRY", raising=False)
