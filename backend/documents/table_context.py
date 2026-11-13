"""Document-level table matrix: row names, disciplines and equipment scope."""

import re

from .intent import requested_categories
from .parsed_tables import CELLS, ROWS
from .work_catalogue import ventilation_type


def document_rows(tables):
    category, role, previous_shape, section, previous_name, previous_assembly = (
        None,
        None,
        None,
        "",
        "",
        False,
    )
    result = {}
    previous_unit = ""
    for page, table in sorted(tables.items()):
        if not table:
            continue
        records = list(ROWS.finditer(table["text"]))
        header = next((row for row in records if int(row[1]) in table["headers"]), None)
        if not header:
            continue
        cells = list(CELLS.finditer(header[2]))
        name_column = next(
            ((cell[1], cell[2]) for cell in cells if re.search(r"наименован", cell[3], re.I)), None
        )
        unit_column = next(
            (
                (cell[1], cell[2])
                for cell in cells
                if re.search(r"единиц|ед\.?\s*изм", cell[3], re.I)
            ),
            None,
        )
        count_column = next(
            ((cell[1], cell[2]) for cell in cells if re.match(r"\s*кол", cell[3], re.I)), None
        )
        surface_column = next(
            (
                (cell[1], cell[2])
                for cell in cells
                if re.search(r"поверх.*ност|поверх", cell[3], re.I | re.S)
            ),
            None,
        )
        shape = (name_column, unit_column, count_column)
        if previous_shape != shape:
            role = None
            previous_name = ""
            previous_assembly = False
            previous_unit = ""
        if surface_column and not unit_column:
            role = "insulation_schedule"
        previous_shape = shape
        name, assembly = previous_name, previous_assembly
        unit = previous_unit
        for row in records:
            number = int(row[1])
            values = {(cell[1], cell[2]): cell[3].strip() for cell in CELLS.finditer(row[2])}
            value = values.get(name_column, "")
            quantity = values.get(count_column, "")
            if number in table["headers"]:
                continue
            short = value.casefold().replace("ё", "е")
            ordinal = (
                number == max(table["headers"]) + 1
                and len(values) >= 5
                and sum(bool(re.fullmatch(r"\d{1,2}(?: \[OCR.*)?", v)) for v in values.values())
                >= len(values) * 0.65
            )
            if not quantity and 0 < len(value) < 120:
                detected = requested_categories(value)
                heading = bool(
                    re.match(
                        r"^(?:вентиля|отоплен|теплоснаб|теплоснад|водоснаб|канализац|кондиционир|электроснаб|автоматика)[а-я\s:.,-]*$",
                        short,
                    )
                )
                if heading and len(detected) == 1:
                    category = next(iter(detected))
                    section = value
                    name, unit, assembly = "", "", False
                    continue
                if re.search(r"пуск.?налад|пуско.?налад", short):
                    role = "commissioning"
                elif re.search(r"^обор[уи]дован", short):
                    role, assembly = "equipment", False
                elif re.search(r"^изделия|материал", short):
                    role, assembly = "materials", False
                    name, unit = "", ""
                    continue
                if re.search(r"^обор[уи]дован", short):
                    name, unit = "", ""
                    continue
            subject = re.sub(r"^\s*\d+[.\s)]*", "", short)
            primary = bool(
                re.match(
                    r"(?:приточн|вентилятор|воздуховод|труб|клапан|кран|диффузор|дпу|реш[её]тк|заслонк|глушител|шумоглушител|люч|зонт|дефлектор|устройств|узел|изделия|изоляц|маты|огнезащ)",
                    subject,
                )
            )
            primary = primary or bool(re.match(r"^\d+[.)]?\s*[а-яa-z]{3,}", short))
            primary = primary or bool(
                re.match(
                    r"^[#Øø⌀]\d+\s+\d*[.\s]*(?:диффузор|клапан|заслонк|воздуховод|реш[её]тк)", short
                )
            )
            primary = primary or bool(
                re.search(
                    r"\b(?:приточн\w*|вентилятор\w*|дроссель[ -]?клапан\w*|воздуховод\w*|клапан\w*|диффузор\w*|дпу|реш[её]тк\w*|заслонк\w*|люч\w*|дюч\w*|зонт\w*|дефлектор\w*|устройств\w*|узел)\b",
                    subject[:110],
                )
            )
            new_numbered = bool(re.match(r"^\s*\d+[.]?\s*[А-ЯA-Z]", value))
            primary = primary or bool(ventilation_type({"name": value, "category": category}))
            if (
                quantity
                and re.match(r"^\s*(?:\d+[.)]?\s*)?[А-Я][а-я]{2,}", value)
                and not re.match(
                    r"^(?:[а-яa-z6-9][.)]|[\-—]|[δд0о]\s*=|[LlLNnPp]\s*=|из\s|с\s|для\s|в\s|на\s)",
                    value,
                )
            ):
                # Keep unfamiliar component names for AI classification as well;
                # the reviewed vocabulary is not a whitelist of allowed works.
                primary = True
            if not quantity and (
                re.search(r"[в6]\s+составе|[в6]\s+комплекте", short)
                or (role == "equipment" and name and re.match(r"(?:[а-яa-z6-9][.)])\s*", short))
            ):
                assembly = True
            in_assembly = assembly and not new_numbered
            if primary and not in_assembly:
                name = value
                unit = values.get(unit_column, "")
                assembly = bool(re.search(r"[в6]\s+составе|[в6]\s+комплекте", short))
            component = in_assembly or (
                bool(re.match(r"^\s*(?:[а-яa-z][.)]|[-—])\s*", value, re.I)) and assembly
            )
            component = component or bool(
                role == "equipment"
                and not primary
                and name
                and re.match(r"^(?:с(?:о)?\s|эл[.]?двиг|лопатк|комплект|секция)", short)
            )
            effective_category = "Вентиляция" if re.search(r"воздуховод", name, re.I) else category
            if values.get(unit_column) and not ordinal:
                unit = values[unit_column]
            result[page, number] = {
                "category": effective_category,
                "role": role,
                "name": name,
                "component": component,
                "unit_cell": unit,
                "quantity_cell": quantity,
                "quantity_column": f"C{count_column[0]}–C{count_column[1]}"
                if count_column
                else None,
                "surface_column": f"C{surface_column[0]}–C{surface_column[1]}"
                if surface_column
                else None,
                "surface_cell": values.get(surface_column, ""),
                "section": section,
                "ordinal": ordinal,
                "dimension_text": value,
                "named_primary": primary and not in_assembly,
                "unit_present": bool(values.get(unit_column)),
            }
        previous_name = name
        previous_assembly = assembly
        previous_unit = unit
    return result
