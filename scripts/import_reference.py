"""Read the supplied reference, never change it. Run with openpyxl available."""

import json
import sys
from datetime import datetime
from pathlib import Path
import openpyxl

source = Path(sys.argv[1])
sheet = openpyxl.load_workbook(source, data_only=True).active
positions, entries = [], []
section = "ОВ 3"
for row in sheet.iter_rows(min_row=4):
    title = str(row[1].value or "").strip()
    if title == "ЭМ3":
        section = "ЭМ3"
    unit, planned = row[2].value, row[3].value
    if not title or not unit or not isinstance(planned, (int, float)):
        continue
    ident = f"excel-{row[0].row}"
    completed = 0
    for cell in row[9:]:
        date = sheet.cell(3, cell.column).value
        if isinstance(date, datetime) and isinstance(cell.value, (float, int)):
            entries.append(
                {
                    "item_id": ident,
                    "date": date.date().isoformat(),
                    "quantity": cell.value,
                }
            )
            completed += cell.value
    positions.append(
        {
            "id": ident,
            "name": title,
            "section": section,
            "unit": str(unit).lower().rstrip("."),
            "planned": planned,
            "rate": row[4].value or 0,
            "source_row": row[0].row,
        }
    )
output = Path(__file__).resolve().parents[1] / "data" / "seed.json"
output.write_text(
    json.dumps(
        {"source": source.name, "positions": positions, "entries": entries},
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(f"Imported {len(positions)} positions and {len(entries)} daily values")
