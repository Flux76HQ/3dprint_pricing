"""SpoolmanDB: a community-kept list of filaments (brand, name, material, weight, diameter, colour, density, empty-spool weight, temperatures),
offered when a new roll is added, so that only the price still has to be typed. https://github.com/Donkie/SpoolmanDB, MIT licence.

What is used is a *snapshot* shipped with the app (`spoolmandb_data/snapshot.json`, made by `scripts/sync_spoolmandb.py`), never the live site:
the app contacts no new host, a roll can be added offline, and what the picker offers is what was reviewed. The licence and the copyright
notice travel with the snapshot (`spoolmandb_data/LICENSE`), as the MIT licence requires, and the screen that offers it names the source.

SpoolmanDB has **no barcode**: a scanned code cannot be looked up in it. What it does is fill the roll form of a barcode the app does not
know yet (brand, material, colour, weight, diameter, temperatures); the roll saved from that form is what the barcode means from then on.
A roll or library entry made from it keeps the SpoolmanDB `id` (`spoolmandb_id`, the reference to the source), which `spoolman.py` sends along
as the filament's `external_id`, with the density and empty-spool weight SpoolmanDB knows, when the roll is pushed to Spoolman.

The names in SpoolmanDB are English and the library's may be Dutch: `colour_names` tells when they are one colour, so a filament that is
already in the library is offered under the name it already has, and is not added a second time.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, jsonify, request

from .colour_names import loose_kind
from .http import ApiError, login_required, pool

bp = Blueprint("spoolmandb", __name__, url_prefix="/api/spoolmandb")

DATA_DIR = Path(__file__).with_name("spoolmandb_data")
SNAPSHOT = DATA_DIR / "snapshot.json"
FORMAT = "spoolmandb-snapshot"
FORMAT_VERSION = 1
# One row of the snapshot is a list in this order (the file says so itself, `columns`): a file of 10 000 objects repeats every key 10 000 times.
COLUMNS = ("id", "brand", "name", "material", "weight", "diameter", "hex", "density", "spool_weight", "extruder_temp", "bed_temp")
MAX_ROWS = 50_000
MAX_LISTED = 1500                                  # rows of one brand and material in an answer (the biggest brand has about 1300)
COLOUR_MAX = 40                                    # the longest colour a roll holds (`api.RESOURCES`)
ID = re.compile(r"[!-~]{1,120}")                  # printable ASCII, no space: SpoolmanDB's ids hold brackets and colons ("add:north_...", "..._basicblue(navyblue)_...")
HEX = re.compile(r"[0-9a-f]{6}")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


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


@lru_cache(maxsize=1)
def load() -> dict:
    """The snapshot: `source` (where it came from, to name on screen), `rows` (dicts) and `by_id`. Read and checked once per process; a file
    that is not what this code expects raises ValueError, which the routes turn into a 503 and the test of the shipped file into a failure."""
    doc = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or doc.get("format_version") != FORMAT_VERSION or tuple(doc.get("columns") or ()) != COLUMNS:
        raise ValueError("not a SpoolmanDB snapshot of this version")
    source = doc.get("source")
    if not isinstance(source, dict) or not all(isinstance(source.get(k), str) and source[k] for k in ("name", "url", "licence", "copyright", "fetched")):
        raise ValueError("the snapshot does not say where it came from")
    raw = doc.get("rows")
    if not isinstance(raw, list) or not raw or len(raw) > MAX_ROWS:
        raise ValueError("the snapshot has no rows, or too many")
    rows, by_id = [], {}
    for n, values in enumerate(raw, 1):
        checked = from_upstream(dict(zip(("id", "manufacturer", "name", "material", "weight", "diameter", "color_hex", "density", "spool_weight",
                                          "extruder_temp", "bed_temp"), values))) if isinstance(values, list) and len(values) == len(COLUMNS) else None
        if checked is None or list(values) != checked or checked[0] in by_id:
            raise ValueError(f"row {n} of the snapshot is not valid")
        row = dict(zip(COLUMNS, checked))
        rows.append(row)
        by_id[row["id"]] = row
    return {"source": {k: source[k] for k in ("name", "url", "licence", "copyright", "fetched") + (("upstream_head",) if source.get("upstream_head") else ())},
            "rows": rows, "by_id": by_id}


def find(spoolmandb_id: str) -> "dict | None":
    """The row with this SpoolmanDB id, None when the snapshot does not have it (or there is no snapshot)."""
    try:
        return load()["by_id"].get(spoolmandb_id)
    except (OSError, ValueError):
        return None


def _data() -> dict:
    try:
        return load()
    except (OSError, ValueError):
        raise ApiError(503, "spoolmandb.unavailable") from None


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


@bp.get("")
def overview():
    """Where the data comes from, and the brands with their materials, for the pull-downs of the picker."""
    data = _data()
    brands: dict[str, dict] = {}
    for row in data["rows"]:
        entry = brands.setdefault(row["brand"], {"name": row["brand"], "count": 0, "materials": set()})
        entry["count"] += 1
        entry["materials"].add(row["material"])
    listed = sorted(({**b, "materials": sorted(b["materials"])} for b in brands.values()), key=lambda b: b["name"].lower())
    return jsonify({"source": data["source"], "brands": listed})


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
    rows = [r for r in _data()["rows"] if r["brand"].lower() == brand.lower() and (not material or r["material"].lower() == material.lower())]
    if not brand or not rows:
        return jsonify({"filaments": []})
    with pool().read() as conn:
        have = _known(conn, rows[0]["brand"])
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
