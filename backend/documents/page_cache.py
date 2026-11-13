import hashlib
import json
import re


def signature(path, file_hash):
    source = (path / "source.pdf").stat()
    return file_hash or f"{source.st_size}:{source.st_mtime_ns}"


def cached_page(path, number, file_hash):
    text_path = path / f"page-{number}.txt"
    layout_path = path / f"page-{number}.layout.json"
    record = path / f"page-{number}.cache.json"
    try:
        text = text_path.read_text(encoding="utf-8")
        layout = (
            json.loads(layout_path.read_text(encoding="utf-8")) if layout_path.exists() else None
        )
        if layout and (float(layout.get("width", 0)) <= 0 or float(layout.get("height", 0)) <= 0):
            return None
        if record.exists():
            metadata = json.loads(record.read_text(encoding="utf-8"))
            if metadata["source"] != signature(path, file_hash):
                return None
            if metadata["digest"] != hashlib.sha256(text.encode()).hexdigest():
                return None
            if (
                metadata.get("layout_digest")
                != hashlib.sha256(json.dumps(layout).encode()).hexdigest()
            ):
                return None
            return {"text": text, "layout": layout, "confidence": metadata["confidence"]}
        if (
            not text.strip()
            or not layout
            or not layout.get("lines")
            or layout.get("cache_required")
        ):
            return None
        if text_path.stat().st_mtime_ns < (path / "source.pdf").stat().st_mtime_ns:
            return None
        if any(line["end"] > len(text) for line in layout["lines"]):
            return None
        return {
            "text": text,
            "layout": layout,
            "confidence": 0 if (path / f"page-{number}.jpg").exists() else None,
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cache_page(path, number, text, confidence, layout, file_hash):
    if layout:
        layout = {**layout, "cache_required": True}
    files = {}
    if layout:
        files[f"page-{number}.layout.json"] = json.dumps(layout)
    files[f"page-{number}.txt"] = text
    files[f"page-{number}.cache.json"] = json.dumps(
        {
            "source": signature(path, file_hash),
            "digest": hashlib.sha256(text.encode()).hexdigest(),
            "confidence": confidence,
            "layout_digest": hashlib.sha256(json.dumps(layout).encode()).hexdigest(),
        }
    )
    for name, content in files.items():
        target = path / name
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)


def text_digest(text):
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode()).hexdigest()
