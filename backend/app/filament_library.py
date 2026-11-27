"""The filament library: what a filament is (specs and a reference price), apart from the rolls on the shelf.

Plain create / edit / delete of an entry is the generic resource in `api.RESOURCES` ("filament-library"); this module adds what only the
library does: reading a Bambu Lab invoice into entries, syncing from GitHub, and exporting / importing the library as a JSON file.
Only the owner's own choices touch the rolls on the shelf (`filament_spools`): a roll is made from an entry by hand in the roll form, a line of an
invoice may put rolls on the shelf when it is told to (`apply_invoice`, the record of it is `invoice_imports`), and a roll that fits two entries is
given the barcode of the one the owner picks (`from_rolls`). The library itself is a separate list of the filaments that exist. An entry is matched on its SKU, else its barcode, else its filament ID, else brand + material +
type + colour + refill, so the same filament is never added twice by an import.
"""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import requests
from flask import Blueprint, Response, jsonify, request

from . import bambu_invoice, bambu_store
from .api import BULK_MAX_ROLLS, RESOURCES, _validated, insert_rolls, stock_changed
from .colour_names import loose_kind, to_english
from .config import CONTRIBUTE_URL, DEFAULT_LIBRARY_URL
from .db import id_list
from .http import ApiError, config, json_body, login_required, pool
from .i18n import L, Localized, tr

bp = Blueprint("filament_library", __name__, url_prefix="/api/filament-library")

TABLE, FIELDS = RESOURCES["filament-library"][:2]
FORMAT = "printpricing-filament-library"
FORMAT_VERSION = 1
MAX_ROWS = 5_000
DEFAULTS = {"roll_weight_g": 1000, "diameter_mm": 1.75}          # an entry in a hand-written file may leave these out
BLANK = {"product_type": "", "material": "", "colour": "", "colour_hex": "", "filament_id": "", "sku": "", "barcode": "", "refill": False,
         "print_temp_c": None, "bed_temp_c": None, "price": None, "notes": "", "spoolmandb_id": ""}      # what a validated entry lacks when the input left it out


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


FILLABLE = ("sku", "filament_id", "barcode", "colour_hex", "print_temp_c", "bed_temp_c", "spoolmandb_id")      # what an entry may be given when it lacks it


def _n(values: dict, key: str) -> str:
    return (values.get(key) or "").strip().lower()


def _num(value) -> str:
    return format(Decimal(str(value)).normalize(), "f") if value not in (None, "") else ""


def _kind(values: dict) -> tuple:
    """Brand, material, type, colour, weight and diameter: what a roll says about its filament (a roll has no refill or SKU)."""
    return (_n(values, "brand"), _n(values, "material"), _n(values, "product_type"), _n(values, "colour"),
            _num(values.get("roll_weight_g")), _num(values.get("diameter_mm")))


def keys(values: dict) -> list[tuple]:
    """Every way an entry is recognised, most certain first. Two entries that share *one* of them are the same filament: the shop's SKU, the
    barcode, the supplier's filament ID (a refill and a roll with spool share it, hence `refill`), or the name with its weight and diameter."""
    found = []
    if _n(values, "sku"):
        found.append(("sku", _n(values, "brand"), _n(values, "sku")))
    if _n(values, "barcode"):
        found.append(("barcode", _n(values, "barcode")))
    if _n(values, "filament_id"):
        found.append(("id", _n(values, "brand"), _n(values, "filament_id"), _n(values, "material"), _n(values, "product_type"), bool(values.get("refill"))))
    found.append(("name", *_kind(values), bool(values.get("refill"))))
    return found


def name_of(values: dict) -> str:
    return " · ".join(v for v in (values.get("brand"), values.get("product_type"), values.get("colour"), values.get("material")) if v)


class Index:
    """The entries of the library by each of their keys, to find the one a new or changed entry would be a copy of."""

    def __init__(self, rows=()):
        self.by: dict[tuple, list] = {}
        for row in rows:
            self.add(row)

    def add(self, row: dict) -> None:
        for key in keys(row):
            self.by.setdefault(key, []).append(row)

    def drop(self, row: dict) -> None:
        for key in keys(row):
            self.by[key] = [r for r in self.by.get(key, []) if r is not row]

    def find(self, values: dict, *, only=None, skip=None) -> "dict | None":
        """The first entry that shares a key with `values` (only these keys, when given), other than `skip`."""
        for key in keys(values):
            if only is None or key in only:
                for row in self.by.get(key, ()):
                    if row is not skip:
                        return row
        return None

    def clash(self, row: dict, merged: dict) -> "dict | None":
        """The entry that `row` would become a copy of once it looks like `merged`. Only what is new counts: two entries that were
        already alike (from before this check existed) can still be edited."""
        return self.find(merged, only=set(keys(merged)) - set(keys(row)), skip=row)


class Loose:
    """The entries of the library by what `colour_names.loose_kind` says they are (and whether they are a refill), to find a filament under its name in the
    other language: an invoice line "Grijs" is the library's "Gray". It is only used where something is being *added* from outside (the invoice import), after
    `Index` found nothing; `keys` and the restore check stay exact, because a restore refuses what `keys` calls a copy."""

    def __init__(self, rows=()):
        self.by: dict[tuple, list] = {}
        for row in rows:
            self.add(row)

    @staticmethod
    def key(values: dict) -> tuple:
        return loose_kind(values), bool(values.get("refill"))

    def add(self, row: dict) -> None:
        self.by.setdefault(self.key(row), []).append(row)

    def drop(self, row: dict) -> None:
        self.by[self.key(row)] = [r for r in self.by.get(self.key(row), []) if r is not row]

    def find(self, values: dict) -> "dict | None":
        found = self.by.get(self.key(values))
        return found[0] if found else None


def _duplicate(other: dict) -> ApiError:
    return ApiError(409, "library.duplicate", name=name_of(other))


def _rows(conn) -> list[dict]:
    return conn.execute(f"SELECT * FROM {TABLE} ORDER BY created_at, id").fetchall()


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


def _blank(value) -> bool:
    return value is None or str(value).strip() == ""


def before_create(conn, values: dict) -> None:
    """Typing in a new entry (the generic resource calls this before it inserts): refused when it is a filament that is already there."""
    other = Index(_rows(conn)).find({**BLANK, **DEFAULTS, **values})
    if other:
        raise _duplicate(other)


def before_update(conn, item_id, values: dict) -> None:
    """Changing an entry: refused when it would become a copy of another one."""
    rows = _rows(conn)
    row = next((r for r in rows if r["id"] == item_id), None)
    other = row and Index(rows).clash(row, {**row, **values})
    if other:
        raise _duplicate(other)


def first_clash(rows: list[dict]) -> "tuple[int, dict] | None":
    """(position, the earlier entry) of the first entry of a list that is a copy of one before it; used before a restore."""
    index = Index()
    for n, values in enumerate(rows, 1):
        full = {**BLANK, **DEFAULTS, **values}
        other = index.find(full)
        if other:
            return n, other
        index.add(full)
    return None


def complete(conn, index: Index, row: dict, source: dict, *, price=None) -> dict:
    """Give an entry that already exists what it is missing, from `source` (the same filament as an invoice line or a roll says it): the
    fields in FILLABLE that are empty, and the reference `price` when one is given. Nothing that is filled in is overwritten. Returns the
    entry as it is now."""
    change = {k: source[k] for k in FILLABLE if _blank(row[k]) and not _blank(source.get(k))}
    if price is not None:
        change["price"] = price
    if not change or not _differs(row, change):
        return row
    merged = {**row, **change}
    other = index.clash(row, merged)
    if other:
        raise _duplicate(other)
    index.drop(row)
    updated = _update(conn, row["id"], change)
    index.add(updated)
    return updated


def _match(rows: list[dict], roll: dict, extra=None) -> "tuple[dict, list[dict]]":
    """(what the roll says about its filament, the library entries it could be): the same barcode is the same filament; so is the same SpoolmanDB
    id; without either, the same brand, material, type, colour, weight and diameter, as a refill or not (`extra["refill"]`, when it is known, makes
    that exact), with the colour read in either language."""
    extra = extra if isinstance(extra, dict) else {}
    refill = extra["refill"] if isinstance(extra.get("refill"), bool) else None
    spec = {**BLANK, **{k: roll[k] for k in ("brand", "product_type", "material", "colour", "colour_hex", "barcode", "roll_weight_g",
                                              "diameter_mm", "print_temp_c", "bed_temp_c", "spoolmandb_id")},
            "filament_id": str(extra.get("filament_id") or "").strip()[:20], "refill": bool(refill)}
    code, source = _n(spec, "barcode"), spec["spoolmandb_id"]
    found = [r for r in rows if code and _n(r, "barcode") == code] or \
        [r for r in rows if source and r["spoolmandb_id"] == source and (refill is None or r["refill"] == refill)] or \
        [r for r in rows if loose_kind(r) == loose_kind(spec) and (refill is None or r["refill"] == refill)]
    return spec, found


def _place(conn, roll: dict, extra=None, *, chosen=None) -> "tuple[str, dict | None]":
    """What `add_roll` does, and the entry the roll turned out to be (None when it was added, or when it is not clear which one it is).
    `chosen` is the id of the entry the owner says this roll is: it settles a roll that fits more than one, and it must be one of them."""
    rows = _rows(conn)
    index = Index(rows)
    spec, found = _match(rows, roll, extra)
    if chosen is not None:
        found = [r for r in found if str(r["id"]) == str(chosen)]
        if not found:                                              # the choice is not (any more) one of the entries it could be: never a new entry
            return "unclear", None
    if not found:
        index.add(_insert(conn, {k: v for k, v in spec.items() if k in FIELDS and k not in ("price", "notes", "sku")}))
        return "added", None
    if len(found) > 1:
        return "unclear", None
    try:
        updated = complete(conn, index, found[0], spec)
    except ApiError:                                              # it would clash with another entry: leave the entry as it is
        return "unclear", None
    return ("unchanged" if updated is found[0] else "updated"), updated


def add_roll(conn, roll: dict, extra=None) -> str:
    """A roll typed in by hand may go in the library too: when the filament is not there yet it is added (what the roll says about the
    filament, never what it cost or what is left), and when it is, that entry gets what it was missing. The same barcode is the same
    filament; so is the same SpoolmanDB id (`spoolmandb_id`: its id says weight and diameter too); without either, the same brand, material,
    type, colour, weight and diameter, as a refill or not, **with the colour read in either language** (`colour_names.loose_kind`: a roll
    "Yellow" picked from SpoolmanDB is the library's "Geel", which is completed and not added a second time; `keys` stays exact, because
    a restore refuses what it calls a copy). When that is more than one
    entry (a refill and a roll with spool), it is not clear which one this roll is, so none is touched. `extra` is what the form knows
    about the filament that a roll does not hold: its supplier `filament_id` and whether it is a `refill` (from the Bambu Lab shop); with a
    `refill` the match is exact, so that is no longer unclear. Returns what happened: `added`, `updated`, `unchanged` or `unclear`."""
    return _place(conn, roll, extra)[0]


# --- export / import as JSON -------------------------------------------------------------------------------------

def _plain(value):
    """Numbers are numbers in the file (the API sends them as text), so it can be read and edited by hand."""
    return float(value) if isinstance(value, Decimal) else value


def _app_version() -> str:
    from . import VERSION, _commit                        # imported here: the package imports this module while it is being set up
    return f"{VERSION} ({_commit()})"


@bp.get("/export")
def export():
    with pool().read() as conn:
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
    """Add what is new and bring what is already there in line with the file. Nothing is ever deleted. A line of the file is the same
    filament as an entry when they share a key (see `keys`); a change that would make an entry a copy of another one is refused, with its line."""
    index = Index(_rows(conn))
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    for n, values in enumerate(items, 1):
        row = index.find(values)
        if row is None:
            counts["added"] += 1
            index.add(_insert(conn, values) if write else {**BLANK, **values, "id": None})
            continue
        merged = {**row, **values}
        other = index.clash(row, merged)
        if other:
            raise ApiError(400, "library.bad_row", n=n, reason=L("library.duplicate", name=name_of(other)))
        if _differs(row, values):
            counts["updated"] += 1
            index.drop(row)
            index.add(_update(conn, row["id"], values) if write else merged)
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


def _contribute_url() -> str:
    """Where a contribution goes: only the shared library of this project has an issue form behind it, so a source of the owner's own has none."""
    return CONTRIBUTE_URL if config().filament_library_url == DEFAULT_LIBRARY_URL else ""


@bp.get("/source")
def source():
    """Where Sync reads from (empty when it is switched off) and where a contribution goes (empty when there is no place for it)."""
    return jsonify({"url": config().filament_library_url, "contribute_url": _contribute_url()})


@bp.post("/sync")
def sync():
    """Merge the shared library into this one: new filaments are added and known ones get what the file says; nothing is deleted."""
    items = _parse_library(_remote())
    dry_run = request.args.get("dry_run") == "1"
    with pool().connection() as conn:
        counts = _merge(conn, items, write=not dry_run)
    return jsonify({"ok": True, "dry_run": dry_run, **counts})


@bp.post("/contribution")
def contribution():
    """What this library has that the shared one lacks, to offer as a contribution: the entries as the export writes them, but without the
    notes (they are the owner's own). Which filament is "the same" is `keys()`, as everywhere. Nothing is written and no roll is touched."""
    if not _contribute_url():
        raise ApiError(404, "library.contribute_off")
    shared = Index({**BLANK, **DEFAULTS, **item} for item in _parse_library(_remote()))
    with pool().connection() as conn:
        rows = _rows(conn)
    missing = [row for row in rows if shared.find(row) is None]
    entries = [{k: _plain(row[k]) for k in FIELDS if k != "notes"} for row in missing]
    return jsonify({"entries": entries, "already_there": len(rows) - len(missing)})


# --- the rolls on the shelf ---------------------------------------------------------------------------------------

def _taggable(roll: dict) -> bool:
    """Whether a roll may be given a barcode by a choice: only one that has none (a barcode that is there was typed or scanned), and not one that
    Spoolman or the Bambu cloud keeps (a sync would put it back)."""
    return not (roll["barcode"] or "").strip() and roll["spoolman_id"] is None and roll["bambu_id"] is None


def _offer(roll: dict, found: list[dict]) -> dict:
    """A roll that fits more than one entry, with those entries, for the owner to choose from (`taggable`: a choice would give the roll the barcode of the entry)."""
    def entry(row: dict) -> dict:
        return {"id": str(row["id"]), **{k: _plain(row[k]) for k in FIELDS if k != "notes"}}
    return {"id": str(roll["id"]), "taggable": _taggable(roll),
            **{k: _plain(roll[k]) for k in ("brand", "product_type", "material", "colour", "colour_hex", "barcode", "roll_weight_g", "diameter_mm", "price", "remaining_g")},
            "candidates": [entry(row) for row in found]}


def _tag(conn, roll: dict, entry: dict) -> bool:
    """The roll the owner says is this entry gets its barcode, so it is never unclear again (see `_taggable`); returns whether the roll changed."""
    code = (entry["barcode"] or "").strip()
    if not code or not _taggable(roll):
        return False
    conn.execute("UPDATE filament_spools SET barcode = %s WHERE id = %s", (code, roll["id"]))
    return True


def _choices(body) -> dict[str, str]:
    """`{"choices": {roll id: entry id}}`: which entry the owner says a roll is. Nothing else is read from the body."""
    choices = body.get("choices") if isinstance(body, dict) else None
    if choices is None:
        return {}
    if not isinstance(choices, dict) or len(choices) > MAX_ROWS or not all(isinstance(k, str) and isinstance(v, str) for k, v in choices.items()):
        raise ApiError(400, "library.bad_choice")
    return choices


@bp.post("/from-rolls")
def from_rolls():
    """Put the filaments of the rolls in the filament list (not archived: those are on the shelf) in the library, so they can be shared too.
    Each roll goes through `add_roll`: a filament that is not there yet is added with what the roll says about it (never its price or what is
    left), one that is there only gets what it lacked, and a roll that cannot be told from more than one entry is left out and counted as
    `unclear`, with the entries it could be in `unclear_rolls` (the invoice's data of each: SKU, filament ID, refill, barcode, price).
    The owner settles such a roll with `choices` ({roll id: entry id}, the entry must be one of those): the entry is completed from the roll, and
    the roll is given the entry's barcode (`_tag`: the only thing here that changes a roll, only on that choice, only when it has none), counted as
    `tagged`; a choice that is not one of the roll's entries is refused (400, nothing changes). Rolls without a choice are only read.
    With `dry_run=1` everything is done and then rolled back, so the counts are exact."""
    dry_run = request.args.get("dry_run") == "1"
    choices = _choices(request.get_json(silent=True))
    counts = {"added": 0, "updated": 0, "unchanged": 0, "unclear": 0, "tagged": 0}
    unclear = []
    with pool().connection() as conn:
        rolls = conn.execute("SELECT * FROM filament_spools WHERE NOT archived ORDER BY created_at, id").fetchall()
        rows = _rows(conn)
        for roll in rolls:                                         # what each choice may be is settled before anything is written
            wanted = choices.get(str(roll["id"]))
            if wanted is not None and wanted not in [str(r["id"]) for r in _match(rows, roll)[1]]:
                raise ApiError(400, "library.bad_choice")
        if not {str(r["id"]) for r in rolls} >= set(choices):
            raise ApiError(400, "library.bad_choice")
        for roll in rolls:
            result, entry = _place(conn, roll, chosen=choices.get(str(roll["id"])))
            counts[result] += 1
            if entry is not None and str(roll["id"]) in choices and _tag(conn, roll, entry):
                counts["tagged"] += 1
            if result == "unclear":
                unclear.append(_offer(roll, _match(_rows(conn), roll)[1]))
        if dry_run:
            conn.rollback()
    if counts["tagged"] and not dry_run:
        stock_changed()                                             # a roll with a barcode is another kind in the stock
    return jsonify({"ok": True, "dry_run": dry_run, **counts, "unclear_rolls": unclear})


# --- Bambu Lab invoice -------------------------------------------------------------------------------------------

@bp.post("/invoice")
def read_invoice():
    """What a Bambu Lab invoice holds, checked against the library. Nothing is written."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ApiError(400, "files.pick")
    try:
        invoice = bambu_invoice.read(upload.stream.read(bambu_invoice.MAX_BYTES + 1))
    except Localized as exc:
        raise ApiError(422, exc) from None
    with pool().connection() as conn:
        rows = _rows(conn)
        invoice["already_imported"] = _earlier_imports(conn, invoice)
    known, loose = Index(rows), Loose(rows)
    store = bambu_store.lookup(invoice["lines"])                    # the Bambu Lab web shop's ID of each line: what the owner uses as barcode
    warnings = []
    for n, line in enumerate(invoice["lines"]):
        line["colour"] = to_english(line["colour"])                  # the invoice is Dutch, SpoolmanDB and Spoolman are English: one language, so no colour comes twice
        match = known.find(line) or loose.find(line)                 # ...and a filament that is there under its Dutch or its English name is the same one
        line["library_id"] = str(match["id"]) if match else None
        line["barcode"] = store["ids"].get(n, "")
    unread = [f"{line['name']} ({line['sku']})" for line in invoice["lines"] if not line["colour"]]
    if unread:                                                     # never let a line without a colour into the library or the shelf unseen
        warnings.append(tr("bambu.warn_no_colour", names=", ".join(unread)))
    if invoice["total"] is not None and invoice["total"] != invoice["lines_total"]:
        warnings.append(tr("bambu.warn_total", lines=invoice["lines_total"], invoice=invoice["total"]))
    if not store["reachable"]:
        warnings.append(tr("bambu.warn_store"))
    elif invoice["lines"] and len(store["ids"]) < len(invoice["lines"]):
        warnings.append(tr("bambu.warn_store_missing", n=len(invoice["lines"]) - len(store["ids"])))
    invoice["warnings"] = warnings
    return jsonify(invoice)


MAX_IMPORTS_LISTED = 500
BAD_COUNT = "library.bad_count"


def _count(value, maximum: int) -> int:
    """A whole number from 0 to `maximum` (a number or the digits of one); anything else is refused."""
    if isinstance(value, bool) or not isinstance(value, (int, str)) or (isinstance(value, str) and not value.strip().isdigit()):
        raise Localized(BAD_COUNT, max=maximum)
    number = int(value)
    if not 0 <= number <= maximum:
        raise Localized(BAD_COUNT, max=maximum)
    return number


def _amount(value) -> "Decimal | None":
    """An amount of money in cents, or None when it is not one (the invoice's totals are only kept as a record, so a bad one is left out, never fatal)."""
    try:
        amount = Decimal(str(value)).quantize(bambu_invoice.CENT)
    except (InvalidOperation, ValueError, TypeError):
        return None
    return amount if 0 <= amount < Decimal(10) ** 8 else None


def _invoice_meta(raw) -> dict:
    """What the browser says about the invoice as a whole: its numbers, its date and its totals. Kept as a record only, so it is cut to size and what is not
    valid is left out."""
    raw = raw if isinstance(raw, dict) else {}
    text = lambda key: str(raw.get(key) or "").strip()[:60]
    day = text("invoice_date")
    return {"invoice_number": text("invoice_number"), "order_number": text("order_number"),
            "invoice_date": day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None,
            "invoice_total": _amount(raw.get("total")), "lines_total": _amount(raw.get("lines_total"))}


def _earlier_imports(conn, invoice: dict) -> list[dict]:
    """The imports of this invoice there were before (by its number, else by the order number): when, and how many rolls they put on the shelf."""
    number, order = (invoice.get("invoice_number") or "").strip(), (invoice.get("order_number") or "").strip()
    if not (number or order):
        return []
    column, value = ("invoice_number", number) if number else ("order_number", order)
    found = conn.execute(f"SELECT id, imported_at, rolls_added FROM invoice_imports WHERE {column} = %s ORDER BY imported_at, id", (value,)).fetchall()
    return [{"id": r["id"], "imported_at": r["imported_at"].isoformat(), "rolls_added": r["rolls_added"]} for r in found]


def _shelf_roll(source: dict, entry: dict, paid: Decimal, note: str) -> dict:
    """A full roll of this filament at the price that was paid for it: `source` is the library's entry for it (else what the invoice line says), which
    brings the temperatures, the colour code and the SpoolmanDB source along, and the barcode of the entry (else the line's)."""
    values = {k: source[k] for k in ("brand", "product_type", "material", "colour", "colour_hex", "roll_weight_g", "diameter_mm", "print_temp_c", "bed_temp_c",
                                     "spoolmandb_id")}
    values.update(barcode=source["barcode"] or entry["barcode"] or "", price=paid, remaining_g=source["roll_weight_g"], notes=note, notify_low=False)
    return _validated(RESOURCES["spools"][1], values, partial=False)


def _record_import(conn, meta: dict, record: list) -> int:
    """Keep what this import did, line by line, so it can be checked against the invoice (`GET /invoice-imports`)."""
    made = sum(rolls for _, _, rolls in record)
    import_id = conn.execute(
        "INSERT INTO invoice_imports (invoice_number, order_number, invoice_date, invoice_total, lines_total, rolls_added) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (meta["invoice_number"], meta["order_number"], meta["invoice_date"], meta["invoice_total"], meta["lines_total"], made)).fetchone()["id"]
    for position, (item, result, rolls) in enumerate(record, 1):
        e = item["entry"]
        conn.execute(
            "INSERT INTO invoice_import_lines (import_id, position, brand, product_type, material, colour, refill, sku, filament_id, barcode, roll_weight_g, diameter_mm, "
            "quantity, rolls_added, paid_price, list_price, library) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (import_id, position, e["brand"], e["product_type"], e["material"], e["colour"], e["refill"], e["sku"], e["filament_id"], e["barcode"], e["roll_weight_g"],
             e["diameter_mm"], item["quantity"], rolls, item["paid"], e["price"], result))
    return import_id


@bp.post("/invoice/apply")
def apply_invoice():
    """Put the lines of an invoice in the library and, where the owner says so, the rolls on the shelf; and keep what was done (`invoice_imports`).
    A line says `library` (false = not in the library; the default is that it goes in) and `stock_quantity` (how many rolls go on the shelf, 0 or absent = none,
    so a client that knows nothing of the shelf never touches it), with `paid` (the price of a roll after the discount, excl. VAT, which the preview worked out) and
    `quantity` (what the invoice says); `invoice` carries its numbers, date and totals. A filament that is already in the library (see `keys`, or `Loose`: the
    same filament under its name in the other language) only gets the newer price and what it was missing (SKU, filament ID, barcode); one that is new is
    stored with its colour in English, as the preview showed it. The rolls are made like any new roll (`insert_rolls`: full, at the price paid, the barcode of the
    entry); the library, the rolls and the record are one transaction, so a refusal changes nothing at all."""
    body = json_body()
    lines = body.get("lines")
    if not isinstance(lines, list) or not lines or len(lines) > bambu_invoice.MAX_LINES:
        raise ApiError(400, "bambu.err_no_lines")
    meta = _invoice_meta(body.get("invoice"))
    price_of = RESOURCES["spools"][1]["price"]
    items = []
    for n, line in enumerate(lines, 1):
        try:
            if not isinstance(line, dict):
                raise Localized("backup.bad_row_type")
            entry = {**BLANK, **_validated(FIELDS, {**DEFAULTS, **line, "colour": to_english(line.get("colour"))}, partial=False)}
            wanted = _count(line.get("stock_quantity", 0), BULK_MAX_ROLLS)
            items.append({"entry": entry, "wanted": wanted, "library": line.get("library") is not False, "quantity": _count(line.get("quantity", 0), 9999),
                          "paid": price_of(line.get("paid")) if wanted else _amount(line.get("paid"))})
        except (ApiError, Localized) as exc:
            raise ApiError(400, "library.bad_row", n=n, reason=exc.msg) from None
    if sum(item["wanted"] for item in items) > BULK_MAX_ROLLS:
        raise ApiError(400, "bulk.too_many", max=BULK_MAX_ROLLS)
    if not any(item["library"] or item["wanted"] for item in items):
        raise ApiError(400, "bambu.err_no_lines")
    note = tr("bambu.roll_note", number=meta["invoice_number"] or meta["order_number"]) if (meta["invoice_number"] or meta["order_number"]) else ""
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    record = []
    with pool().connection() as conn:
        rows = _rows(conn)
        index, loose = Index(rows), Loose(rows)
        for n, item in enumerate(items, 1):
            entry = item["entry"]
            row = index.find(entry) or loose.find(entry)
            result = "skipped"
            if item["library"]:
                if row is None:
                    row = _insert(conn, entry)
                    index.add(row)
                    loose.add(row)
                    result = "added"
                else:
                    try:
                        updated = complete(conn, index, row, entry, price=entry["price"])
                    except ApiError as exc:
                        raise ApiError(400, "library.bad_row", n=n, reason=exc.msg) from None
                    if updated is not row:
                        loose.drop(row)
                        loose.add(updated)
                    result = "unchanged" if updated is row else "updated"
                    row = updated
                counts[result] += 1
            made = insert_rolls(conn, _shelf_roll(row or entry, entry, item["paid"], note), item["wanted"]) if item["wanted"] else []
            record.append((item, result, len(made)))
        import_id = _record_import(conn, meta, record)
    rolls = sum(count for _, _, count in record)
    if rolls:
        stock_changed()
    return jsonify({"ok": True, **counts, "rolls": rolls, "import_id": import_id})


@bp.get("/invoice-imports")
def invoice_imports():
    """What each invoice that was read in brought, newest first: the numbers, the totals, and per line the filament, what the invoice says, what went on the shelf, the
    price paid and what happened in the library, so that the owner can check it against the invoice."""
    with pool().read() as conn:
        imports = conn.execute("SELECT * FROM invoice_imports ORDER BY imported_at DESC, id DESC LIMIT %s", (MAX_IMPORTS_LISTED,)).fetchall()
        lines = conn.execute("SELECT * FROM invoice_import_lines WHERE import_id IN (SELECT value FROM json_each(%s)) ORDER BY import_id, position",
                             (id_list([r["id"] for r in imports]),)).fetchall()
    by_import: dict = {}
    for line in lines:
        by_import.setdefault(line["import_id"], []).append({k: _plain(v) for k, v in line.items() if k not in ("id", "import_id")})
    return jsonify([{**{k: _plain(v) for k, v in row.items()}, "imported_at": row["imported_at"].isoformat(),
                     "invoice_date": row["invoice_date"].isoformat() if row["invoice_date"] else None, "lines": by_import.get(row["id"], [])} for row in imports])
