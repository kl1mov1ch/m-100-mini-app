"""ASGI entry point."""

from .clock import today as today
from .security import validate_init_data as validate_init_data
from .service import app as app
