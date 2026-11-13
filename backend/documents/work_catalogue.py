"""Labour names, not equipment models or fixed quantities.

The ventilation vocabulary follows the user's reviewed payroll workbook. Prices
and quantities are deliberately absent: they belong to each individual PDF.
"""

import re

from .profile import load_template


def catalogue():
    return tuple(
        (row["id"], row["name"], row["unit"], row["pattern"]) for row in load_template()["works"]
    )


def ventilation_type(source):
    if source.get("category") != "Вентиляция":
        return None
    value = re.sub(r"\s+", " ", source["name"].casefold().replace("ё", "е"))
    for pattern, replacement in load_template().get("ocr_word_aliases", {}).items():
        value = re.sub(pattern, replacement, value)
    consumables = next(row for row in catalogue() if row[0] == "consumables")
    if re.search(consumables[3], value):
        return consumables
    value = re.split(r"\b(?:[lL]\s*=|в\s+комплекте|6\s+комплекте)", value, maxsplit=1)[0]
    # An accessory mentioning its parent is not the parent equipment itself.
    if re.search(r"поддон|под\s+дефлектор|гибк\w*\s+вставк|комплект.*вибро|переход|креплен", value):
        return None
    if re.search(r"изоляц|матами|минераловатн|вертикально[ -]слоист", value) and not re.search(
        r"огнезащ", value
    ):
        return next(row for row in catalogue() if row[0] == "insulation")
    exclusions = {row["id"]: row.get("exclude_pattern") for row in load_template()["works"]}
    matched = next(
        (
            row
            for row in catalogue()
            if re.search(row[3], value)
            and not (exclusions[row[0]] and re.search(exclusions[row[0]], value))
        ),
        None,
    )
    if matched:
        return matched
    return next((row for row in catalogue() if row[1] == source.get("work_name")), None)


def catalogue_prompt():
    return [
        {key: row[key] for key in ("name", "unit", "exclude_pattern") if key in row}
        for row in load_template()["works"]
    ]


def catalogue_order(name):
    return next(
        (index for index, row in enumerate(catalogue()) if row[1] == name), len(catalogue())
    )
