"""What is on the shelf, per kind of filament: rolls with the same barcode are one kind, and their grams add up."""
from decimal import Decimal


def key_of(row: dict) -> str:
    """One kind of filament: the barcode when there is one, otherwise brand + type + material + colour."""
    barcode = (row["barcode"] or "").strip()
    if barcode:
        return f"barcode:{barcode}"
    return "name:" + "|".join((row[k] or "").strip().lower() for k in ("brand", "product_type", "material", "colour"))


def groups(rows) -> list[dict]:
    """Per kind of filament: the rolls that still have filament on them (with their weights) and the total.

    Archived rolls are not stock. A roll that is empty is not a roll you still have, but its kind stays in
    the list with 0 g so a sold-out colour does not just vanish. `notify_low` is on when any roll of the kind has it on."""
    found: dict[str, dict] = {}
    for row in rows:
        group = found.setdefault(key_of(row), {
            "key": key_of(row), "brand": row["brand"], "product_type": row["product_type"] or "", "material": row["material"] or "", "colour": row["colour"] or "",
            "colour_hex": row["colour_hex"] or "", "barcode": (row["barcode"] or "").strip(), "rolls": [], "remaining_g": Decimal(0), "notify_low": False})
        group["notify_low"] = group["notify_low"] or bool(row["notify_low"])
        group["colour_hex"] = group["colour_hex"] or row["colour_hex"] or ""          # the first roll that has a colour gives the kind its colour
        if row["remaining_g"] > 0:
            group["rolls"].append({"id": str(row["id"]), "remaining_g": str(row["remaining_g"]),
                                   "roll_weight_g": str(row["roll_weight_g"])})
            group["remaining_g"] += row["remaining_g"]
    out = []
    for group in found.values():
        group["roll_count"] = len(group["rolls"])
        group["remaining_g"] = str(group["remaining_g"])
        out.append(group)
    return sorted(out, key=lambda g: ((g["material"] or "~").lower(), g["brand"].lower(), g["product_type"].lower(), g["colour"].lower()))


def fetch(conn, barcode: str | None = None):
    """The rolls that count as stock (not archived), optionally only those with this barcode."""
    sql = ("SELECT id, brand, product_type, material, colour, colour_hex, barcode, roll_weight_g, remaining_g, notify_low FROM filament_spools "
           "WHERE NOT archived")
    params: tuple = ()
    if barcode is not None:
        sql, params = sql + " AND barcode = %s", (barcode,)
    return conn.execute(sql + " ORDER BY created_at", params).fetchall()
