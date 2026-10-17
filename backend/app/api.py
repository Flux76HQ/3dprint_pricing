"""Domain API: printers, energy tariffs, filament spools, projects, preferences."""
import json
import re
import uuid
from decimal import Decimal, InvalidOperation

from flask import Blueprint, g, jsonify

from .calc import calculate
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
    "spools": ("filament_spools", {
        "brand": text("Merk/type"),
        "material": text("Materiaal", required=False, max_len=40),
        "colour": text("Kleur", required=False, max_len=40),
        "roll_weight_g": number("Gewicht rol (g)", strict=True),
        "price": number("Prijs rol"),
        "remaining_g": number("Resterend (g)"),
        "notes": text("Notities", required=False, max_len=1000),
        "archived": boolean("Gearchiveerd"),
    }, "brand, colour"),
}
OPTIONAL = {"notes", "archived", "is_default", "material", "colour", "power_kw"}


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
        return data, calculate(data, body.get("margin_pct", 0))
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
        rows = conn.execute("SELECT id, name, margin_pct, totals, stock_booked_at, updated_at "
                            "FROM projects ORDER BY updated_at DESC").fetchall()
    return jsonify([_project_row(r) for r in rows])


@bp.get("/projects/<uuid:project_id>")
def get_project(project_id):
    with pool().connection() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = %s", (project_id,)).fetchone()
    if row is None:
        raise ApiError(404, "Berekening niet gevonden.")
    return jsonify(_project_row(row))


def _project_fields(body):
    name = text("Naam")(body.get("name"))
    notes = text("Notities", required=False, max_len=2000)(body.get("notes"))
    margin = number("Marge", maximum=1000)(body.get("margin_pct", 0))
    data, totals = _calc({"data": body.get("data"), "margin_pct": margin})
    return name, notes, margin, data, totals


@bp.post("/projects")
def create_project():
    name, notes, margin, data, totals = _project_fields(json_body())
    with pool().connection() as conn:
        row = conn.execute(
            "INSERT INTO projects (name, notes, margin_pct, data, totals) VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (name, notes, margin, json.dumps(data), json.dumps(totals))).fetchone()
    return jsonify(_project_row(row)), 201


@bp.put("/projects/<uuid:project_id>")
def update_project(project_id):
    name, notes, margin, data, totals = _project_fields(json_body())
    with pool().connection() as conn:
        row = conn.execute(
            "UPDATE projects SET name=%s, notes=%s, margin_pct=%s, data=%s, totals=%s, updated_at=now() "
            "WHERE id=%s RETURNING *",
            (name, notes, margin, json.dumps(data), json.dumps(totals), project_id)).fetchone()
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
