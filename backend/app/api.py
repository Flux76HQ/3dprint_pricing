"""Domain API: printers, energy tariffs, filament spools, projects, preferences."""
import json
import re
import uuid
from decimal import Decimal, InvalidOperation

from flask import Blueprint, g, jsonify, request

from . import push
from .calc import ROUNDINGS, calculate
from .http import ApiError, json_body, login_required, pool

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
            raise ApiError(400, f"{label} is verplicht.")
        if len(value) > max_len:
            raise ApiError(400, f"{label} is te lang (maximaal {max_len} tekens).")
        return value
    return check


def number(label, *, minimum=0, strict=False, maximum=10_000_000):
    def check(value):
        try:
            n = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ApiError(400, f"{label}: '{value}' is geen getal.") from None
        if not n.is_finite() or n < minimum or (strict and n == minimum) or n > maximum:
            bound = f"groter dan {minimum}" if strict else f"{minimum} of hoger"
            raise ApiError(400, f"{label}: moet {bound} zijn.")
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
            raise ApiError(400, f"{label}: '{value}' is geen getal.") from None
        if n != n.to_integral_value() or not minimum <= n <= maximum:
            raise ApiError(400, f"{label}: geef een heel getal tussen {minimum} en {maximum}.")
        return int(n)
    return check


def boolean(label):
    def check(value):
        if not isinstance(value, bool):
            raise ApiError(400, f"{label} moet waar of onwaar zijn.")
        return value
    return check


RESOURCES = {
    "printers": ("printers", {
        "name": text("Naam"),
        "purchase_price": number("Aanschafwaarde"),
        "lifetime_hours": number("Levensduur (uren)", strict=True),
        "power_kw": number("Vermogen (kW)", maximum=100),
        "notes": text("Notities", required=False, max_len=1000),
        "archived": boolean("Gearchiveerd"),
    }, "name"),
    "tariffs": ("energy_tariffs", {
        "name": text("Naam"),
        "price_per_kwh": number("Prijs per kWh", maximum=100),
        "is_default": boolean("Standaard"),
    }, "name"),
    "packaging": ("packaging_items", {
        "name": text("Naam"),
        "price": number("Prijs per stuk"),
        "notes": text("Notities", required=False, max_len=1000),
        "archived": boolean("Gearchiveerd"),
    }, "name"),
    "spools": ("filament_spools", {
        "brand": text("Merk/type"),
        "material": text("Materiaal", required=False, max_len=40),
        "colour": text("Kleur", required=False, max_len=40),
        "roll_weight_g": number("Gewicht rol (g)", strict=True),
        "price": number("Prijs rol"),
        "remaining_g": number("Resterend (g)"),
        "barcode": text("Barcode", required=False, max_len=100),
        "diameter_mm": number("Diameter (mm)", strict=True, maximum=5),
        "print_temp_c": optional_int("Printtemperatuur", minimum=0, maximum=500),
        "bed_temp_c": optional_int("Bedtemperatuur", minimum=0, maximum=200),
        "notes": text("Notities", required=False, max_len=1000),
        "archived": boolean("Gearchiveerd"),
    }, "brand, colour"),
}
OPTIONAL = {"notes", "archived", "is_default", "material", "colour", "power_kw", "barcode", "diameter_mm",
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
        return jsonify(_serialise(row)), 201

    def update(item_id):
        values = _validated(fields, json_body(), partial=True)
        if not values:
            raise ApiError(400, "Niets om te wijzigen.")
        sets = ", ".join(f"{k} = %s" for k in values)
        with pool().connection() as conn:
            if values.get("is_default"):
                conn.execute(f"UPDATE {table} SET is_default = false")
            row = conn.execute(f"UPDATE {table} SET {sets} WHERE id = %s RETURNING *",
                               (*values.values(), item_id)).fetchone()
        if row is None:
            raise ApiError(404, "Niet gevonden.")
        return jsonify(_serialise(row))

    def delete(item_id):
        with pool().connection() as conn:
            row = conn.execute(f"DELETE FROM {table} WHERE id = %s RETURNING id", (item_id,)).fetchone()
        if row is None:
            raise ApiError(404, "Niet gevonden.")
        return jsonify({"ok": True})

    bp.add_url_rule(f"/{path}", f"{path}_list", list_all, methods=["GET"])
    bp.add_url_rule(f"/{path}", f"{path}_create", create, methods=["POST"])
    bp.add_url_rule(f"/{path}/<uuid:item_id>", f"{path}_update", update, methods=["PATCH"])
    bp.add_url_rule(f"/{path}/<uuid:item_id>", f"{path}_delete", delete, methods=["DELETE"])


for _path, (_table, _fields, _order) in RESOURCES.items():
    _register(_path, _table, _fields, _order)


def _stock_key(row: dict) -> str:
    """One kind of filament: the barcode when there is one, otherwise brand + material + colour."""
    barcode = (row["barcode"] or "").strip()
    if barcode:
        return f"barcode:{barcode}"
    return "name:" + "|".join((row[k] or "").strip().lower() for k in ("brand", "material", "colour"))


def _stock(rows) -> list[dict]:
    """Per kind of filament: the rolls that still have filament on them (with their weights) and the total.

    Archived rolls are not stock. A roll that is empty is not a roll you still have, but its kind stays in
    the list with 0 g so a sold-out colour does not just vanish."""
    groups: dict[str, dict] = {}
    for row in rows:
        group = groups.setdefault(_stock_key(row), {
            "key": _stock_key(row), "brand": row["brand"], "material": row["material"] or "", "colour": row["colour"] or "",
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
    return sorted(out, key=lambda g: ((g["material"] or "~").lower(), g["brand"].lower(), g["colour"].lower()))


def _stock_rows(conn, barcode: str | None = None):
    sql = ("SELECT id, brand, material, colour, barcode, roll_weight_g, remaining_g FROM filament_spools "
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
    materials: dict[str, dict] = {}
    for g_ in groups:
        name = (g_["material"] or "Onbekend materiaal").strip()
        m = materials.setdefault(name.lower(), {"material": name, "roll_count": 0, "remaining_g": Decimal(0)})   # "PLA" = "pla"
        m["roll_count"] += g_["roll_count"]
        m["remaining_g"] += Decimal(g_["remaining_g"])
    return jsonify({"groups": groups, "materials": [{**m, "remaining_g": str(m["remaining_g"])}
                                                    for m in sorted(materials.values(), key=lambda m: m["material"].lower())]})


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


# --- preferences ----------------------------------------------------------------

THEMES = ("system", "light", "dark")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@bp.get("/preferences")
def get_preferences():
    with pool().connection() as conn:
        row = conn.execute("SELECT preferences FROM users WHERE id = %s", (g.user_id,)).fetchone()
    return jsonify(row["preferences"] if row else {})


@bp.put("/preferences")
def put_preferences():
    body = json_body()
    prefs = {}
    if "theme" in body:
        if body["theme"] not in THEMES:
            raise ApiError(400, "Ongeldig thema.")
        prefs["theme"] = body["theme"]
    if "accent" in body:
        if not isinstance(body["accent"], str) or not HEX.match(body["accent"]):
            raise ApiError(400, "Accentkleur moet een hex-kleur zijn, bijv. #6c5ce7.")
        prefs["accent"] = body["accent"].lower()
    if "vat_pct" in body:
        prefs["vat_pct"] = str(number("Standaard btw-tarief", maximum=100)(body["vat_pct"]))
    if "notify_release" in body:
        prefs["notify_release"] = boolean("Melding bij nieuwe versie")(body["notify_release"])
    if "quiet_hours" in body:
        window = body["quiet_hours"]
        if not isinstance(window, dict) or not isinstance(window.get("enabled"), bool) \
                or not push.valid_window({"tz": window.get("tz"), "start": window.get("start"), "end": window.get("end")}):
            raise ApiError(400, "Stille uren: geef begin en einde als UU:MM en een geldige tijdzone, bijv. Europe/Amsterdam.")
        prefs["quiet_hours"] = {"enabled": window["enabled"], "start": window["start"], "end": window["end"], "tz": window["tz"]}
    if "blur_costs" in body:
        prefs["blur_costs"] = boolean("Kosten blurren")(body["blur_costs"])
    if "auto_adopt_file" in body:
        prefs["auto_adopt_file"] = boolean("Automatisch overnemen")(body["auto_adopt_file"])
    if "price_rounding" in body:
        if body["price_rounding"] not in ROUNDINGS:
            raise ApiError(400, "Ongeldige afronding.")
        prefs["price_rounding"] = body["price_rounding"]
    if "sidebar_collapsed" in body:
        prefs["sidebar_collapsed"] = boolean("Zijbalk")(body["sidebar_collapsed"])
    with pool().connection() as conn:
        row = conn.execute("UPDATE users SET preferences = preferences || %s::jsonb WHERE id = %s "
                           "RETURNING preferences", (json.dumps(prefs), g.user_id)).fetchone()
    return jsonify(row["preferences"])


# --- calculations ---------------------------------------------------------------

def _calc(body):
    data = body.get("data")
    if not isinstance(data, dict):
        raise ApiError(400, "'data' ontbreekt.")
    try:
        return data, calculate(data, body.get("margin_pct", 0), body.get("vat_pct", 0),
                               body.get("price_rounding", "none"))
    except ValueError as exc:
        raise ApiError(400, str(exc)) from None


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
        raise ApiError(404, "Berekening niet gevonden.")
    return jsonify(_project_row(row))


URL = re.compile(r"^https?://[^\s]+$", re.I)


def _project_fields(body):
    name = text("Naam")(body.get("name"))
    source_url = text("Bronlink", required=False, max_len=500)(body.get("source_url"))
    if source_url and not URL.match(source_url):
        raise ApiError(400, "Bronlink moet beginnen met http:// of https://.")
    file_id = body.get("file_id") or None
    if file_id is not None:
        try:
            file_id = uuid.UUID(str(file_id))
        except ValueError:
            raise ApiError(400, "Ongeldig bestand.") from None
        with pool().connection() as conn:
            if conn.execute("SELECT 1 FROM print_files WHERE id = %s", (file_id,)).fetchone() is None:
                raise ApiError(400, "Dat printbestand bestaat niet (meer). Upload het opnieuw.")
    notes = text("Notities", required=False, max_len=2000)(body.get("notes"))
    margin = number("Marge", maximum=1000)(body.get("margin_pct", 0))
    vat = number("BTW", maximum=100)(body.get("vat_pct", 0))
    rounding = body.get("price_rounding", "none")
    if rounding not in ROUNDINGS:
        raise ApiError(400, "Ongeldige afronding.")
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
        raise ApiError(404, "Berekening niet gevonden.")
    return jsonify(_project_row(row))


@bp.delete("/projects/<uuid:project_id>")
def delete_project(project_id):
    with pool().connection() as conn:
        row = conn.execute("DELETE FROM projects WHERE id = %s RETURNING id", (project_id,)).fetchone()
    if row is None:
        raise ApiError(404, "Berekening niet gevonden.")
    return jsonify({"ok": True})


@bp.post("/projects/<uuid:project_id>/book-stock")
def book_stock(project_id):
    """Subtract the project's filament grams from the spools it used, once."""
    with pool().connection() as conn:
        project = conn.execute("SELECT data, stock_booked_at FROM projects WHERE id = %s FOR UPDATE",
                               (project_id,)).fetchone()
        if project is None:
            raise ApiError(404, "Berekening niet gevonden.")
        if project["stock_booked_at"] is not None:
            raise ApiError(409, "Het verbruik van deze berekening is al afgeboekt.")
        used: dict[str, Decimal] = {}
        for line in project["data"].get("filament", []):
            spool_id = line.get("spool_id")
            if spool_id:
                used[spool_id] = used.get(spool_id, Decimal(0)) + Decimal(str(line.get("grams") or 0))
        short = []
        for spool_id, grams in used.items():
            row = conn.execute("SELECT brand, remaining_g FROM filament_spools WHERE id = %s FOR UPDATE",
                               (spool_id,)).fetchone()
            if row is None:
                continue  # spool was deleted since; nothing to subtract from
            if row["remaining_g"] < grams:
                short.append(f"{row['brand']} (nog {row['remaining_g']} g, nodig {grams} g)")
            conn.execute("UPDATE filament_spools SET remaining_g = GREATEST(remaining_g - %s, 0) WHERE id = %s",
                         (grams, spool_id))
        conn.execute("UPDATE projects SET stock_booked_at = now() WHERE id = %s", (project_id,))
    return jsonify({"ok": True, "spools_updated": len(used), "short": short})
