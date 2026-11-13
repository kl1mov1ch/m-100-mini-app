"""Local BM25 ranking. Queries never change source quantities or section names."""

import json
import math
import re
from collections import Counter


def terms(text):
    words = re.findall(r"[а-яa-z0-9]+", text.casefold().replace("ё", "е"))
    return [word[:6] if len(word) > 6 else word for word in words if len(word) > 2]


def rank(query, records):
    words = set(terms(query))
    documents = [Counter(terms(row["text"])) for row in records]
    average = sum(sum(row.values()) for row in documents) / max(1, len(documents))
    frequencies = {word: sum(word in row for row in documents) for word in words}
    result = []
    for record, document in zip(records, documents):
        length = sum(document.values())
        score = sum(
            math.log(1 + (len(documents) - frequencies[word] + 0.5) / (frequencies[word] + 0.5))
            * document[word]
            * 2.2
            / (document[word] + 1.2 * (0.25 + 0.75 * length / max(1, average)))
            for word in words
            if document[word]
        )
        if score > 0:
            result.append({**record, "score": round(score, 5)})
    return sorted(result, key=lambda row: (-row["score"], row.get("page", 0)))


def search(path, query, signature, limit=12):
    records = []
    # Page JSON is already OCR'd and source-bound; searching performs no OCR or LLM call.
    for page in sorted((path / "docling").glob("page-*.json")):
        value = json.loads(page.read_text(encoding="utf-8"))
        if value.get("source") != signature:
            continue
        number = int(page.stem.split("-")[-1])
        lines = value.get("analysis_text", value["text"]).splitlines()
        for index, line in enumerate(lines):
            if len(line.strip()) > 5:
                records.append({"page": number, "line": index + 1, "text": line[:1600]})
    return rank(query, records)[:limit]


def relevant_examples(query, examples):
    records = [
        {"text": " ".join(str(value) for value in row.values()), "example": row} for row in examples
    ]
    return [row["example"] for row in rank(query, records)[:3]]
