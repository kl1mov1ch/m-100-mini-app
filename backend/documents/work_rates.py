import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from difflib import SequenceMatcher
from functools import lru_cache

import httpx
from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .aggregation import work_key, work_traits
from .normalization import canonical, decimal_value, unit_value
from .profile import load_prompt
from .repository import WorkRate, session

OPERATION = re.compile(
    r"\b(демонтаж|замен|изготовлен|пусконалад|настройк|испытан|монтаж|установ|проклад)"
)


def rate_key(row):
    unit, factor = unit_value(row.get("unit"))
    if factor != 1:
        return None
    category, name = canonical(row.get("category")), canonical(row.get("name"))
    if not category or not name:
        return None
    commissioning = canonical(row.get("subsection")).startswith("пусконаладоч") or any(
        source.get("table_role") == "commissioning" for source in row.get("sources", [])
    )
    return category, unit, "commissioning" if commissioning else "work", name


def record_rate(database, row, before):
    rate = decimal_value(row.get("rate"))
    key = rate_key(row)
    if key is None or rate is None:
        return
    unchanged = rate == decimal_value(before.get("rate"))
    if unchanged and row.get("rate_suggestion"):
        return
    if (
        unchanged
        and before.get("confirmed")
        and rate_key({**before, "sources": row.get("sources", [])}) == key
    ):
        return
    row.pop("rate_suggestion", None)
    category, unit, work_type, name_key = key
    insert = postgres_insert if database.bind.dialect.name == "postgresql" else sqlite_insert
    statement = insert(WorkRate).values(
        category=category,
        unit=unit,
        work_type=work_type,
        name_key=name_key,
        name=row["name"],
        rate=rate,
        updated_at=datetime.now(UTC),
    )
    database.execute(
        statement.on_conflict_do_update(
            index_elements=[
                WorkRate.category,
                WorkRate.unit,
                WorkRate.work_type,
                WorkRate.name_key,
            ],
            set_={
                "name": statement.excluded.name,
                "rate": statement.excluded.rate,
                "updated_at": statement.excluded.updated_at,
            },
        )
    )


@lru_cache(maxsize=4096)
def comparison(name):
    words = work_key(name).split()
    numbers = tuple(word.replace(",", ".") for word in words if word[0].isdigit())
    operations = {
        "монтаж" if operation in {"монтаж", "установ", "проклад"} else operation
        for operation in OPERATION.findall(name)
    }
    return set(words), numbers, work_traits(name), operations


def similar_rates(target, candidates):
    words, sizes, traits, operations = comparison(target)
    matches = []
    for candidate in candidates:
        name = candidate.name_key
        other_words, other_sizes, other_traits, other_operations = comparison(name)
        if (
            sizes != other_sizes
            or traits != other_traits
            or (operations and other_operations and operations != other_operations)
        ):
            continue
        score = max(
            len(words & other_words) / max(1, len(words | other_words)),
            SequenceMatcher(None, target, name).ratio(),
        )
        if score >= 0.56:
            matches.append((score, candidate))
    matches.sort(key=lambda match: (-match[0], match[1].name_key))
    return [candidate for _, candidate in matches[:5]]


def suggest(row, reference, method):
    row["rate"] = format(reference.rate.normalize(), "f")
    row["rate_suggestion"] = {"name": reference.name, "method": method}


async def suggest_rates(rows, settings, complete=None):
    pending = defaultdict(list)
    for row in rows:
        if row.get("confirmed"):
            continue
        if row.pop("rate_suggestion", None):
            row["rate"] = None
        if row.get("rate") is None and (key := rate_key(row)):
            pending[key].append(row)
    if not pending:
        return
    partitions = {key[:3] for key in pending}
    catalogue = defaultdict(dict)
    with session() as database:
        for item in database.scalars(
            select(WorkRate).where(
                tuple_(WorkRate.category, WorkRate.unit, WorkRate.work_type).in_(partitions)
            )
        ):
            catalogue[item.category, item.unit, item.work_type][item.name_key] = item

    fuzzy = []
    for key, items in pending.items():
        candidates = catalogue[key[:3]]
        if reference := candidates.get(key[3]):
            for row in items:
                suggest(row, reference, "exact")
        elif complete and (matches := similar_rates(key[3], candidates.values())):
            fuzzy.append((items, matches))

    for offset in range(0, len(fuzzy), 18):
        batch = fuzzy[offset : offset + 18]
        payload = {
            "items": [
                {
                    "index": index,
                    "name": items[0]["name"],
                    "category": items[0]["category"],
                    "unit": items[0]["unit"],
                    "subsection": items[0].get("subsection", ""),
                    "candidates": [item.name for item in matches],
                }
                for index, (items, matches) in enumerate(batch)
            ]
        }
        try:
            result = await complete(
                load_prompt("rates"), json.dumps(payload, ensure_ascii=False), settings
            )
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            break
        answers = result.get("matches") if isinstance(result, dict) else None
        if not isinstance(answers, list):
            continue
        accepted = defaultdict(set)
        for match in answers:
            if not isinstance(match, dict):
                continue
            index, candidate = match.get("index"), match.get("candidate")
            if (
                type(index) is int
                and 0 <= index < len(batch)
                and type(candidate) is int
                and 0 <= candidate < len(batch[index][1])
            ):
                accepted[index].add(candidate)
        for index, selections in accepted.items():
            if len(selections) == 1:
                items, matches = batch[index]
                for row in items:
                    suggest(row, matches[next(iter(selections))], "ai")
