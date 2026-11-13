"""Surface area from explicit dimensions in a specification row (SI units)."""

import re
from decimal import Decimal, InvalidOperation


def perimeter(dimensions, text=""):
    if not dimensions:
        rectangle = re.search(r"(?<!\d)(\d{2,5})\s*[xх×]\s*(\d{2,5})(?!\d)", text)
        round_duct = re.search(r"[Øø⌀Фф#]\s*(\d{2,5})(?!\d)", text)
        if rectangle:
            dimensions = {"kind": "rectangle", "a_mm": rectangle[1], "b_mm": rectangle[2]}
        elif round_duct:
            dimensions = {"kind": "round", "diameter_mm": round_duct[1]}
    if not dimensions:
        return None
    try:
        if dimensions.get("kind") == "rectangle":
            sizes = [Decimal(str(dimensions[key])) for key in ("a_mm", "b_mm")]
            if all(size.is_finite() and 0 < size <= 100000 for size in sizes):
                return Decimal(2) * sum(sizes) / 1000
        if dimensions.get("kind") == "round":
            diameter = Decimal(str(dimensions["diameter_mm"]))
            if diameter.is_finite() and 0 < diameter <= 100000:
                return Decimal("3.141592653589793") * diameter / 1000
    except (KeyError, InvalidOperation, ValueError):
        return None
    return None
