import ast
import io
import operator
import re
import zipfile
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from xml.etree import ElementTree as ET

import openpyxl
from openpyxl.utils import get_column_letter, range_boundaries

NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def extend_day_ranges(sheet, new_column, date_columns):
    if not date_columns:
        return
    for row in sheet:
        for cell in row:
            if cell.data_type != "f":
                continue

            def extend(match):
                start, start_row, end, end_row = match.groups()
                first = openpyxl.utils.column_index_from_string(start.replace("$", ""))
                last = openpyxl.utils.column_index_from_string(end.replace("$", ""))
                if first <= min(date_columns) and last >= max(date_columns) and last < new_column:
                    return f"{start}{start_row}:{'$' if end.startswith('$') else ''}{get_column_letter(new_column)}{end_row}"
                return match[0]

            cell.value = re.sub(r"(\$?[A-Z]+)(\$?\d+):(\$?[A-Z]+)(\$?\d+)", extend, cell.value)


def header_text(value):
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def recalculate(content, catalogue, mappings=None, issues=None):
    book = openpyxl.load_workbook(io.BytesIO(content))
    by_sheet = {}
    for position in catalogue:
        sheet_name = position.get("source_sheet") or book.sheetnames[0]
        by_sheet.setdefault(sheet_name, []).append(position)
    for sheet_name, positions in by_sheet.items():
        sheet = book[sheet_name]
        descriptor = next((item for item in mappings or [] if item["name"] == sheet_name), None)
        header = descriptor["header_row"] if descriptor else 1
        fields = {}
        for column in range(1, sheet.max_column + 1):
            label = header_text(sheet.cell(header, column).value)
            if re.search(r"остат.*объем|^остаток$", label):
                fields["remaining"] = column
            elif re.search(r"выполн.*объем|^выполнено$", label):
                fields["completed"] = column
            elif re.search(
                r"выполн.*(?:ден|byn|руб)|сумма.*выполн|стоимость.*выполн|на руки", label
            ):
                fields["earned"] = column
            elif re.search(r"зп.*весь|сумма.*план|стоимость.*смет|по смете.*(?:byn|руб)", label):
                fields["planned_amount"] = column
        mapping = descriptor["mapping"] if descriptor else {"planned": 4, "rate": 5}
        date_row = descriptor.get("date_row", header) if descriptor else 3
        dates = [
            column
            for column in range(1, sheet.max_column + 1)
            if isinstance(sheet.cell(date_row, column).value, (datetime, date))
        ]
        for position in positions:
            row = position["source_row"]
            completed = position.get("baseline", 0) + sum(
                float(sheet.cell(row, column).value or 0)
                for column in dates
                if not isinstance(sheet.cell(row, column).value, str)
            )
            planned = position["planned"]
            rate = position["rate"]
            computed = {
                "completed": completed,
                "remaining": planned - completed,
                "earned": float(
                    (Decimal(str(completed)) * Decimal(str(rate))).quantize(
                        Decimal(".01"), rounding=ROUND_HALF_UP
                    )
                ),
                "planned_amount": float(
                    (Decimal(str(planned)) * Decimal(str(rate))).quantize(
                        Decimal(".01"), rounding=ROUND_HALF_UP
                    )
                ),
            }
            for name, column in fields.items():
                cell = sheet.cell(row, column)
                if cell.data_type != "f":
                    planned_ref = f"{get_column_letter(mapping.get('planned') or 4)}{row}"
                    rate_ref = f"{get_column_letter(mapping.get('rate') or 5)}{row}"
                    completed_ref = (
                        f"{get_column_letter(fields['completed'])}{row}"
                        if fields.get("completed")
                        else str(completed)
                    )
                    formulas = {
                        "completed": "="
                        + str(position.get("baseline", 0))
                        + "+SUM("
                        + ",".join(f"{get_column_letter(column)}{row}" for column in dates)
                        + ")",
                        "remaining": f"={planned_ref}-{completed_ref}",
                        "earned": f"=ROUND({completed_ref}*{rate_ref},2)",
                        "planned_amount": f"=ROUND({planned_ref}*{rate_ref},2)",
                    }
                    cell.value = formulas[name] if dates or name != "completed" else computed[name]
                cell.number_format = (
                    '#,##0.00 "BYN"' if name in ("earned", "planned_amount") else "0.####"
                )
    stream = io.BytesIO()
    book.save(stream)
    return cache_formulas(stream.getvalue(), issues)


class FormulaEvaluator:
    def __init__(self, book):
        self.book = book
        self.cache = {}
        self.visiting = set()

    def cell(self, sheet, address):
        key = (sheet, address.replace("$", ""))
        if key in self.cache:
            return self.cache[key]
        if key in self.visiting:
            raise ValueError("Циклическая формула")
        value = self.book[sheet][key[1]].value
        if isinstance(value, str) and value.startswith("="):
            self.visiting.add(key)
            try:
                formula = (
                    value[1:]
                    .replace("$", "")
                    .replace(";", ",")
                    .replace("^", "**")
                    .replace("<>", "!=")
                )
                formula = re.sub(r"(?<![<>=!])=(?!=)", "==", formula)
                formula = re.sub(
                    r"(?:'([^']+)'|([A-Za-z_А-Яа-я][\w ]*))!([A-Z]+\d+)",
                    lambda match: f"CELL({(match[1] or match[2])!r},{match[3]!r})",
                    formula,
                )
                formula = re.sub(r"\b([A-Z]+\d+):([A-Z]+\d+)\b", r"RANGE(\1,\2)", formula)
                value = self.evaluate(ast.parse(formula, mode="eval").body, sheet)
            finally:
                self.visiting.remove(key)
        self.cache[key] = value
        return value

    def evaluate(self, node, sheet):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and re.fullmatch(r"[A-Z]+\d+", node.id):
            return self.cell(sheet, node.id)
        if isinstance(node, ast.Name) and node.id in ("TRUE", "FALSE"):
            return node.id == "TRUE"
        binary = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.Mod: operator.mod,
        }
        if isinstance(node, ast.BinOp) and type(node.op) in binary:
            left = self.evaluate(node.left, sheet)
            right = self.evaluate(node.right, sheet)
            left = 0 if left is None else left
            right = 0 if right is None else right
            if isinstance(node.op, ast.Pow) and abs(right) > 20:
                raise ValueError("Слишком большая степень")
            return binary[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = self.evaluate(node.operand, sheet)
            value = 0 if value is None else value
            return -value if isinstance(node.op, ast.USub) else value
        comparison = {
            ast.Eq: operator.eq,
            ast.NotEq: operator.ne,
            ast.Lt: operator.lt,
            ast.LtE: operator.le,
            ast.Gt: operator.gt,
            ast.GtE: operator.ge,
        }
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in comparison:
            left = self.evaluate(node.left, sheet)
            right = self.evaluate(node.comparators[0], sheet)
            if left is None:
                left = "" if isinstance(right, str) else 0
            if right is None:
                right = "" if isinstance(left, str) else 0
            return comparison[type(node.ops[0])](left, right)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = node.func.id.upper()
            if function == "IF" and len(node.args) == 3:
                return self.evaluate(
                    node.args[1] if self.evaluate(node.args[0], sheet) else node.args[2], sheet
                )
            if function == "IFERROR" and len(node.args) == 2:
                try:
                    return self.evaluate(node.args[0], sheet)
                except (ValueError, ArithmeticError, TypeError):
                    return self.evaluate(node.args[1], sheet)
            if (
                function == "RANGE"
                and len(node.args) == 2
                and all(isinstance(arg, ast.Name) for arg in node.args)
            ):
                left, top, right, bottom = range_boundaries(f"{node.args[0].id}:{node.args[1].id}")
                if (right - left + 1) * (bottom - top + 1) > 200000:
                    raise ValueError("Слишком большой диапазон формулы")
                cells = self.book[sheet][f"{node.args[0].id}:{node.args[1].id}"]
                return [self.cell(sheet, cell.coordinate) for row in cells for cell in row]
            values = [self.evaluate(arg, sheet) for arg in node.args]
            if function == "CELL" and len(values) == 2:
                return self.cell(values[0], values[1])
            if function == "ISBLANK" and len(values) == 1:
                return values[0] is None
            if function == "NOT" and len(values) == 1:
                return not values[0]
            if function in ("OR", "AND"):
                flags = (
                    bool(item)
                    for value in values
                    for item in (value if isinstance(value, list) else [value])
                )
                return any(flags) if function == "OR" else all(flags)
            flattened = [
                item
                for value in values
                for item in (value if isinstance(value, list) else [value])
                if isinstance(item, (int, float))
            ]
            if function == "SUM":
                return sum(flattened)
            if (
                function == "SUMPRODUCT"
                and len(values) == 2
                and all(isinstance(value, list) for value in values)
            ):
                if len(values[0]) != len(values[1]):
                    raise ValueError("Диапазоны SUMPRODUCT разной длины")
                return sum((left or 0) * (right or 0) for left, right in zip(*values))
            if function == "INT" and len(values) == 1:
                return int(values[0] // 1)
            if function == "MOD" and len(values) == 2:
                return values[0] % values[1]
            if function == "COUNT":
                return len(flattened)
            if (
                function == "COUNTIF"
                and len(values) == 2
                and values[1] == ">0"
                and isinstance(values[0], list)
            ):
                return sum(isinstance(value, (int, float)) and value > 0 for value in values[0])
            if function == "AVERAGE" and flattened:
                return sum(flattened) / len(flattened)
            if function == "MIN":
                return min(flattened, default=0)
            if function == "MAX":
                return max(flattened, default=0)
            if function == "ROUND" and len(values) == 2:
                return float(
                    Decimal(str(values[0])).quantize(
                        Decimal(1).scaleb(-int(values[1])), rounding=ROUND_HALF_UP
                    )
                )
            if function == "ABS" and len(values) == 1:
                return abs(values[0])
        raise ValueError("Неподдерживаемая формула")


def cache_formulas(content, issues=None, *, original=None):
    from openpyxl.utils.datetime import to_excel

    from .workbook_journal import is_journal

    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    originals = openpyxl.load_workbook(io.BytesIO(original), data_only=True) if original else None
    evaluator = FormulaEvaluator(book)
    cached = {}
    for index, sheet in enumerate(book, 1):
        values = {}
        for row in sheet:
            for cell in row:
                if cell.data_type == "f":
                    if originals is not None and not is_journal(sheet):
                        previous = originals[sheet.title][cell.coordinate]
                        value = previous.value
                        if value is not None:
                            values[cell.coordinate] = (
                                to_excel(value, originals.epoch)
                                if previous.is_date and not isinstance(value, (int, float))
                                else value
                            )
                            continue
                    try:
                        values[cell.coordinate] = evaluator.cell(sheet.title, cell.coordinate)
                    except (
                        ValueError,
                        SyntaxError,
                        ArithmeticError,
                        TypeError,
                        KeyError,
                        RecursionError,
                    ):
                        message = f"Лист «{sheet.title}», ячейка {cell.coordinate}: формула требует проверки."
                        if issues is None:
                            raise ValueError(message)
                        issues.append(
                            {
                                "id": f"{sheet.title}:{cell.coordinate}",
                                "sheet": sheet.title,
                                "cell": cell.coordinate,
                                "value": str(cell.value),
                                "message": message,
                            }
                        )
        cached[f"xl/worksheets/sheet{index}.xml"] = values
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(content)) as source,
        zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename in cached and cached[item.filename]:
                root = ET.fromstring(data)
                for node in root.iter(f"{{{NAMESPACE}}}c"):
                    if node.get("r") not in cached[item.filename]:
                        continue
                    value = cached[item.filename][node.get("r")]
                    child = node.find(f"{{{NAMESPACE}}}v")
                    if child is None:
                        child = ET.SubElement(node, f"{{{NAMESPACE}}}v")
                    child.text = (
                        ""
                        if value is None
                        else str(int(value) if isinstance(value, bool) else value)
                    )
                    if isinstance(value, str):
                        node.set("t", "str")
                    else:
                        node.attrib.pop("t", None)
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(item, data)
    return output.getvalue()


def verify_calculations(expected, actual, sheet_name=None):
    formulas = openpyxl.load_workbook(io.BytesIO(expected), data_only=False)
    values = openpyxl.load_workbook(io.BytesIO(expected), data_only=True)
    remote = openpyxl.load_workbook(io.BytesIO(actual), data_only=True)
    for sheet in formulas:
        if sheet_name and sheet.title != sheet_name:
            continue
        for row in sheet:
            for cell in row:
                if cell.data_type != "f":
                    continue
                expected_value = values[sheet.title][cell.coordinate].value
                if expected_value is None:
                    continue
                received = (
                    remote[sheet.title][cell.coordinate].value if sheet.title in remote else None
                )
                if isinstance(expected_value, (int, float)) and isinstance(received, (int, float)):
                    matches = abs(expected_value - received) < 0.000001
                else:
                    matches = expected_value == received
                if not matches:
                    raise ValueError(
                        f"Битрикс не подтвердил пересчёт: лист «{sheet.title}», ячейка {cell.coordinate}."
                    )
