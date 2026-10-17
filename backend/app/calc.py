"""Cost calculation for one print job.

Mirrors the owner's spreadsheet: filament + parts + charger + printer
depreciation + energy = cost price. Money is `Decimal` and every line is rounded
to whole cents (half up) *before* it is summed, so the lines on screen always add
up to the total shown under them.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
PART_UNITS = ("stuks", "m", "g")
PART_GROUPS = ("onderdeel", "oplader", "verpakking")


def _num(value, label: str) -> Decimal:
    try:
        number = Decimal(str(value if value not in (None, "") else 0))
    except InvalidOperation:
        raise ValueError(f"{label}: '{value}' is geen getal.") from None
    if not number.is_finite() or number < 0:
        raise ValueError(f"{label}: moet 0 of hoger zijn.")
    return number


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _lines(data: dict, key: str) -> list:
    lines = data.get(key) or []
    if not isinstance(lines, list):
        raise ValueError(f"'{key}' moet een lijst zijn.")
    return lines


def calculate(data: dict, margin_pct=0) -> dict:
    """Return every line and subtotal as strings with two decimals."""
    margin = _num(margin_pct, "Marge")

    filament = []
    for i, line in enumerate(_lines(data, "filament"), 1):
        grams = _num(line.get("grams"), f"Filament {i}: gram")
        per_kg = _num(line.get("price_per_kg"), f"Filament {i}: prijs/kg")
        filament.append({**line, "cost": _money(grams / 1000 * per_kg)})

    parts = []
    for i, line in enumerate(_lines(data, "parts"), 1):
        unit = line.get("unit", "stuks")
        group = line.get("group", "onderdeel")
        if unit not in PART_UNITS:
            raise ValueError(f"Onderdeel {i}: eenheid moet een van {', '.join(PART_UNITS)} zijn.")
        if group not in PART_GROUPS:
            raise ValueError(f"Onderdeel {i}: groep moet een van {', '.join(PART_GROUPS)} zijn.")
        quantity = _num(line.get("quantity"), f"Onderdeel {i}: aantal")
        price = _num(line.get("unit_price"), f"Onderdeel {i}: prijs")
        # Grams are priced per kilogram, like the spreadsheet's "prijs per meter/kg" column.
        cost = quantity / 1000 * price if unit == "g" else quantity * price
        parts.append({**line, "unit": unit, "group": group, "cost": _money(cost)})

    print_data = data.get("print") or {}
    depreciation = []
    for i, line in enumerate(_lines(print_data, "depreciation"), 1):
        hours = _num(line.get("hours"), f"Afschrijving {i}: uren")
        rate = _num(line.get("price_per_hour"), f"Afschrijving {i}: prijs/uur")
        depreciation.append({**line, "cost": _money(hours * rate)})

    energy = []
    for i, line in enumerate(_lines(print_data, "energy"), 1):
        hours = _num(line.get("hours"), f"Energie {i}: uren")
        kw = _num(line.get("kw"), f"Energie {i}: kW")
        tariff = _num(line.get("price_per_kwh"), f"Energie {i}: prijs/kWh")
        energy.append({**line, "cost": _money(hours * kw * tariff)})

    def total(lines):
        return sum((line["cost"] for line in lines), Decimal(0))

    filament_total = total(filament)
    parts_total = total([p for p in parts if p["group"] == "onderdeel"])
    charger_total = total([p for p in parts if p["group"] == "oplader"])
    packaging_total = total([p for p in parts if p["group"] == "verpakking"])
    depreciation_total = total(depreciation)
    energy_total = total(energy)
    cost_price = (filament_total + parts_total + charger_total + packaging_total
                  + depreciation_total + energy_total)
    margin_amount = _money(cost_price * margin / 100)

    def fmt(lines):
        return [{**line, "cost": str(line["cost"])} for line in lines]

    return {
        "filament": fmt(filament),
        "parts": fmt(parts),
        "depreciation": fmt(depreciation),
        "energy": fmt(energy),
        "subtotals": {
            "filament": str(filament_total),
            "parts": str(parts_total),
            "charger": str(charger_total),
            "parts_and_charger": str(parts_total + charger_total),
            "packaging": str(packaging_total),
            "depreciation": str(depreciation_total),
            "energy": str(energy_total),
            "energy_and_depreciation": str(energy_total + depreciation_total),
        },
        "cost_price": str(cost_price),
        "margin_pct": str(margin),
        "margin_amount": str(margin_amount),
        "sell_price": str(cost_price + margin_amount),
    }
