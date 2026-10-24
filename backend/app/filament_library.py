"""The filament library: what a filament is (specs and a reference price), apart from the rolls on the shelf.

Plain create / edit / delete of an entry is the generic resource in `api.RESOURCES` ("filament-library"); this module adds what only the
library does: reading a Bambu Lab invoice into entries (and, when asked, into rolls on the shelf), and exporting / importing the library
as a JSON file. An entry is matched on its SKU, else its barcode, else brand + material + type + colour + refill, so the same filament
is never added twice by an import.
"""
import json
from datetime import datetime, timezone
from decimal import Decimal

import requests
from flask import Blueprint, Response, jsonify, request

from . import bambu_invoice
from .api import RESOURCES, _share_notify, _validated, number, optional_int, stock_changed
from .http import ApiError, config, json_body, login_required, pool
from .i18n import Localized, tr

bp = Blueprint("filament_library", __name__, url_prefix="/api/filament-library")

TABLE, FIELDS = RESOURCES["filament-library"][:2]
FORMAT = "printpricing-filament-library"
FORMAT_VERSION = 1
MAX_ROWS = 5_000
DEFAULTS = {"roll_weight_g": 1000, "diameter_mm": 1.75}          # an entry in a hand-written file may leave these out
BLANK = {"product_type": "", "material": "", "colour": "", "colour_hex": "", "filament_id": "", "sku": "", "barcode": "", "refill": False,
         "print_temp_c": None, "bed_temp_c": None, "price": None, "notes": ""}      # what a validated entry lacks when the input left it out


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


def identity(values: dict) -> tuple:
    """What makes two entries the same filament: the shop's SKU, else the barcode, else the supplier's filament ID, else its name."""
    brand = (values.get("brand") or "").strip().lower()
    sku = (values.get("sku") or "").strip().lower()
    if sku:
        return ("sku", brand, sku)
    barcode = (values.get("barcode") or "").strip()
    if barcode:
        return ("barcode", barcode)
    material, kind = (values.get("material") or "").strip().lower(), (values.get("product_type") or "").strip().lower()
    fid = (values.get("filament_id") or "").strip().lower()
    if fid:                                            # a refill and a roll with spool share the ID, hence `refill`
        return ("id", brand, fid, material, kind, bool(values.get("refill")))
    return ("name", brand, *((values.get(k) or "").strip().lower() for k in ("material", "product_type", "colour")), bool(values.get("refill")))


def _existing(conn) -> dict:
    return {identity(r): r for r in conn.execute(f"SELECT * FROM {TABLE} ORDER BY created_at, id").fetchall()}


def _insert(conn, values: dict):
    return conn.execute(f"INSERT INTO {TABLE} ({', '.join(values)}) VALUES ({', '.join(['%s'] * len(values))}) RETURNING *",
                        tuple(values.values())).fetchone()


def _update(conn, item_id, values: dict):
    return conn.execute(f"UPDATE {TABLE} SET {', '.join(f'{k} = %s' for k in values)} WHERE id = %s RETURNING *",
                        (*values.values(), item_id)).fetchone()


def _differs(row: dict, values: dict) -> bool:
    """Whether saving `values` would change `row`: 1000 and Decimal('1000.0') are the same weight."""
    def same(a, b):
        if isinstance(a, bool) or isinstance(b, bool) or not (isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal))):
            return a == b
        return Decimal(str(a)) == Decimal(str(b))
    return any(not same(row[k], v) for k, v in values.items())


# --- export / import as JSON -------------------------------------------------------------------------------------

def _plain(value):
    """Numbers are numbers in the file (the API sends them as text), so it can be read and edited by hand."""
    return float(value) if isinstance(value, Decimal) else value


def _app_version() -> str:
    from . import VERSION, _commit                        # imported here: the package imports this module while it is being set up
    return f"{VERSION} ({_commit()})"


@bp.get("/export")
def export():
    with pool().connection() as conn:
        rows = conn.execute(f"SELECT {', '.join(FIELDS)} FROM {TABLE} ORDER BY lower(brand), lower(material), lower(product_type), lower(colour), sku").fetchall()
    doc = {"format": FORMAT, "format_version": FORMAT_VERSION, "app_version": _app_version(),
           "created_at": datetime.now(timezone.utc).isoformat(),
           "filaments": [{k: _plain(v) for k, v in row.items()} for row in rows]}
    name = f"printpricing-filaments-{datetime.now().strftime('%Y-%m-%d')}.json"
    return Response(json.dumps(doc, ensure_ascii=False, indent=1), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _parse_library(doc) -> list[dict]:
    """The whole file checked with the rules of typing an entry in by hand; nothing is written here."""
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ApiError(400, "library.not_library")
    version = doc.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ApiError(400, "library.not_library")
    if version > FORMAT_VERSION:
        raise ApiError(400, "library.too_new", version=str(doc.get("app_version", "?"))[:40])
    rows = doc.get("filaments")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ApiError(400, "library.bad_list", max=MAX_ROWS)
    out = []
    for n, row in enumerate(rows, 1):
        try:
            if not isinstance(row, dict):
                raise Localized("backup.bad_row_type")
            out.append(_validated(FIELDS, {**DEFAULTS, **row}, partial=False))
        except (ApiError, Localized) as exc:
            reason = exc.msg if hasattr(exc, "msg") else str(exc)
            raise ApiError(400, "library.bad_row", n=n, reason=reason) from None
    return out


def _merge(conn, items: list[dict], *, write: bool) -> dict:
    """Add what is new and bring what is already there in line with the file. Nothing is ever deleted."""
    known = _existing(conn)
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    for values in items:
        key = identity(values)
        row = known.get(key)
        if row is None:
            counts["added"] += 1
            known[key] = {**{k: None for k in FIELDS}, **values, "id": None} if not write else _insert(conn, values)
        elif _differs(row, values):
            counts["updated"] += 1
            known[key] = {**row, **values} if not write else _update(conn, row["id"], values)
        else:
            counts["unchanged"] += 1
    return counts


@bp.post("/import")
def import_library():
    items = _parse_library(json_body())
    dry_run = request.args.get("dry_run") == "1"
    with pool().connection() as conn:
        counts = _merge(conn, items, write=not dry_run)
    return jsonify({"ok": True, "dry_run": dry_run, **counts})


# --- sync from GitHub --------------------------------------------------------------------------------------------

MAX_REMOTE_BYTES = 2 * 1024 * 1024


def _remote() -> dict:
    """The shared library file from `FILAMENT_LIBRARY_URL`. The address comes from the server's configuration (https, a GitHub raw host:
    see `config._library_url`) and never from the request, and a redirect is not followed, so this can only ever read that one file."""
    url = config().filament_library_url
    if not url:
        raise ApiError(404, "library.sync_off")
    try:
        with requests.get(url, timeout=15, allow_redirects=False, stream=True,
                          headers={"Accept": "application/json", "User-Agent": "3dprint-pricing"}) as res:
            if res.status_code != 200:
                raise ApiError(502, "library.sync_status", code=res.status_code)
            data = b""
            for chunk in res.iter_content(65536):
                data += chunk
                if len(data) > MAX_REMOTE_BYTES:
                    raise ApiError(502, "library.sync_too_big")
    except requests.RequestException:
        raise ApiError(502, "library.sync_failed") from None
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError:
        raise ApiError(502, "library.sync_not_json") from None


@bp.get("/source")
def source():
    """Where Sync reads from; empty when it is switched off."""
    return jsonify({"url": config().filament_library_url})


@bp.post("/sync")
def sync():
    """Merge the shared library into this one: new filaments are added and known ones get what the file says; nothing is deleted."""
    items = _parse_library(_remote())
    dry_run = request.args.get("dry_run") == "1"
    with pool().connection() as conn:
        counts = _merge(conn, items, write=not dry_run)
    return jsonify({"ok": True, "dry_run": dry_run, **counts})


# --- Bambu Lab invoice -------------------------------------------------------------------------------------------

@bp.post("/invoice")
def read_invoice():
    """What a Bambu Lab invoice holds, checked against the library and the shelf. Nothing is written."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ApiError(400, "files.pick")
    try:
        invoice = bambu_invoice.read(upload.stream.read(bambu_invoice.MAX_BYTES + 1))
    except Localized as exc:
        raise ApiError(422, exc) from None
    with pool().connection() as conn:
        known = _existing(conn)
        rolls = 0
        if invoice["order_number"]:
            rolls = conn.execute("SELECT count(*) AS n FROM filament_spools WHERE position(%s in notes) > 0",
                                 (invoice["order_number"],)).fetchone()["n"]
    for line in invoice["lines"]:
        match = known.get(identity(line))
        line["library_id"] = str(match["id"]) if match else None
    invoice["rolls_on_shelf"] = rolls                    # rolls already made from this very invoice: importing it twice doubles the shelf
    if invoice["total"] is not None and invoice["total"] != invoice["lines_total"]:
        invoice["warning"] = tr("bambu.warn_total", lines=invoice["lines_total"], invoice=invoice["total"])
    return jsonify(invoice)


ROLLS = optional_int("f.rolls", minimum=0, maximum=99)
PAID = number("f.roll_price")


@bp.post("/invoice/apply")
def apply_invoice():
    """Put the chosen lines of an invoice in the library (a known entry only gets the newer price and what it was missing)
    and, for the lines that say how many rolls came in, those rolls on the shelf at the price that was paid."""
    body = json_body()
    lines = body.get("lines")
    if not isinstance(lines, list) or not lines or len(lines) > bambu_invoice.MAX_LINES:
        raise ApiError(400, "bambu.err_no_lines")
    order = str(body.get("order_number") or "").strip()[:60]
    parsed = []
    for n, line in enumerate(lines, 1):
        if not isinstance(line, dict):
            raise ApiError(400, "backup.bad_row_type")
        try:
            entry = {**BLANK, **_validated(FIELDS, {**DEFAULTS, **line}, partial=False)}
            rolls = ROLLS(line.get("rolls")) or 0
            paid = PAID(line.get("paid_price")) if rolls else None
        except ApiError as exc:
            raise ApiError(400, "library.bad_row", n=n, reason=exc.msg) from None
        parsed.append((entry, bool(line.get("add_to_library", True)), rolls, paid))
    counts = {"added": 0, "updated": 0, "unchanged": 0, "rolls": 0}
    with pool().connection() as conn:
        known = _existing(conn)
        for entry, add, rolls, paid in parsed:
            row = known.get(identity(entry))
            if add:
                if row is None:
                    row = known[identity(entry)] = _insert(conn, entry)
                    counts["added"] += 1
                else:
                    fill = {k: entry[k] for k in ("sku", "filament_id", "barcode") if not row[k] and entry[k]}
                    change = {"price": entry["price"], **fill}
                    if entry["price"] is not None and _differs(row, change):
                        row = known[identity(entry)] = _update(conn, row["id"], change)
                        counts["updated"] += 1
                    else:
                        counts["unchanged"] += 1
            spec = row if row is not None else entry
            for _ in range(rolls):
                spool = conn.execute(
                    "INSERT INTO filament_spools (brand, product_type, material, colour, colour_hex, roll_weight_g, price, remaining_g, barcode, "
                    "diameter_mm, print_temp_c, bed_temp_c, notes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                    (spec["brand"], spec["product_type"], spec["material"], spec["colour"], spec["colour_hex"], spec["roll_weight_g"],
                     paid, spec["roll_weight_g"], spec["barcode"], spec["diameter_mm"], spec["print_temp_c"], spec["bed_temp_c"],
                     tr("bambu.note", order=order) if order else "")).fetchone()
                _share_notify(conn, spool, explicit=False, creating=True)     # a new roll takes over the notification its kind already has
                counts["rolls"] += 1
    if counts["rolls"]:
        stock_changed()
    return jsonify({"ok": True, **counts})
