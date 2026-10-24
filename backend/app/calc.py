"""Cost calculation for one print job.

Mirrors the owner's spreadsheet: filament + parts + charger + printer
depreciation + energy = cost price. Money is `Decimal` and every line is rounded
to whole cents (half up) *before* it is summed, so the lines on screen always add
up to the total shown under them.
"""
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation

from .i18n import L, Localized

CENT = Decimal("0.01")
PART_UNITS = ("stuks", "m", "g")
PART_GROUPS = ("onderdeel", "oplader", "verpakking")
# Rounding of the selling price including VAT: a step to round up to, or a price ending ("x.95").
ROUNDINGS = ("none", "0.05", "0.10", "0.50", "1.00", "5.00", "x.95", "x.99")


def _num(value, label) -> Decimal:
    try:
        number = Decimal(str(value if value not in (None, "") else 0))
    except InvalidOperation:
        raise Localized("err.not_number", label=label, value=value) from None
    if not number.is_finite() or number < 0:
        raise Localized("err.ge", label=label, min=0)
    return number


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def whole_hours(hours: Decimal) -> Decimal:
    """Machine time is always charged in whole hours, rounded up (3,06 h counts as 4 h)."""
    return hours.to_integral_value(rounding=ROUND_CEILING)


def _lines(data: dict, key: str) -> list:
    lines = data.get(key) or []
    if not isinstance(lines, list):
        raise Localized("calc.err.list", key=key)
    return lines


def round_up_price(value: Decimal, rule: str) -> Decimal:
    """Smallest 'nice' price >= value. Never lowers a price, so the margin never drops below its minimum."""
    if rule == "none" or value <= 0:
        return value
    if rule.startswith("x."):
        ending = Decimal(rule[1:])                     # 0.95 -> 4.95, 5.95, ...
        return (max((value - ending).to_integral_value(rounding=ROUND_CEILING), Decimal(0)) + ending).quantize(CENT)
    step = Decimal(rule)
    return ((value / step).to_integral_value(rounding=ROUND_CEILING) * step).quantize(CENT)


def price_from_cost(cost_price: Decimal, margin: Decimal, vat_rate: Decimal, rounding: str = "none") -> dict:
    """Margin, VAT and rounding on top of a cost price (all excl. VAT): the part of the calculation an order repeats with its own
    margin and rounding. Returns Decimals."""
    margin_amount = _money(cost_price * margin / 100)
    sell_price = cost_price + margin_amount
    # VAT is charged on the selling price; everything above is bought excl. VAT (deductible).
    vat_amount = _money(sell_price * vat_rate / 100)
    if rounding != "none":
        # The consumer price is authoritative: round the VAT-inclusive price up, then take the VAT
        # out of it. `margin` becomes a minimum and the effective margin follows from the price.
        minimum_net = sell_price
        incl = round_up_price(sell_price + vat_amount, rounding)
        while True:
            vat_amount = _money(incl - incl / (1 + vat_rate / 100))
            if incl - vat_amount >= minimum_net or incl <= 0:
                break
            incl = round_up_price(incl + CENT, rounding)   # cent rounding of the VAT cost us the minimum
        sell_price = incl - vat_amount
        margin_amount = sell_price - cost_price
    effective_pct = _money(margin_amount / cost_price * 100) if cost_price else Decimal("0.00")
    return {"margin_amount": margin_amount, "sell_price": sell_price, "vat_amount": vat_amount,
            "sell_price_incl_vat": sell_price + vat_amount, "margin_pct_effective": effective_pct}


def calculate(data: dict, margin_pct=0, vat_pct=0, rounding="none") -> dict:
    """Return every line and subtotal as strings with two decimals."""
    margin = _num(margin_pct, L("cl.margin"))
    if rounding not in ROUNDINGS:
        raise Localized("calc.err.rounding", options=", ".join(ROUNDINGS))
    vat_rate = _num(vat_pct, L("cl.vat"))
    if vat_rate > 100:
        raise Localized("calc.err.vat_range")

    filament = []
    for i, line in enumerate(_lines(data, "filament"), 1):
        grams = _num(line.get("grams"), L("cl.filament_grams", i=i))
        per_kg = _num(line.get("price_per_kg"), L("cl.filament_price", i=i))
        filament.append({**line, "cost": _money(grams / 1000 * per_kg)})

    parts = []
    for i, line in enumerate(_lines(data, "parts"), 1):
        unit = line.get("unit", "stuks")
        group = line.get("group", "onderdeel")
        if unit not in PART_UNITS:
            raise Localized("calc.err.unit", i=i, options=", ".join(PART_UNITS))
        if group not in PART_GROUPS:
            raise Localized("calc.err.group", i=i, options=", ".join(PART_GROUPS))
        quantity = _num(line.get("quantity"), L("cl.part_quantity", i=i))
        price = _num(line.get("unit_price"), L("cl.part_price", i=i))
        # Grams are priced per kilogram, like the spreadsheet's "prijs per meter/kg" column.
        cost = quantity / 1000 * price if unit == "g" else quantity * price
        parts.append({**line, "unit": unit, "group": group, "cost": _money(cost)})

    print_data = data.get("print") or {}
    depreciation = []
    for i, line in enumerate(_lines(print_data, "depreciation"), 1):
        hours = whole_hours(_num(line.get("hours"), L("cl.dep_hours", i=i)))
        rate = _num(line.get("price_per_hour"), L("cl.dep_rate", i=i))
        depreciation.append({**line, "hours_billed": hours, "cost": _money(hours * rate)})

    energy = []
    for i, line in enumerate(_lines(print_data, "energy"), 1):
        hours = whole_hours(_num(line.get("hours"), L("cl.energy_hours", i=i)))
        kw = _num(line.get("kw"), L("cl.energy_kw", i=i))
        tariff = _num(line.get("price_per_kwh"), L("cl.energy_tariff", i=i))
        energy.append({**line, "hours_billed": hours, "cost": _money(hours * kw * tariff)})

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
    price = price_from_cost(cost_price, margin, vat_rate, rounding)
    margin_amount, sell_price, vat_amount = price["margin_amount"], price["sell_price"], price["vat_amount"]
    effective_pct = price["margin_pct_effective"]

    def fmt(lines):
        return [{**line, "cost": str(line["cost"]),
                 **({"hours_billed": str(line["hours_billed"])} if "hours_billed" in line else {})}
                for line in lines]

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
        "margin_pct": str(margin),                   # as entered (the minimum when rounding)
        "margin_pct_effective": str(effective_pct),
        "margin_amount": str(margin_amount),
        "rounding": rounding,
        "sell_price": str(sell_price),              # excl. VAT
        "vat_pct": str(vat_rate),
        "vat_amount": str(vat_amount),
        "sell_price_incl_vat": str(sell_price + vat_amount),
    }
