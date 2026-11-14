"""Versioned document instructions and structural work templates."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent


def load_prompt(name):
    if name not in {
        "extract",
        "verify",
        "families",
        "template",
        "visual",
        "visual_verify",
        "visual_dimensions",
    }:
        raise ValueError("Unknown document prompt")
    return (ROOT / "prompts" / (name + ".md")).read_text(encoding="utf-8")


def load_template():
    path = ROOT / "templates" / "ventilation.json"
    return _template(path.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _template(revision):
    return json.loads((ROOT / "templates" / "ventilation.json").read_text(encoding="utf-8"))


def profile_version():
    files = sorted((ROOT / "prompts").glob("*.md")) + sorted((ROOT / "templates").glob("*.json"))
    return hashlib.sha256(b"".join(path.read_bytes() for path in files)).hexdigest()[:16]
