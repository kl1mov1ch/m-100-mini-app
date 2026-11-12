import os
from pathlib import Path


def configure_runtime():
    for name in ("TELEGRAM_BOT_TOKEN", "LLM_API_KEY", "DATABASE_URL"):
        secret_file = os.getenv(name + "_FILE")
        if secret_file and not os.getenv(name):
            os.environ[name] = Path(secret_file).read_text(encoding="utf-8").strip()
    mode = os.getenv("APP_ENV", "development")
    storage = os.getenv("APP_STORAGE", "sqlite")
    if storage not in {"sqlite", "postgres"}:
        raise RuntimeError("APP_STORAGE must be sqlite or postgres")
    if storage == "postgres" and not os.getenv("DATABASE_URL"):
        raise RuntimeError("Set DATABASE_URL or DATABASE_URL_FILE for PostgreSQL")
    if mode not in {"development", "production"}:
        raise RuntimeError("APP_ENV must be development or production")
    if mode == "production":
        if not os.getenv("TELEGRAM_BOT_TOKEN"):
            raise RuntimeError("Set TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN_FILE")
        admins = os.getenv("TELEGRAM_ADMIN_IDS", "").split(",")
        if not admins or not all(
            value.strip().isdigit() and int(value.strip()) > 0 for value in admins
        ):
            raise RuntimeError("Set numeric TELEGRAM_ADMIN_IDS")
        if not os.getenv("APP_ALLOWED_ORIGINS", "").startswith("https://"):
            raise RuntimeError("Set the HTTPS application origin in APP_ALLOWED_ORIGINS")
