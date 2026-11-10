from datetime import datetime
from zoneinfo import ZoneInfo

MINSK_TIMEZONE = ZoneInfo("Europe/Minsk")


def today():
    return datetime.now(MINSK_TIMEZONE).date().isoformat()


def now():
    return datetime.now(MINSK_TIMEZONE).isoformat()
