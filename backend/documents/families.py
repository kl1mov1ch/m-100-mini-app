import json
import re

from .aggregation import work_label
from .normalization import unit_value
from .profile import load_prompt
from .work_catalogue import catalogue_prompt


async def assign_work_names(works, settings, complete):
    """Classify labour types, never quantities, rates or amounts."""
    known = list(dict.fromkeys(work.get("work_name") for work in works if work.get("work_name")))[
        :100
    ]
    pending = {}
    for work in works:
        if not work.get("work_name"):
            stable = work_label(work["name"], None)
            if stable != work["name"]:
                work["work_name"] = stable
                continue
            pending.setdefault((work["name"], unit_value(work.get("unit"))[0]), []).append(work)
    batch = list(pending.items())[:40]
    if not batch:
        return 0
    result = await complete(
        load_prompt("families") + "\n" + load_prompt("template"),
        json.dumps(
            {
                "known": known,
                "structural_template": catalogue_prompt(),
                "items": [
                    {"index": index, "name": key[0], "unit": key[1]}
                    for index, (key, _) in enumerate(batch)
                ],
            },
            ensure_ascii=False,
        ),
        {**settings, "response_token_limit": 3500},
    )
    assignments = result.get("assignments", []) if isinstance(result, dict) else []
    labels = {}
    template_names = {row["name"]: row for row in catalogue_prompt()}
    tentative = set()
    for item in assignments:
        if (
            not isinstance(item, dict)
            or type(item.get("index")) is not int
            or not 0 <= item["index"] < len(batch)
        ):
            continue
        label = str(item.get("work_name") or "").strip()[:180]
        original = batch[item["index"]][0][0]
        exclude = template_names.get(label, {}).get("exclude_pattern")
        if exclude and re.search(exclude, original, re.I):
            labels[item["index"]] = original
            tentative.add(item["index"])
            continue
        checked = work_label(original, label)
        if checked == original and label in template_names:
            checked = label
            tentative.add(item["index"])
        if label in template_names:
            # A name not recognised by the catalogue is an AI suggestion,
            # even if it shares a common word with a paid work type.
            tentative.add(item["index"])
        labels[item["index"]] = checked
    for index, ((name, _), items) in enumerate(batch):
        for work in items:
            work["work_name"] = labels.get(index, name)
            if index in tentative:
                work["classification_warning"] = (
                    "Проверьте сопоставление исходного названия с видом работ"
                )
    return len(batch)
