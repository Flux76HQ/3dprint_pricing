"""The filament library: what a filament is (specs and a reference price), apart from the rolls on the shelf.

Plain create / edit / delete of an entry is the generic resource in `api.RESOURCES` ("filament-library"); this module adds what only the
library does: reading a Bambu Lab invoice into entries, syncing from GitHub, and exporting / importing the library as a JSON file.
None of it touches the rolls on the shelf (`filament_spools`): the library is a separate list of the filaments that exist, a roll is made
from an entry by hand in the roll form. An entry is matched on its SKU, else its barcode, else its filament ID, else brand + material +
type + colour + refill, so the same filament is never added twice by an import.
"""
import json
from datetime import datetime, timezone
from decimal import Decimal

import requests
from flask import Blueprint, Response, jsonify, request

from . import bambu_invoice, bambu_store
from .api import RESOURCES, _validated
from .config import CONTRIBUTE_URL, DEFAULT_LIBRARY_URL
from .http import ApiError, config, json_body, login_required, pool
from .i18n import L, Localized, tr

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


FILLABLE = ("sku", "filament_id", "barcode", "colour_hex", "print_temp_c", "bed_temp_c")      # what an entry may be given when it lacks it
LOCK = 7_210_021                                                                                # advisory lock: one writer of the library at a time


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


def _duplicate(other: dict) -> ApiError:
    return ApiError(409, "library.duplicate", name=name_of(other))


def _lock(conn) -> None:
    """Held until the transaction ends: two requests that add the same filament at once are made to take turns, so the second sees the first."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))


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
    _lock(conn)
    other = Index(_rows(conn)).find({**BLANK, **DEFAULTS, **values})
    if other:
        raise _duplicate(other)


def before_update(conn, item_id, values: dict) -> None:
    """Changing an entry: refused when it would become a copy of another one."""
    _lock(conn)
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


def roll_spec(roll: dict, extra=None) -> "tuple[dict, bool | None]":
    """What a roll says about its filament, as a library entry (never what it cost or what is left), and whether it is a refill when that is
    known (`extra` is what the roll form knows: the supplier `filament_id` and `refill`)."""
    extra = extra if isinstance(extra, dict) else {}
    refill = extra["refill"] if isinstance(extra.get("refill"), bool) else None
    spec = {**BLANK, **{k: roll[k] for k in ("brand", "product_type", "material", "colour", "colour_hex", "barcode", "roll_weight_g",
                                              "diameter_mm", "print_temp_c", "bed_temp_c")},
            "filament_id": str(extra.get("filament_id") or "").strip()[:20], "refill": bool(refill)}
    return spec, refill


def matches(rows: list[dict], spec: dict, refill: "bool | None") -> list[dict]:
    """The entries a roll can be: the same barcode, else the same brand, material, type, colour, weight and diameter (as a refill or not
    when that is known). More than one is "not clear which one"; none means the library lacks the filament."""
    code = _n(spec, "barcode")
    return [r for r in rows if code and _n(r, "barcode") == code] or \
        [r for r in rows if _kind(r) == _kind(spec) and (refill is None or r["refill"] == refill)]


def add_roll(conn, roll: dict, extra=None) -> str:
    """A roll typed in by hand may go in the library too: when the filament is not there yet it is added (what the roll says about the
    filament, never what it cost or what is left), and when it is, that entry gets what it was missing. The same barcode is the same
    filament; without one, the same brand, material, type, colour, weight and diameter, as a refill or not. When that is more than one
    entry (a refill and a roll with spool), it is not clear which one this roll is, so none is touched. `extra` is what the form knows
    about the filament that a roll does not hold: its supplier `filament_id` and whether it is a `refill` (from the Bambu Lab shop); with a
    `refill` the match is exact, so that is no longer unclear. Returns what happened: `added`, `updated`, `unchanged` or `unclear`."""
    _lock(conn)
    rows = _rows(conn)
    index = Index(rows)
    spec, refill = roll_spec(roll, extra)
    found = matches(rows, spec, refill)
    if not found:
        index.add(_insert(conn, {k: v for k, v in spec.items() if k in FIELDS and k not in ("price", "notes", "sku")}))
        return "added"
    if len(found) > 1:
        return "unclear"
    try:
        updated = complete(conn, index, found[0], spec)
    except ApiError:                                              # it would clash with another entry: leave the entry as it is
        return "unclear"
    return "unchanged" if updated is found[0] else "updated"


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
    """Add what is new and bring what is already there in line with the file. Nothing is ever deleted. A line of the file is the same
    filament as an entry when they share a key (see `keys`); a change that would make an entry a copy of another one is refused, with its line."""
    if write:
        _lock(conn)
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


SHARE_FILLS = (*FILLABLE, "price")                                  # what a contribution may fill in on a filament the shared library already has


def _offer(row: dict, **extra) -> dict:
    """An entry as the export writes it, without the notes (they are the owner's own)."""
    return {**{k: _plain(row[k]) for k in FIELDS if k != "notes"}, **extra}


@bp.post("/contribution")
def contribution():
    """What this installation can add to the shared library, to offer as a contribution. The candidates are the entries of the library and the
    filaments of the rolls (not archived) that the library lacks, as `add_roll` would make them. Which filament is "the same" is `keys()`, as
    everywhere. One the shared library does not know is a new entry (`entries`); one it knows, but lacks some of the fields in `SHARE_FILLS`
    for, is a completion (`completions`, with the `fills`): only blanks are ever filled, nothing is overwritten. The rest is `already_there`.
    Nothing is written, neither in the library nor in the rolls."""
    if not _contribute_url():
        raise ApiError(404, "library.contribute_off")
    shared = Index({**BLANK, **DEFAULTS, **item} for item in _parse_library(_remote()))
    with pool().connection() as conn:
        rows = _rows(conn)
        rolls = conn.execute("SELECT * FROM filament_spools WHERE NOT archived ORDER BY created_at, id").fetchall()
    candidates = [(row, {}) for row in rows]
    seen = Index(rows)
    for roll in rolls:
        spec, refill = roll_spec(roll)
        if matches(rows, spec, refill) or seen.find(spec):          # in the library already (or unclear which entry it is), or another roll said so
            continue
        seen.add(spec)
        candidates.append((spec, {"source": "roll"}))
    entries, completions, known = [], [], 0
    for row, extra in candidates:
        other = shared.find(row)
        if other is None:
            entries.append(_offer(row, **extra))
            continue
        fills = [k for k in SHARE_FILLS if _blank(other[k]) and not _blank(row.get(k))]
        if fills and shared.clash(other, {**other, **{k: row[k] for k in fills}}) is None:
            completions.append({"entry": _offer(row, **extra), "fills": fills})
        else:
            known += 1
    return jsonify({"entries": entries, "completions": completions, "already_there": known})


# --- the rolls on the shelf ---------------------------------------------------------------------------------------

@bp.post("/from-rolls")
def from_rolls():
    """Put the filaments of the rolls in the filament list (not archived: those are on the shelf) in the library, so they can be shared too.
    Each roll goes through `add_roll`: a filament that is not there yet is added with what the roll says about it (never its price or what is
    left), one that is there only gets what it lacked, and a roll that cannot be told from more than one entry is left out and counted as
    `unclear`. The rolls themselves are only read. With `dry_run=1` everything is done and then rolled back, so the counts are exact."""
    dry_run = request.args.get("dry_run") == "1"
    counts = {"added": 0, "updated": 0, "unchanged": 0, "unclear": 0}
    with pool().connection() as conn:
        _lock(conn)
        for roll in conn.execute("SELECT * FROM filament_spools WHERE NOT archived ORDER BY created_at, id").fetchall():
            counts[add_roll(conn, roll)] += 1
        if dry_run:
            conn.rollback()
    return jsonify({"ok": True, "dry_run": dry_run, **counts})


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
        known = Index(_rows(conn))
    store = bambu_store.lookup(invoice["lines"])                    # the Bambu Lab web shop's ID of each line: what the owner uses as barcode
    warnings = []
    for n, line in enumerate(invoice["lines"]):
        match = known.find(line)
        line["library_id"] = str(match["id"]) if match else None
        line["barcode"] = store["ids"].get(n, "")
    if invoice["total"] is not None and invoice["total"] != invoice["lines_total"]:
        warnings.append(tr("bambu.warn_total", lines=invoice["lines_total"], invoice=invoice["total"]))
    if not store["reachable"]:
        warnings.append(tr("bambu.warn_store"))
    elif invoice["lines"] and len(store["ids"]) < len(invoice["lines"]):
        warnings.append(tr("bambu.warn_store_missing", n=len(invoice["lines"]) - len(store["ids"])))
    invoice["warnings"] = warnings
    return jsonify(invoice)


@bp.post("/invoice/apply")
def apply_invoice():
    """Put the chosen lines of an invoice in the library. A filament that is already there (see `keys`) only gets the newer price and what
    it was missing (SKU, filament ID, barcode). Only the library changes: the rolls on the shelf are never touched, whatever the invoice says."""
    lines = json_body().get("lines")
    if not isinstance(lines, list) or not lines or len(lines) > bambu_invoice.MAX_LINES:
        raise ApiError(400, "bambu.err_no_lines")
    entries = []
    for n, line in enumerate(lines, 1):
        try:
            if not isinstance(line, dict):
                raise Localized("backup.bad_row_type")
            entries.append({**BLANK, **_validated(FIELDS, {**DEFAULTS, **line}, partial=False)})
        except (ApiError, Localized) as exc:
            raise ApiError(400, "library.bad_row", n=n, reason=exc.msg) from None
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    with pool().connection() as conn:
        _lock(conn)
        index = Index(_rows(conn))
        for n, entry in enumerate(entries, 1):
            row = index.find(entry)
            if row is None:
                index.add(_insert(conn, entry))
                counts["added"] += 1
                continue
            try:
                updated = complete(conn, index, row, entry, price=entry["price"])
            except ApiError as exc:
                raise ApiError(400, "library.bad_row", n=n, reason=exc.msg) from None
            counts["unchanged" if updated is row else "updated"] += 1
    return jsonify({"ok": True, **counts})
