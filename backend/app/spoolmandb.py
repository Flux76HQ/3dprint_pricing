"""SpoolmanDB: a community-kept list of filaments (brand, name, material, weight, diameter, colour, density, empty-spool weight, temperatures),
offered when a new roll is added, so that only the price still has to be typed. https://github.com/Donkie/SpoolmanDB, MIT licence.

Two copies exist, and the newer one wins. A **snapshot ships with the app** (`spoolmandb_data/snapshot.json`, made by `scripts/sync_spoolmandb.py`
and reviewed like any other change), so the suggestions work offline and from the first start. An **administrator can refresh it** from the project's
published list with the button in Settings -> Filaments, at most once a day (`POST /api/spoolmandb/sync`): that copy is kept in the database
(`spoolmandb_sync`, one row, not in a backup) and is used instead of the shipped one. The app contacts the project on that button and at no other
moment, only two fixed addresses (`SYNC_URL`, `LICENSE_URL`: https, no redirect followed, size and time capped, never taken from a request), and what
comes back is checked row by row (`from_upstream`) and refused when the licence is no longer the project's MIT text, when it is unusable or when it
is much smaller than what is held. The licence and the copyright notice travel with the data, as the MIT licence requires, and the screens name the source.

SpoolmanDB has **no barcode**: a scanned code cannot be looked up in it. What it does is fill the form of a barcode the app does not know yet (brand,
material, colour, weight, diameter, temperatures); the roll saved from that form is what the barcode means from then on. A roll or library entry made
from it keeps the SpoolmanDB `id` (`spoolmandb_id`, the reference to the source), which `spoolman.py` sends along as the filament's `external_id`, with
the density and empty-spool weight SpoolmanDB knows, when the roll is pushed to Spoolman. A sync never touches a roll or a library entry: a row that
leaves the list only costs those two values, which are then no longer sent.

The names in SpoolmanDB are English and the library's may be Dutch: `colour_names` tells when they are one colour, so a filament that is already in the
library is offered under the name it already has, and is not added a second time.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path

import requests
from flask import Blueprint, g, jsonify, request

from .colour_names import loose_kind
from .db import named_lock
from .http import ApiError, login_required, pool

log = logging.getLogger(__name__)
bp = Blueprint("spoolmandb", __name__, url_prefix="/api/spoolmandb")

DATA_DIR = Path(__file__).with_name("spoolmandb_data")
SNAPSHOT = DATA_DIR / "snapshot.json"
FORMAT = "spoolmandb-snapshot"
FORMAT_VERSION = 1
# One row of the snapshot is a list in this order (the file says so itself, `columns`): a file of 10 000 objects repeats every key 10 000 times.
COLUMNS = ("id", "brand", "name", "material", "weight", "diameter", "hex", "density", "spool_weight", "extruder_temp", "bed_temp")
UPSTREAM_KEYS = ("id", "manufacturer", "name", "material", "weight", "diameter", "color_hex", "density", "spool_weight", "extruder_temp", "bed_temp")
SOURCE_KEYS = ("name", "url", "licence", "copyright", "fetched")                # what a snapshot says about where it came from (`upstream_head`, `modified` are optional)
REPO = "https://github.com/Donkie/SpoolmanDB"
COPYRIGHT = "Copyright (c) 2024 Donkie"
MAX_ROWS = 50_000
MAX_LISTED = 1500                                  # rows of one brand and material in an answer (the biggest brand has about 1300)
COLOUR_MAX = 40                                    # the longest colour a roll holds (`api.RESOURCES`)
ID = re.compile(r"[!-~]{1,120}")                  # printable ASCII, no space: SpoolmanDB's ids hold brackets and colons ("add:north_...", "..._basicblue(navyblue)_...")
HEX = re.compile(r"[0-9a-f]{6}")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# The sync: the two addresses the app ever calls for this, fixed here and not configurable (the published list lives on the project's GitHub Pages, the
# licence in its repository), how much it may download, how long it may take, how often it may run, and how small a new list may be before it is distrusted.
SYNC_URL = "https://donkie.github.io/SpoolmanDB/filaments.json"
LICENSE_URL = "https://raw.githubusercontent.com/Donkie/SpoolmanDB/main/LICENSE"
MAX_DOWNLOAD_BYTES = 24 * 1024 * 1024              # the published list is about 6 MB
MAX_LICENCE_BYTES = 64 * 1024
TIMEOUT = (5, 30)                                  # connect, read: seconds
MIN_INTERVAL = timedelta(hours=24)
MIN_ROWS = 100
KEEP_RATIO = 0.5                                   # a list with fewer than half the rows that are held is a broken download or a changed format, not an update
SYNC_LOCK = "spoolmandb-sync"


class Refused(Exception):
    """Nothing is taken. `key` is the message of the screen (`lang/*.json`) and `params` its values; the text is plain English for a script."""

    def __init__(self, text: str, key: "str | None" = None, **params):
        super().__init__(text)
        self.key, self.params = key, params


# --- reading and checking the list -------------------------------------------------------------------------------------

def _text(value, limit: int) -> str:
    return CONTROL.sub(" ", value).strip()[:limit] if isinstance(value, str) else ""


def _number(value, low: float, high: float) -> "float | None":
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and low < value <= high
    return (int(value) if float(value).is_integer() else float(value)) if ok else None


def _temp(value, high: int) -> "int | None":
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= high else None


def from_upstream(entry) -> "list | None":
    """One compiled entry of SpoolmanDB's `filaments.json` as a row of the snapshot, or None when it cannot be used. The upstream file is
    third-party data: every value is checked and cut to size here, so the snapshot never holds more than the app is able to show."""
    if not isinstance(entry, dict):
        return None
    ident = entry.get("id")
    hexes = entry.get("color_hexes")
    colour = entry.get("color_hex") or (hexes[0] if isinstance(hexes, list) and hexes and isinstance(hexes[0], str) else "")
    row = [ident if isinstance(ident, str) and ID.fullmatch(ident) else None,
           _text(entry.get("manufacturer"), 60), _text(entry.get("name"), 80), _text(entry.get("material"), 40),
           _number(entry.get("weight"), 0, 100_000), _number(entry.get("diameter"), 0, 5),
           colour.lower().lstrip("#")[:6] if isinstance(colour, str) and HEX.fullmatch(colour.lower().lstrip("#")[:6]) else "",     # an alpha channel is dropped
           _number(entry.get("density"), 0, 25), _number(entry.get("spool_weight"), 0, 10_000),
           _temp(entry.get("extruder_temp"), 500), _temp(entry.get("bed_temp"), 200)]
    return row if all(row[i] not in (None, "") for i in (0, 1, 2, 3, 4, 5, 7)) else None


def rows_of(upstream) -> tuple[list, int]:
    """(the usable rows of the upstream list by id, how many entries were dropped). Raises `Refused` for something that is not a list of filaments."""
    if not isinstance(upstream, list):
        raise Refused("the upstream file is not a list of filaments", "spoolmandb.sync_unusable")
    rows, dropped, seen = [], 0, set()
    for entry in upstream:
        row = from_upstream(entry)
        if row is None or row[0] in seen:
            dropped += 1
            continue
        seen.add(row[0])
        rows.append(row)
    if len(rows) < MIN_ROWS:
        raise Refused(f"only {len(rows)} usable rows: the upstream format has probably changed", "spoolmandb.sync_unusable")
    rows.sort(key=lambda r: r[0])
    return rows, dropped


def document_text(rows: list, source: dict) -> str:
    """The text of a snapshot: a few lines of header and one row per line, in the same order every time, so that a refresh is a readable diff."""
    lines = ['{"format": ' + json.dumps(FORMAT) + ', "format_version": ' + str(FORMAT_VERSION) + ',',
             ' "source": ' + json.dumps(source, ensure_ascii=False) + ',',
             ' "columns": ' + json.dumps(list(COLUMNS)) + ',',
             ' "rows": [']
    lines += [json.dumps(row, ensure_ascii=False, separators=(",", ":")) + ("," if n < len(rows) else "") for n, row in enumerate(rows, 1)]
    lines.append(']}')
    return "\n".join(lines) + "\n"


def check_licence(text: str) -> str:
    """The licence is part of what is copied: it has to be the MIT licence of that project, or the data is not ours to keep."""
    head = text.splitlines()[:5]
    if not text.startswith("MIT License") or not any("Copyright" in line and "Donkie" in line for line in head) or "Permission is hereby granted" not in text:
        raise Refused("the licence of SpoolmanDB is not the MIT licence this was reviewed under: check it before using the data", "spoolmandb.sync_licence")
    return text if text.endswith("\n") else text + "\n"


def _parse(text: str) -> dict:
    """A snapshot as `source` (where it came from, to name on screen), `rows` (dicts) and `by_id`. A text that is not what this code expects
    raises ValueError, which the routes turn into a 503 and the test of the shipped file into a failure."""
    doc = json.loads(text)
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or doc.get("format_version") != FORMAT_VERSION or tuple(doc.get("columns") or ()) != COLUMNS:
        raise ValueError("not a SpoolmanDB snapshot of this version")
    source = doc.get("source")
    if not isinstance(source, dict) or not all(isinstance(source.get(k), str) and source[k] for k in SOURCE_KEYS):
        raise ValueError("the snapshot does not say where it came from")
    raw = doc.get("rows")
    if not isinstance(raw, list) or not raw or len(raw) > MAX_ROWS:
        raise ValueError("the snapshot has no rows, or too many")
    rows, by_id = [], {}
    for n, values in enumerate(raw, 1):
        checked = from_upstream(dict(zip(UPSTREAM_KEYS, values))) if isinstance(values, list) and len(values) == len(COLUMNS) else None
        if checked is None or list(values) != checked or checked[0] in by_id:
            raise ValueError(f"row {n} of the snapshot is not valid")
        row = dict(zip(COLUMNS, checked))
        rows.append(row)
        by_id[row["id"]] = row
    return {"source": {k: source[k] for k in SOURCE_KEYS + ("upstream_head", "modified") if isinstance(source.get(k), str) and source[k]}, "rows": rows, "by_id": by_id}


@lru_cache(maxsize=1)
def load() -> dict:
    """The snapshot that ships with the app, read and checked once per process."""
    return _parse(SNAPSHOT.read_text(encoding="utf-8"))


# --- the copy in use ---------------------------------------------------------------------------------------------------------

# (version of the synced copy it was read from, the copy): None, None while the shipped snapshot is the one in use. Replaced as a whole, so a request
# in another thread sees the old pair or the new one, never half of each. Every worker of the web server has its own, and `refresh` is how a worker
# notices that another one synced.
_state: tuple = (None, None)


def reset() -> None:
    """Forget the synced copy this process holds (it is read again on the next `refresh`), and the shipped snapshot too; for tests."""
    global _state
    _state = (None, None)
    load.cache_clear()


def current() -> dict:
    """The list in use: the synced copy once `refresh` has seen one, else the shipped snapshot."""
    return _state[1] or load()


def refresh(conn) -> dict:
    """Make the copy of this process the one in the database (one short read of the version; the list itself is only read when it changed), and
    return it. A synced copy that is not valid is left unused and the shipped snapshot serves instead, so a damaged row never takes the suggestions down."""
    global _state
    row = conn.execute("SELECT version FROM spoolmandb_sync").fetchone()
    version = row["version"] if row else None
    if version != _state[0]:
        data = None
        if row:
            try:
                data = _parse(conn.execute("SELECT document FROM spoolmandb_sync").fetchone()["document"])
            except ValueError as exc:
                log.warning("The synced SpoolmanDB copy is not usable (%s); the one that shipped with the app is used", exc)
        _state = (version, data)
    return current()


def find(spoolmandb_id: str) -> "dict | None":
    """The row with this SpoolmanDB id, None when the list in use does not have it (or there is none)."""
    try:
        return current()["by_id"].get(spoolmandb_id)
    except (OSError, ValueError):
        return None


def _data(conn) -> dict:
    try:
        return refresh(conn)
    except (OSError, ValueError):
        raise ApiError(503, "spoolmandb.unavailable") from None


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


# --- the routes ------------------------------------------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_sync(synced_at: "datetime | None") -> "datetime | None":
    """When the next sync may run: a day after the last one that went through, None when it may run now."""
    after = synced_at + MIN_INTERVAL if synced_at else None
    return after if after and after > _now() else None


@bp.get("")
def overview():
    """Where the list in use comes from and how big it is, the brands with their materials (for the brand pull-down and the suggestions of the form), and for the
    sync button: whether the list is the shipped one or a synced copy, when it was synced and when it may be again."""
    with pool().read() as conn:
        data = _data(conn)
        stored = conn.execute("SELECT synced_at FROM spoolmandb_sync").fetchone()
    brands: dict[str, dict] = {}
    for row in data["rows"]:
        entry = brands.setdefault(row["brand"], {"name": row["brand"], "count": 0, "materials": set()})
        entry["count"] += 1
        entry["materials"].add(row["material"])
    listed = sorted(({**b, "materials": sorted(b["materials"])} for b in brands.values()), key=lambda b: b["name"].lower())
    synced_at = stored["synced_at"] if stored and _state[1] is not None else None
    wait = _next_sync(synced_at)
    return jsonify({"source": data["source"], "brands": listed, "rows": len(data["rows"]), "origin": "synced" if synced_at else "shipped",
                    "synced_at": synced_at.isoformat() if synced_at else None, "next_sync_at": wait.isoformat() if wait else None,
                    "can_sync": getattr(g, "role", None) == "admin"})


def fetch(url: str, limit: int) -> tuple[bytes, dict]:
    """(the body, the headers) of one of the fixed addresses. https only, a redirect is not followed (so the answer can only be from that address),
    and at most `limit` bytes are read."""
    if not url.startswith("https://"):
        raise Refused(f"not an https address: {url}", "spoolmandb.sync_failed")
    try:
        with requests.get(url, timeout=TIMEOUT, allow_redirects=False, stream=True, headers={"User-Agent": "3dprint-pricing"}) as res:
            if res.status_code != 200:
                raise Refused(f"{url} answered {res.status_code}", "spoolmandb.sync_status", code=res.status_code)
            body = b""
            for chunk in res.iter_content(65536):
                body += chunk
                if len(body) > limit:
                    raise Refused(f"{url} is larger than {limit} bytes", "spoolmandb.sync_too_big")
            return body, dict(res.headers)
    except requests.RequestException:
        raise Refused(f"{url} could not be reached", "spoolmandb.sync_failed") from None


def _modified(headers: dict) -> str:
    """The date the project published this list (`Last-Modified`), or '' when it does not say."""
    try:
        return parsedate_to_datetime(next(v for k, v in headers.items() if k.lower() == "last-modified")).astimezone(timezone.utc).date().isoformat()
    except (StopIteration, TypeError, ValueError):
        return ""


def _sync() -> dict:
    """Fetch, check and keep a new copy. Raises `Refused` with nothing changed. The caller holds `SYNC_LOCK` and has seen that a sync is allowed."""
    check_licence(fetch(LICENSE_URL, MAX_LICENCE_BYTES)[0].decode("utf-8", errors="replace"))      # checked, not copied: the text that travels with the data is `spoolmandb_data/LICENSE`
    body, headers = fetch(SYNC_URL, MAX_DOWNLOAD_BYTES)
    try:
        upstream = json.loads(body.decode("utf-8"))
    except ValueError:
        raise Refused("the upstream file is not JSON", "spoolmandb.sync_not_json") from None
    rows, dropped = rows_of(upstream)
    with pool().read() as conn:
        held = refresh(conn)
    if len(rows) < KEEP_RATIO * len(held["rows"]):
        raise Refused(f"{len(rows)} rows against the {len(held['rows'])} held", "spoolmandb.sync_shrunk", n=len(rows), held=len(held["rows"]))
    now = _now()
    source = {"name": "SpoolmanDB", "url": REPO, "licence": "MIT", "copyright": COPYRIGHT, "fetched": now.date().isoformat(),
              **({"modified": _modified(headers)} if _modified(headers) else {})}
    text = document_text(rows, source)
    try:
        _parse(text)                                                 # what is kept is what `refresh` will accept: checked before it replaces anything
    except ValueError as exc:
        raise Refused(f"the new list does not pass its own check: {exc}", "spoolmandb.sync_unusable") from None
    with pool().connection() as conn:
        conn.execute("INSERT INTO spoolmandb_sync (singleton, version, synced_at, document) VALUES (true, 1, %s, %s) "
                     "ON CONFLICT (singleton) DO UPDATE SET version = spoolmandb_sync.version + 1, synced_at = EXCLUDED.synced_at, document = EXCLUDED.document",
                     (now, text))
    with pool().read() as conn:
        refresh(conn)                                                # this process uses it at once; the others notice the new version on their next request
    before, after = {r["id"] for r in held["rows"]}, {r[0] for r in rows}
    return {"rows": len(rows), "brands": len({r[1] for r in rows}), "added": len(after - before), "removed": len(before - after), "dropped": dropped}


@bp.post("/sync")
def run_sync():
    """Fetch the project's published list now, at most once a day (counted from the last sync that went through: one that fails does not use up the
    day). Administrators only (`access.ADMIN_ONLY`): it changes what everybody is offered and contacts the internet. Nothing of the rolls or the
    library is touched."""
    try:
        with named_lock(pool(), SYNC_LOCK):
            with pool().read() as conn:
                stored = conn.execute("SELECT synced_at FROM spoolmandb_sync").fetchone()
            wait = _next_sync(stored["synced_at"] if stored else None)
            if wait:                                                 # checked inside the lock: two clicks at once make one sync
                hours = max(1, -(-int((wait - _now()).total_seconds()) // 3600))
                raise ApiError(429, "spoolmandb.too_soon", hours=hours)
            return jsonify(_sync())
    except Refused as exc:
        log.warning("SpoolmanDB sync refused: %s", exc)
        raise ApiError(502, exc.key or "spoolmandb.sync_failed", **exc.params) from None


# --- the suggestions of the form ------------------------------------------------------------------------------------------------------------

def _spec(row: dict) -> dict:
    """What a SpoolmanDB row says about a roll's filament, in the words of a roll: its whole name is the colour (SpoolmanDB names carry the
    product line, "Matte Black", as Spoolman does), and the type is left empty rather than guessed."""
    return {"brand": row["brand"], "material": row["material"], "product_type": "", "colour": row["name"], "roll_weight_g": row["weight"], "diameter_mm": row["diameter"]}


def _known(conn, brand: str) -> list[dict]:
    """The filaments this installation already has of a brand: the library's entries first, then the rolls, which are the same filament when
    `loose_kind` says so (a Dutch and an English name of one colour are one)."""
    found = conn.execute("SELECT *, 'library' AS origin FROM filament_library WHERE lower(brand) = lower(%s) ORDER BY created_at, id", (brand,)).fetchall()
    found += conn.execute("SELECT *, 'roll' AS origin FROM filament_spools WHERE lower(brand) = lower(%s) ORDER BY created_at, id", (brand,)).fetchall()
    return found


def fill(row: dict, have: "dict | None") -> dict:
    """What picking this row puts in the roll form. A filament the installation already has keeps its own spelling (brand, type, material,
    colour, the library's price): the roll is the one that is there, and the colour of the other language is not added next to it. What the
    entry lacks (colour, temperatures) is completed from SpoolmanDB. The barcode is never part of it: it was scanned or typed."""
    own = have or {}
    colour = (own.get("colour") or row["name"]).strip()[:COLOUR_MAX].rstrip()
    values = {"brand": own.get("brand") or row["brand"], "product_type": own.get("product_type") or "", "material": own.get("material") or row["material"],
              "colour": colour, "colour_hex": own.get("colour_hex") or (f"#{row['hex']}" if row["hex"] else ""),
              "roll_weight_g": row["weight"], "diameter_mm": row["diameter"],
              "print_temp_c": own["print_temp_c"] if own.get("print_temp_c") is not None else row["extruder_temp"],
              "bed_temp_c": own["bed_temp_c"] if own.get("bed_temp_c") is not None else row["bed_temp"],
              "spoolmandb_id": row["id"]}
    if own.get("origin") == "library" and own.get("price") is not None:
        values["price"] = str(own["price"])
    return values


@bp.get("/filaments")
def filaments():
    """The filaments of one brand and material, each with what picking it fills in (`fill`) and, when the installation already has that
    filament, `known` (its name there: it is what `fill` uses)."""
    brand, material = (request.args.get("brand") or "").strip(), (request.args.get("material") or "").strip()
    with pool().read() as conn:
        data = _data(conn)
        rows = [r for r in data["rows"] if r["brand"].lower() == brand.lower() and (not material or r["material"].lower() == material.lower())]
        have = _known(conn, rows[0]["brand"]) if brand and rows else []
    if not brand or not rows:
        return jsonify({"filaments": []})
    mine: dict[tuple, dict] = {}
    for entry in have:
        mine.setdefault(loose_kind(entry), entry)
    out = []
    for row in rows[:MAX_LISTED]:
        entry = mine.get(loose_kind(_spec(row)))
        out.append({"id": row["id"], "name": row["name"], "weight": row["weight"], "diameter": row["diameter"], "hex": row["hex"],
                    "spool_weight": row["spool_weight"], "known": ({"colour": entry["colour"], "product_type": entry["product_type"], "origin": entry["origin"]}
                                                                    if entry else None),
                    "fill": fill(row, entry)})
    out.sort(key=lambda r: (r["name"].lower(), r["weight"], r["diameter"]))
    return jsonify({"filaments": out, "listed": len(out), "total": len(rows)})
