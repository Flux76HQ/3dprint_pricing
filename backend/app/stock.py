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
    the list with 0 g so a sold-out colour does not just vanish. `notify_low` is on when any roll of the kind has it on.
    `spool_ids` names every roll of the kind (a calculation line points at one of them and means the kind).

    The rolls of a kind may be in different groups (the bins and shelves of `filament_groups`): `groups` names every group a roll of the kind is in
    (empty rolls too, none for a roll out of any group), and `by_group` says what is in each one (`""` for the rolls out of any group; keyed on the
    name in lower case, the way groups are found): its rolls, their number and the grams, so a list filtered on a group shows what is *there*."""
    found: dict[str, dict] = {}
    for row in rows:
        group = found.setdefault(key_of(row), {
            "key": key_of(row), "brand": row["brand"], "product_type": row["product_type"] or "", "material": row["material"] or "", "colour": row["colour"] or "",
            "colour_hex": row["colour_hex"] or "", "barcode": (row["barcode"] or "").strip(), "rolls": [], "spool_ids": [], "remaining_g": Decimal(0),
            "notify_low": False, "groups": [], "by_group": {}})
        group["spool_ids"].append(str(row["id"]))                                     # every roll of the kind, the empty ones too
        group["notify_low"] = group["notify_low"] or bool(row["notify_low"])
        group["colour_hex"] = group["colour_hex"] or row["colour_hex"] or ""          # the first roll that has a colour gives the kind its colour
        name = (row["group_name"] or "").strip() if "group_name" in row.keys() else ""
        here = group["by_group"].setdefault(name.lower(), {"group": name, "rolls": [], "remaining_g": Decimal(0)})
        if name and name not in group["groups"]:
            group["groups"].append(name)
        if row["remaining_g"] > 0:
            roll = {"id": str(row["id"]), "remaining_g": str(row["remaining_g"]), "roll_weight_g": str(row["roll_weight_g"]), "group": name}
            group["rolls"].append(roll)
            group["remaining_g"] += row["remaining_g"]
            here["rolls"].append(roll)
            here["remaining_g"] += row["remaining_g"]
    out = []
    for group in found.values():
        group["roll_count"] = len(group["rolls"])
        group["remaining_g"] = str(group["remaining_g"])
        group["groups"].sort(key=str.lower)
        for here in group["by_group"].values():
            here["roll_count"] = len(here["rolls"])
            here["remaining_g"] = str(here["remaining_g"])
        out.append(group)
    return sorted(out, key=lambda g: ((g["material"] or "~").lower(), g["brand"].lower(), g["product_type"].lower(), g["colour"].lower()))


def fetch(conn, barcode: str | None = None):
    """The rolls that count as stock (not archived), optionally only those with this barcode."""
    sql = ("SELECT s.id, s.brand, s.product_type, s.material, s.colour, s.colour_hex, s.barcode, s.roll_weight_g, s.remaining_g, s.notify_low, s.bambu_id, "
           "COALESCE(g.name, '') AS group_name FROM filament_spools s LEFT JOIN filament_groups g ON g.id = s.group_id WHERE NOT s.archived")
    params: tuple = ()
    if barcode is not None:
        sql, params = sql + " AND s.barcode = %s", (barcode,)
    return conn.execute(sql + " ORDER BY s.created_at", params).fetchall()
