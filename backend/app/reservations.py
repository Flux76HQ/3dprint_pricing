"""Filament that open orders still have to use: reserved, never booked off.

Nothing is stored. What an order reserves is worked out from its lines whenever it is asked: the filament of each model on the order (the
calculation's filament lines, grams per piece) times the quantity, per kind of filament (`stock.key_of`). An order reserves while its
status is in `OPEN` (`nieuw`, `in_behandeling`, `verwerkt`); at `verstuurd` or `afgehandeld` the print is made, the roll in stock (Spoolman, or the booking
of the calculation) already says so, and the reservation is gone: it lets go by itself when the status changes, the order is deleted or a
line is taken off, because there is no second record that could be forgotten.

Only a line made from a calculation reserves, and not its optional lines (the calculation's accessories, which repeat the model's
`project_id`) nor packaging; a line of a calculation that is gone reserves nothing.
"""
from decimal import Decimal

from . import stock
from .db import id_list

OPEN = ("nieuw", "in_behandeling", "verwerkt")                  # the statuses of an order that has not been printed and sent yet
PLACES = Decimal("0.1")


def _grams(value) -> str:
    return str(Decimal(value).quantize(PLACES))


def _spools(conn, spool_ids) -> dict:
    """The roll rows (also archived ones: a calculation may still name one) that these ids are, by id."""
    ids = sorted({str(s) for s in spool_ids})
    if not ids:
        return {}
    rows = conn.execute("SELECT id, brand, product_type, material, colour, colour_hex, barcode FROM filament_spools "
                        "WHERE id IN (SELECT value FROM json_each(%s))", (id_list(ids),)).fetchall()
    return {str(r["id"]): r for r in rows}


def per_piece(conn, project_ids) -> tuple:
    """What one piece of each calculation takes, per kind of filament: `{project_id: {kind key: grams}}`, plus the roll each kind was
    found through (`names`, to name a kind that has no roll in stock any more). A filament line without a roll is a manual line: it
    names no kind, so it reserves nothing."""
    ids = sorted({str(p) for p in project_ids})
    if not ids:
        return {}, {}
    projects = conn.execute("SELECT id, data FROM projects WHERE id IN (SELECT value FROM json_each(%s))", (id_list(ids),)).fetchall()
    wanted = [line.get("spool_id") for p in projects for line in (p["data"] or {}).get("filament", []) if line.get("spool_id")]
    rolls = _spools(conn, wanted)
    out: dict = {}
    names: dict = {}
    for project in projects:
        kinds: dict = {}
        for line in (project["data"] or {}).get("filament", []):
            roll = rolls.get(str(line.get("spool_id") or ""))
            if roll is None:
                continue
            key = stock.key_of(roll)
            kinds[key] = kinds.get(key, Decimal(0)) + Decimal(str(line.get("grams") or 0))
            names.setdefault(key, roll)
        out[str(project["id"])] = kinds
    return out, names


def _pieces(lines) -> dict:
    """How many pieces of each calculation these order lines ask for: `{project_id: count}`. Only a line that takes filament counts (a model,
    not an optional or a packaging line); the lines are dicts with `project_id`, `quantity` and the flags `optional` and `packaging`."""
    pieces: dict = {}
    for line in lines:
        if line.get("project_id") and not line.get("optional") and not line.get("packaging"):
            key = str(line["project_id"])
            pieces[key] = pieces.get(key, 0) + int(line["quantity"])
    return pieces


def _take(per: dict, pieces: dict) -> dict:
    """What `pieces` take in all, per kind of filament (`{kind key: grams}`), given what one piece of each calculation takes (`per_piece`)."""
    total: dict = {}
    for project_id, count in pieces.items():
        for kind, grams in per.get(project_id, {}).items():
            total[kind] = total.get(kind, Decimal(0)) + grams * count
    return total


def _kind(roll) -> dict:
    """How a kind of filament is named: from a roll, or from the stock's group of that kind."""
    return {"brand": roll["brand"], "product_type": roll["product_type"] or "", "material": roll["material"] or "",
            "colour": roll["colour"] or "", "colour_hex": roll["colour_hex"] or ""}


def needs(conn, lines) -> tuple:
    """What these order lines take in all, per kind of filament: `{kind key: grams}`. A line is a dict with `project_id`, `quantity` and
    the flags `optional` and `packaging`. Also the roll that names each kind."""
    pieces = _pieces(lines)
    per, names = per_piece(conn, pieces)
    return _take(per, pieces), names


def reserved(conn, *, exclude_order=None) -> dict:
    """What the open orders reserve, per kind of filament (`{kind key: Decimal grams}`), the order `exclude_order` left out."""
    sql = ("SELECT l.project_id, l.quantity FROM order_lines l JOIN orders o ON o.id = l.order_id "
           "WHERE o.status IN (SELECT value FROM json_each(%s)) AND l.project_id IS NOT NULL AND NOT l.optional AND NOT l.packaging")
    params: tuple = (id_list(OPEN),)
    if exclude_order is not None:
        sql, params = sql + " AND o.id <> %s", (*params, exclude_order)
    return needs(conn, conn.execute(sql, params).fetchall())[0]


def check(conn, lines, *, status, order_id=None) -> dict:
    """What this order asks of the shelf: per kind of filament how much it takes, what is on the shelf, what the other open orders
    already reserve and what is still missing. `reserving` says whether the order holds the filament at all (only while it is open);
    `short_g` is only given a value for an order that reserves, because a sent order has already used what it used."""
    need, names = needs(conn, lines)
    others = reserved(conn, exclude_order=order_id)
    shelf = {g["key"]: g for g in stock.groups(stock.fetch(conn))}
    reserving = status in OPEN
    kinds = []
    for key in sorted(need, key=lambda k: (shelf.get(k) or names[k])["brand"].lower()):
        group = shelf.get(key)
        roll = group or names[key]
        have = Decimal(group["remaining_g"]) if group else Decimal(0)
        held = others.get(key, Decimal(0))
        kinds.append({"key": key, **_kind(roll), "need_g": _grams(need[key]),
                      "remaining_g": _grams(have), "reserved_others_g": _grams(held),
                      "short_g": _grams(max(need[key] + held - have, Decimal(0))) if reserving else "0.0"})
    return {"reserving": reserving, "kinds": kinds, "short": reserving and any(Decimal(k["short_g"]) > 0 for k in kinds)}


def shortages(conn) -> dict:
    """The open orders that cannot be served from the shelf, for the list of orders: `{order_id: [kind, ...]}`, each kind named as in `check`
    plus `short_g`. The rule is `check`'s for a saved order (what it takes next to what the other open orders hold, against what is on the shelf), so
    the list and the order's own *Filament* card never disagree; it is worked out for every open order at once, from one read of their lines, so the
    list needs no request per order. An order that is not open, takes none of a kind or has enough of it is not in the answer."""
    rows = conn.execute("SELECT l.order_id, l.project_id, l.quantity FROM order_lines l JOIN orders o ON o.id = l.order_id "
                        "WHERE o.status IN (SELECT value FROM json_each(%s)) AND l.project_id IS NOT NULL AND NOT l.optional AND NOT l.packaging",
                        (id_list(OPEN),)).fetchall()
    if not rows:
        return {}
    by_order: dict = {}
    for row in rows:
        by_order.setdefault(row["order_id"], []).append(row)
    per, names = per_piece(conn, {row["project_id"] for row in rows})
    wants = {order_id: _take(per, _pieces(lines)) for order_id, lines in by_order.items()}
    held: dict = {}                                                         # what all the open orders take together, per kind
    for want in wants.values():
        for key, grams in want.items():
            held[key] = held.get(key, Decimal(0)) + grams
    shelf = {g["key"]: g for g in stock.groups(stock.fetch(conn))}
    out: dict = {}
    for order_id, want in wants.items():
        kinds = []
        for key, grams in want.items():
            short = held[key] - (Decimal(shelf[key]["remaining_g"]) if key in shelf else Decimal(0))
            if grams > 0 and short > 0:
                kinds.append({**_kind(shelf.get(key) or names[key]), "short_g": _grams(short)})
        if kinds:
            out[order_id] = sorted(kinds, key=lambda k: (k["brand"].lower(), k["product_type"].lower(), k["colour"].lower()))
    return out


def add_to_stock(conn, groups: list) -> None:
    """Give each kind of the stock list what the open orders hold of it (`reserved_g`) and what is left after that (`available_g`, which
    is negative when more is reserved than there is)."""
    held = reserved(conn)
    for group in groups:
        grams = held.get(group["key"], Decimal(0))
        group["reserved_g"] = _grams(grams)
        group["available_g"] = _grams(Decimal(group["remaining_g"]) - grams)
