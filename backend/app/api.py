"""Domain API: printers, energy tariffs, filament spools, projects, preferences."""
import json
import re
import uuid
from decimal import Decimal, InvalidOperation

from flask import Blueprint, g, jsonify, request

from . import lowstock, push
from .calc import ROUNDINGS, calculate
from .http import ApiError, config, json_body, login_required, pool
from .i18n import LANGUAGES, L, tr

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.before_request
@login_required
def _guard():
    """Every route in this blueprint needs a session."""


# --- field validation -----------------------------------------------------------

def text(label, *, required=True, max_len=120):
    def check(value):
        value = "" if value is None else str(value).strip()
        if required and not value:
            raise ApiError(400, "err.required", label=L(label))
        if len(value) > max_len:
            raise ApiError(400, "err.too_long", label=L(label), max=max_len)
        return value
    return check


def number(label, *, minimum=0, strict=False, maximum=10_000_000):
    def check(value):
        try:
            n = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ApiError(400, "err.not_number", label=L(label), value=value) from None
        if not n.is_finite() or n < minimum or (strict and n == minimum) or n > maximum:
            raise ApiError(400, "err.gt" if strict else "err.ge", label=L(label), min=minimum)
        return n
    return check


def optional_int(label, *, minimum, maximum):
    """A whole number in range, or None when left empty (stored as NULL)."""
    def check(value):
        if value is None or str(value).strip() == "":
            return None
        try:
            n = Decimal(str(value).replace(",", "."))
        except (InvalidOperation, ValueError):
            raise ApiError(400, "err.not_number", label=L(label), value=value) from None
        if n != n.to_integral_value() or not minimum <= n <= maximum:
            raise ApiError(400, "err.whole_between", label=L(label), min=minimum, max=maximum)
        return int(n)
    return check


def boolean(label):
    def check(value):
        if not isinstance(value, bool):
            raise ApiError(400, "err.bool", label=L(label))
        return value
    return check


RESOURCES = {
    "printers": ("printers", {
        "name": text("f.name"),
        "purchase_price": number("f.purchase_price"),
        "lifetime_hours": number("f.lifetime", strict=True),
        "power_kw": number("f.power", maximum=100),
        "notes": text("f.notes", required=False, max_len=1000),
        "archived": boolean("f.archived"),
    }, "name"),
    "tariffs": ("energy_tariffs", {
        "name": text("f.name"),
        "price_per_kwh": number("f.price_per_kwh", maximum=100),
        "is_default": boolean("f.default"),
    }, "name"),
    "packaging": ("packaging_items", {
        "name": text("f.name"),
        "price": number("f.price_per_piece"),
        "notes": text("f.notes", required=False, max_len=1000),
        "archived": boolean("f.archived"),
    }, "name"),
    "spools": ("filament_spools", {
        "brand": text("f.brand"),
        "product_type": text("f.type", required=False, max_len=60),
        "material": text("f.material", required=False, max_len=40),
        "colour": text("f.colour", required=False, max_len=40),
        "roll_weight_g": number("f.roll_weight", strict=True),
        "price": number("f.roll_price"),
        "remaining_g": number("f.remaining"),
        "barcode": text("f.barcode", required=False, max_len=100),
        "diameter_mm": number("f.diameter", strict=True, maximum=5),
        "print_temp_c": optional_int("f.print_temp", minimum=0, maximum=500),
        "bed_temp_c": optional_int("f.bed_temp", minimum=0, maximum=200),
        "notes": text("f.notes", required=False, max_len=1000),
        "archived": boolean("f.archived"),
    }, "brand, colour"),
}
OPTIONAL = {"notes", "archived", "is_default", "material", "colour", "product_type", "power_kw", "barcode", "diameter_mm",
            "print_temp_c", "bed_temp_c"}


def _serialise(row: dict) -> dict:
    out = {}
    for key, value in row.items():
        if isinstance(value, uuid.UUID):
            out[key] = str(value)
        elif isinstance(value, Decimal):
            out[key] = str(value)
        elif hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def _validated(fields, body, *, partial):
    values = {}
    for name, check in fields.items():
        if name in body:
            values[name] = check(body[name])
        elif not partial and name not in OPTIONAL:
            check(None)  # raises the "is verplicht" message for a missing required field
    return values


def _register(path, table, fields, order):
    def list_all():
        with pool().connection() as conn:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY archived, {order}"
                                if "archived" in fields else f"SELECT * FROM {table} ORDER BY {order}").fetchall()
        return jsonify([_serialise(r) for r in rows])

    def create():
        values = _validated(fields, json_body(), partial=False)
        cols = ", ".join(values)
        marks = ", ".join(["%s"] * len(values))
        with pool().connection() as conn:
            if values.get("is_default"):
                conn.execute(f"UPDATE {table} SET is_default = false")
            elif table == "energy_tariffs" and not conn.execute("SELECT 1 FROM energy_tariffs").fetchone():
                values["is_default"] = True  # the first tariff is the default
                cols, marks = ", ".join(values), ", ".join(["%s"] * len(values))
            row = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks}) RETURNING *",
                               tuple(values.values())).fetchone()
        if table == "filament_spools":
            stock_changed()
        return jsonify(_serialise(row)), 201

    def update(item_id):
        values = _validated(fields, json_body(), partial=True)
        if not values:
            raise ApiError(400, "err.nothing_to_change")
        sets = ", ".join(f"{k} = %s" for k in values)
        with pool().connection() as conn:
            if values.get("is_default"):
                conn.execute(f"UPDATE {table} SET is_default = false")
            row = conn.execute(f"UPDATE {table} SET {sets} WHERE id = %s RETURNING *",
                               (*values.values(), item_id)).fetchone()
        if row is None:
            raise ApiError(404, "err.not_found")
        if table == "filament_spools":
            stock_changed()
        return jsonify(_serialise(row))

    def delete(item_id):
        with pool().connection() as conn:
            row = conn.execute(f"DELETE FROM {table} WHERE id = %s RETURNING id", (item_id,)).fetchone()
        if row is None:
            raise ApiError(404, "err.not_found")
        if table == "filament_spools":
            stock_changed()
        return jsonify({"ok": True})

    bp.add_url_rule(f"/{path}", f"{path}_list", list_all, methods=["GET"])
    bp.add_url_rule(f"/{path}", f"{path}_create", create, methods=["POST"])
    bp.add_url_rule(f"/{path}/<uuid:item_id>", f"{path}_update", update, methods=["PATCH"])
    bp.add_url_rule(f"/{path}/<uuid:item_id>", f"{path}_delete", delete, methods=["DELETE"])


def stock_changed() -> None:
    """Something that changes what is on the shelf was saved: see whether a material has just run low."""
    lowstock.check(pool(), config())


for _path, (_table, _fields, _order) in RESOURCES.items():
    _register(_path, _table, _fields, _order)


def _stock_key(row: dict) -> str:
    """One kind of filament: the barcode when there is one, otherwise brand + type + material + colour."""
    barcode = (row["barcode"] or "").strip()
    if barcode:
        return f"barcode:{barcode}"
    return "name:" + "|".join((row[k] or "").strip().lower() for k in ("brand", "product_type", "material", "colour"))


def _stock(rows) -> list[dict]:
    """Per kind of filament: the rolls that still have filament on them (with their weights) and the total.

    Archived rolls are not stock. A roll that is empty is not a roll you still have, but its kind stays in
    the list with 0 g so a sold-out colour does not just vanish."""
    groups: dict[str, dict] = {}
    for row in rows:
        group = groups.setdefault(_stock_key(row), {
            "key": _stock_key(row), "brand": row["brand"], "product_type": row["product_type"] or "", "material": row["material"] or "", "colour": row["colour"] or "",
            "barcode": (row["barcode"] or "").strip(), "rolls": [], "remaining_g": Decimal(0)})
        if row["remaining_g"] > 0:
            group["rolls"].append({"id": str(row["id"]), "remaining_g": str(row["remaining_g"]),
                                   "roll_weight_g": str(row["roll_weight_g"])})
            group["remaining_g"] += row["remaining_g"]
    out = []
    for group in groups.values():
        group["roll_count"] = len(group["rolls"])
        group["remaining_g"] = str(group["remaining_g"])
        out.append(group)
    return sorted(out, key=lambda g: ((g["material"] or "~").lower(), g["brand"].lower(), g["product_type"].lower(), g["colour"].lower()))


def _stock_rows(conn, barcode: str | None = None):
    sql = ("SELECT id, brand, product_type, material, colour, barcode, roll_weight_g, remaining_g FROM filament_spools "
           "WHERE NOT archived")
    params: tuple = ()
    if barcode is not None:
        sql, params = sql + " AND barcode = %s", (barcode,)
    return conn.execute(sql + " ORDER BY created_at", params).fetchall()


@bp.get("/spools/stock")
def spool_stock():
    """What is left, per kind of filament and per material."""
    with pool().connection() as conn:
        groups = _stock(_stock_rows(conn))
        row = conn.execute("SELECT preferences FROM users WHERE id = %s", (g.user_id,)).fetchone()
    alert = lowstock.settings(row["preferences"] if row else None)
    materials: dict[str, dict] = {}
    for g_ in groups:
        key = lowstock.material_key(g_["material"])           # "" = no material filled in; those are not followed
        name = (g_["material"] or tr("stock.unknown_material")).strip()
        m = materials.setdefault(key or name.lower(), {"material": name, "key": key, "roll_count": 0, "remaining_g": Decimal(0)})   # "PLA" = "pla"
        m["roll_count"] += g_["roll_count"]
        m["remaining_g"] += Decimal(g_["remaining_g"])
    out = []
    for m in sorted(materials.values(), key=lambda m: m["material"].lower()):
        followed = alert is not None and m["key"] != ""
        limit = lowstock.threshold_for(alert, m["key"]) if followed else None
        out.append({**m, "remaining_g": str(m["remaining_g"]), "threshold_g": int(limit) if limit is not None else None,
                    "low": limit is not None and m["remaining_g"] <= limit})
    return jsonify({"groups": groups, "materials": out})


@bp.get("/spools/lookup")
def lookup_spool():
    """The newest roll with this barcode (so a re-purchase can copy its details) and what is in stock of it."""
    barcode = (request.args.get("barcode") or "").strip()
    if not barcode:
        return jsonify({"spool": None, "stock": None})
    with pool().connection() as conn:
        row = conn.execute("SELECT * FROM filament_spools WHERE barcode = %s ORDER BY created_at DESC LIMIT 1",
                           (barcode,)).fetchone()
        stock = _stock(_stock_rows(conn, barcode)) if row else []
    return jsonify({"spool": _serialise(row) if row else None, "stock": stock[0] if stock else None})


# Details of the product, not of one roll: the same barcode means the same brand, type, material, colour,
# weight and diameter. Price, what is left and notes differ per roll and are never passed on.
PRODUCT_FIELDS = ("brand", "product_type", "material", "colour", "roll_weight_g", "diameter_mm", "print_temp_c", "bed_temp_c")


def _barcode_of(conn, spool_id) -> str:
    row = conn.execute("SELECT barcode FROM filament_spools WHERE id = %s", (spool_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.not_found")
    return (row["barcode"] or "").strip()


@bp.get("/spools/<uuid:spool_id>/siblings")
def spool_siblings(spool_id):
    """How many other rolls have the same barcode (none when this roll has no barcode)."""
    with pool().connection() as conn:
        barcode = _barcode_of(conn, spool_id)
        count = conn.execute("SELECT count(*) AS n FROM filament_spools WHERE barcode = %s AND id <> %s",
                             (barcode, spool_id)).fetchone()["n"] if barcode else 0
    return jsonify({"count": count})


@bp.post("/spools/<uuid:spool_id>/propagate")
def propagate_spool(spool_id):
    """Copy the chosen product details of this roll to every other roll with the same barcode."""
    fields = json_body().get("fields")
    if not isinstance(fields, list) or not fields or not all(f in PRODUCT_FIELDS for f in fields):
        raise ApiError(400, "err.propagate_fields")
    fields = list(dict.fromkeys(fields))
    with pool().connection() as conn:
        barcode = _barcode_of(conn, spool_id)
        if not barcode:
            return jsonify({"updated": 0})
        row = conn.execute(f"SELECT {', '.join(fields)} FROM filament_spools WHERE id = %s", (spool_id,)).fetchone()
        sets = ", ".join(f"{name} = %s" for name in fields)
        done = conn.execute(f"UPDATE filament_spools SET {sets} WHERE barcode = %s AND id <> %s RETURNING id",
                            (*[row[name] for name in fields], barcode, spool_id)).fetchall()
    if "material" in fields:                                        # the rolls moved to another material's total
        stock_changed()
    return jsonify({"updated": len(done)})


# --- preferences ----------------------------------------------------------------

THEMES = ("system", "light", "dark")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@bp.get("/preferences")
def get_preferences():
    with pool().connection() as conn:
        row = conn.execute("SELECT preferences FROM users WHERE id = %s", (g.user_id,)).fetchone()
    return jsonify(row["preferences"] if row else {})


def validated_preferences(body: dict) -> dict:
    """The preferences in `body` that are valid, as they will be stored; raises ApiError for a bad value.
    Used by the settings screen and by restoring a backup, so both accept exactly the same things."""
    prefs = {}
    if "theme" in body:
        if body["theme"] not in THEMES:
            raise ApiError(400, "err.theme")
        prefs["theme"] = body["theme"]
    if "accent" in body:
        if not isinstance(body["accent"], str) or not HEX.match(body["accent"]):
            raise ApiError(400, "err.accent")
        prefs["accent"] = body["accent"].lower()
    if "vat_pct" in body:
        prefs["vat_pct"] = str(number("f.default_vat", maximum=100)(body["vat_pct"]))
    if "notify_release" in body:
        prefs["notify_release"] = boolean("f.notify_release")(body["notify_release"])
    if "quiet_hours" in body:
        window = body["quiet_hours"]
        if not isinstance(window, dict) or not isinstance(window.get("enabled"), bool) \
                or not push.valid_window({"tz": window.get("tz"), "start": window.get("start"), "end": window.get("end")}):
            raise ApiError(400, "err.quiet_hours")
        prefs["quiet_hours"] = {"enabled": window["enabled"], "start": window["start"], "end": window["end"], "tz": window["tz"]}
    if "blur_costs" in body:
        prefs["blur_costs"] = boolean("f.blur")(body["blur_costs"])
    if "auto_adopt_file" in body:
        prefs["auto_adopt_file"] = boolean("f.auto_adopt")(body["auto_adopt_file"])
    if "price_rounding" in body:
        if body["price_rounding"] not in ROUNDINGS:
            raise ApiError(400, "err.rounding")
        prefs["price_rounding"] = body["price_rounding"]
    if "language" in body:
        if body["language"] not in LANGUAGES:
            raise ApiError(400, "err.language")
        prefs["language"] = body["language"]
    if "sidebar_collapsed" in body:
        prefs["sidebar_collapsed"] = boolean("f.sidebar")(body["sidebar_collapsed"])
    if "low_stock" in body:
        prefs["low_stock"] = _validated_low_stock(body["low_stock"])
    return prefs


def _validated_low_stock(value) -> dict:
    """On or off, the threshold for every material and the ones that differ per material, all in whole grams."""
    if not isinstance(value, dict) or not isinstance(value.get("enabled"), bool):
        raise ApiError(400, "err.low_stock")
    grams = optional_int("f.low_stock_g", minimum=0, maximum=1_000_000)

    def whole(raw):
        n = grams(raw)
        if n is None:
            raise ApiError(400, "err.required", label=L("f.low_stock_g"))
        return n

    own = value.get("materials", {})
    if not isinstance(own, dict) or len(own) > 100:
        raise ApiError(400, "err.low_stock")
    materials = {}
    for name, raw in own.items():
        key = lowstock.material_key(name)
        if not key or len(key) > 40:
            raise ApiError(400, "err.low_stock")
        materials[key] = whole(raw)
    return {"enabled": value["enabled"], "threshold_g": whole(value.get("threshold_g", lowstock.DEFAULT_THRESHOLD_G)),
            "materials": materials}


@bp.put("/preferences")
def put_preferences():
    prefs = validated_preferences(json_body())
    with pool().connection() as conn:
        row = conn.execute("UPDATE users SET preferences = preferences || %s::jsonb WHERE id = %s "
                           "RETURNING preferences", (json.dumps(prefs), g.user_id)).fetchone()
    if "low_stock" in prefs:
        stock_changed()                                              # switched on or tightened: what is low now is announced now
    return jsonify(row["preferences"])


# --- calculations ---------------------------------------------------------------

def _calc(body):
    data = body.get("data")
    if not isinstance(data, dict):
        raise ApiError(400, "err.data_missing")
    try:
        return data, calculate(data, body.get("margin_pct", 0), body.get("vat_pct", 0),
                               body.get("price_rounding", "none"))
    except ValueError as exc:
        raise ApiError(400, exc) from None


@bp.post("/calculate")
def calculate_endpoint():
    _, totals = _calc(json_body())
    return jsonify(totals)


def _project_row(row):
    return _serialise(row)


@bp.get("/projects")
def list_projects():
    with pool().connection() as conn:
        rows = conn.execute("SELECT id, name, margin_pct, vat_pct, price_rounding, totals, stock_booked_at, updated_at "
                            "FROM projects ORDER BY updated_at DESC").fetchall()
    return jsonify([_project_row(r) for r in rows])


@bp.get("/projects/<uuid:project_id>")
def get_project(project_id):
    with pool().connection() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = %s", (project_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.calc_not_found")
    return jsonify(_project_row(row))


URL = re.compile(r"^https?://[^\s]+$", re.I)


def _project_fields(body):
    name = text("f.name")(body.get("name"))
    source_url = text("f.source_url", required=False, max_len=500)(body.get("source_url"))
    if source_url and not URL.match(source_url):
        raise ApiError(400, "err.source_url")
    file_id = body.get("file_id") or None
    if file_id is not None:
        try:
            file_id = uuid.UUID(str(file_id))
        except ValueError:
            raise ApiError(400, "err.bad_file") from None
        with pool().connection() as conn:
            if conn.execute("SELECT 1 FROM print_files WHERE id = %s", (file_id,)).fetchone() is None:
                raise ApiError(400, "err.file_gone")
    notes = text("f.notes", required=False, max_len=2000)(body.get("notes"))
    margin = number("f.margin", maximum=1000)(body.get("margin_pct", 0))
    vat = number("f.vat", maximum=100)(body.get("vat_pct", 0))
    rounding = body.get("price_rounding", "none")
    if rounding not in ROUNDINGS:
        raise ApiError(400, "err.rounding")
    data, totals = _calc({"data": body.get("data"), "margin_pct": margin, "vat_pct": vat, "price_rounding": rounding})
    return {"name": name, "notes": notes, "margin_pct": margin, "vat_pct": vat, "price_rounding": rounding, "data": data,
            "totals": totals, "source_url": source_url, "file_id": file_id}


@bp.post("/projects")
def create_project():
    f = _project_fields(json_body())
    with pool().connection() as conn:
        row = conn.execute(
            "INSERT INTO projects (name, notes, margin_pct, vat_pct, price_rounding, data, totals, source_url, "
            "file_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (f["name"], f["notes"], f["margin_pct"], f["vat_pct"], f["price_rounding"], json.dumps(f["data"]),
             json.dumps(f["totals"]), f["source_url"], f["file_id"])).fetchone()
    return jsonify(_project_row(row)), 201


@bp.put("/projects/<uuid:project_id>")
def update_project(project_id):
    f = _project_fields(json_body())
    with pool().connection() as conn:
        row = conn.execute(
            "UPDATE projects SET name=%s, notes=%s, margin_pct=%s, vat_pct=%s, price_rounding=%s, data=%s, "
            "totals=%s, source_url=%s, file_id=%s, updated_at=now() WHERE id=%s RETURNING *",
            (f["name"], f["notes"], f["margin_pct"], f["vat_pct"], f["price_rounding"], json.dumps(f["data"]),
             json.dumps(f["totals"]), f["source_url"], f["file_id"], project_id)).fetchone()
    if row is None:
        raise ApiError(404, "err.calc_not_found")
    return jsonify(_project_row(row))


@bp.delete("/projects/<uuid:project_id>")
def delete_project(project_id):
    with pool().connection() as conn:
        row = conn.execute("DELETE FROM projects WHERE id = %s RETURNING id", (project_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.calc_not_found")
    return jsonify({"ok": True})


@bp.post("/projects/<uuid:project_id>/book-stock")
def book_stock(project_id):
    """Subtract the project's filament grams from the spools it used, once."""
    with pool().connection() as conn:
        project = conn.execute("SELECT data, stock_booked_at FROM projects WHERE id = %s FOR UPDATE",
                               (project_id,)).fetchone()
        if project is None:
            raise ApiError(404, "err.calc_not_found")
        if project["stock_booked_at"] is not None:
            raise ApiError(409, "err.already_booked")
        used: dict[str, Decimal] = {}
        for line in project["data"].get("filament", []):
            spool_id = line.get("spool_id")
            if spool_id:
                used[spool_id] = used.get(spool_id, Decimal(0)) + Decimal(str(line.get("grams") or 0))
        short = []
        for spool_id, grams in used.items():
            row = conn.execute("SELECT brand, product_type, remaining_g FROM filament_spools WHERE id = %s FOR UPDATE",
                               (spool_id,)).fetchone()
            if row is None:
                continue  # spool was deleted since; nothing to subtract from
            if row["remaining_g"] < grams:
                short.append(tr("book.short_item", name=" ".join(x for x in (row["brand"], row["product_type"]) if x), left=row["remaining_g"], need=grams))
            conn.execute("UPDATE filament_spools SET remaining_g = GREATEST(remaining_g - %s, 0) WHERE id = %s",
                         (grams, spool_id))
        conn.execute("UPDATE projects SET stock_booked_at = now() WHERE id = %s", (project_id,))
    stock_changed()
    return jsonify({"ok": True, "spools_updated": len(used), "short": short})
