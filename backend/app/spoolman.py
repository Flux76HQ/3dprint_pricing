"""Spoolman (https://github.com/Donkie/Spoolman) as the source of the rolls and of what is left on them.

With `SPOOLMAN_URL` set, *Sync* reads every spool from Spoolman and mirrors it as a roll in `filament_spools`, keyed on Spoolman's own spool
number (`spoolman_id`). A calculation keeps pointing at a local roll, so prices and saved calculations work as before; only where the roll's
details come from changes. The details of a mirrored roll are Spoolman's to change (the app refuses to edit them, see `api.update`), a sync
overwrites them, and a spool that is gone from Spoolman is archived here, never deleted, because calculations may refer to it.

Going the other way, booking a calculation's filament reports the grams to Spoolman (`PUT /api/v1/spool/<id>/use`). The grams are written
to `spoolman_pending_use` in the same transaction as the booking and sent afterwards, so a Spoolman that is out of reach loses nothing:
a sync sends what is left first, and until it is sent the weight Spoolman reports is reduced by it, so the shelf does not jump back up.

The address is configuration, never taken from a request. Nothing is followed on a redirect, every answer is capped in size, and Spoolman's
data is validated and clamped before it reaches a column (a malformed spool is skipped and counted, never fatal). The library
(`filament_library`) is not touched by any of this.
"""
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import requests
from flask import Blueprint, g, jsonify, request

from . import filament_library
from .api import _serialise, _share_notify, stock_changed
from .http import ApiError, config, login_required, pool

log = logging.getLogger(__name__)
bp = Blueprint("spoolman", __name__, url_prefix="/api/spoolman")

LOCK = 7_210_025                        # advisory lock: one sync at a time
PAGE = 200
MAX_SPOOLS = 5_000
MAX_BYTES = 20 * 1024 * 1024            # one page of spools is far below this; it is only a stop for a server that never ends
TIMEOUT = (5, 20)                       # connect, read: the screen waits for a sync, so it must end
HEX = re.compile(r"^[0-9a-f]{6}$")
MIRRORED = ("brand", "product_type", "material", "colour", "colour_hex", "roll_weight_g", "price", "remaining_g", "barcode", "diameter_mm",
            "print_temp_c", "bed_temp_c", "notes", "archived")        # everything but `notify_low`, which is the app's own setting


class SpoolmanError(Exception):
    """Spoolman could not be reached or did not answer as Spoolman does. `retry` is whether trying again later can help."""

    def __init__(self, key: str, *, retry: bool = True, **params):
        super().__init__(key)
        self.key, self.retry, self.params = key, retry, params

    def api(self) -> ApiError:
        return ApiError(502, self.key, **self.params)


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session; syncing is for administrators (`access.ADMIN_ONLY`)."""


def enabled() -> bool:
    return bool(config().spoolman_url)


def _call(method: str, path: str, **kwargs):
    url = config().spoolman_url + "/api/v1" + path
    try:
        reply = requests.request(method, url, timeout=TIMEOUT, allow_redirects=False, stream=True, headers={"Accept": "application/json"}, **kwargs)
    except requests.RequestException as exc:
        log.warning("Spoolman %s %s failed: %s", method, path, type(exc).__name__)
        raise SpoolmanError("spoolman.unreachable") from None
    try:
        if 300 <= reply.status_code < 400:
            raise SpoolmanError("spoolman.redirect", retry=False)
        if reply.status_code >= 400:
            raise SpoolmanError("spoolman.bad_status", retry=reply.status_code >= 500, status=reply.status_code)
        body = b""
        for chunk in reply.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES:
                raise SpoolmanError("spoolman.bad_reply", retry=False)
        return reply, body
    finally:
        reply.close()


def _json(method: str, path: str, **kwargs):
    reply, body = _call(method, path, **kwargs)
    try:
        return reply, json.loads(body)
    except ValueError:
        raise SpoolmanError("spoolman.bad_reply", retry=False) from None


def _pages(path: str, params: dict | None = None, *, cap: int = MAX_SPOOLS) -> tuple[list[dict], int]:
    """Every object of a Spoolman list, and how many entries were not an object with a whole-number id."""
    found, skipped, offset = [], 0, 0
    while True:
        reply, page = _json("GET", path, params={**(params or {}), "limit": PAGE, "offset": offset})
        if not isinstance(page, list):
            raise SpoolmanError("spoolman.bad_reply", retry=False)
        for item in page:
            if isinstance(item, dict) and isinstance(item.get("id"), int) and not isinstance(item["id"], bool):
                found.append(item)
            else:
                skipped += 1
        offset += len(page)
        if not page or len(page) < PAGE:
            return found, skipped
        if offset >= cap:
            raise SpoolmanError("spoolman.too_many", retry=False, max=cap)


def fetch_spools() -> tuple[list[dict], int]:
    return _pages("/spool", {"allow_archived": "true"})        # archived ones too, so a spool archived in Spoolman is archived here as well


def _dec(value, places: str):
    """A number as Decimal rounded to `places`, or None when it is not a finite number."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number.quantize(Decimal(places)) if number.is_finite() else None


def _text(value, limit: int) -> str:
    return str(value).strip()[:limit] if value is not None else ""


def _temp(value, high: int):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= high else None


def to_roll(spool: dict) -> dict:
    """The columns of a roll from one spool of Spoolman. Spoolman's *filament* is what our roll calls brand/material/colour, its *name* is the
    colour, its *article number* is the barcode (what groups the rolls of one kind), and a price on the spool beats the filament's."""
    filament = spool.get("filament") if isinstance(spool.get("filament"), dict) else {}
    vendor = filament.get("vendor") if isinstance(filament.get("vendor"), dict) else {}
    weight = next((w for w in (_dec(spool.get("initial_weight"), "0.1"), _dec(filament.get("weight"), "0.1")) if w and w > 0), Decimal("1000.0"))
    left = _dec(spool.get("remaining_weight"), "0.1")
    if left is None:
        left = weight - (_dec(spool.get("used_weight"), "0.1") or Decimal(0))
    price = next((p for p in (_dec(spool.get("price"), "0.01"), _dec(filament.get("price"), "0.01")) if p is not None and p >= 0), Decimal("0.00"))
    diameter = _dec(filament.get("diameter"), "0.01")
    colour = _text(filament.get("color_hex"), 7).lstrip("#").lower()
    return {
        "brand": _text(vendor.get("name"), 100) or "Spoolman", "product_type": "", "material": _text(filament.get("material"), 40),
        "colour": _text(filament.get("name"), 40), "colour_hex": f"#{colour}" if HEX.match(colour) else "",
        "roll_weight_g": min(weight, Decimal("99999999.9")), "price": min(price, Decimal("9999999999.99")),
        "remaining_g": min(max(left, Decimal(0)), Decimal("99999999.9")), "barcode": _text(filament.get("article_number"), 100),
        "diameter_mm": diameter if diameter and 0 < diameter <= 5 else Decimal("1.75"),
        "print_temp_c": _temp(filament.get("settings_extruder_temp"), 500), "bed_temp_c": _temp(filament.get("settings_bed_temp"), 200),
        "notes": _text(spool.get("comment"), 1000), "archived": bool(spool.get("archived")),
    }


def _differs(row: dict, values: dict) -> bool:
    return any(row[k] != v for k, v in values.items())


# --- reporting what was used -----------------------------------------------------------------------------------------

def queue_use(conn, spoolman_id: int, grams: Decimal) -> None:
    """Called inside the transaction that books the filament: the grams are owed to Spoolman from now on."""
    if grams > 0:
        conn.execute("INSERT INTO spoolman_pending_use (spoolman_id, grams) VALUES (%s, %s)", (spoolman_id, grams))


def flush(*, wait: bool) -> tuple[int, int]:
    """Send what is owed to Spoolman, oldest first; (sent, dropped). Each use is its own transaction, so one that was sent is gone even when the
    next one fails. A use that Spoolman refuses for good (the spool no longer exists) is dropped, anything else stays for the next time and ends
    the run. `wait` is whether to queue behind another flush that holds a row (a sync does, so the weights it reads are final) or to leave it
    to that flush (a booking does)."""
    sent = dropped = last = 0
    while True:
        with pool().connection() as conn:
            row = conn.execute("SELECT id, spoolman_id, grams FROM spoolman_pending_use WHERE id > %s ORDER BY id LIMIT 1 FOR UPDATE"
                               + ("" if wait else " SKIP LOCKED"), (last,)).fetchone()
            if row is None:
                return sent, dropped
            last = row["id"]
            try:
                _call("PUT", f"/spool/{row['spoolman_id']}/use", json={"use_weight": float(row["grams"])})
                sent += 1
            except SpoolmanError as exc:
                if exc.retry:
                    raise
                dropped += 1
                log.warning("Spoolman refused a use of %s g on spool %s; dropped", row["grams"], row["spoolman_id"])
            conn.execute("DELETE FROM spoolman_pending_use WHERE id = %s", (row["id"],))


def flush_after_booking() -> None:
    """Best effort, after the booking has been committed: Spoolman being away must never fail it, the rows wait for the next sync."""
    if not enabled():
        return
    try:
        flush(wait=False)
    except SpoolmanError:
        pass


# --- the sync ----------------------------------------------------------------------------------------------------------

def sync(conn) -> dict:
    """Read every spool and bring the rolls in line (what is owed to Spoolman has been sent by now: see `run_sync`)."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
    spools, skipped = fetch_spools()
    owed: dict[int, Decimal] = {r["spoolman_id"]: r["total"] for r in conn.execute(
        "SELECT spoolman_id, sum(grams) AS total FROM spoolman_pending_use GROUP BY spoolman_id").fetchall()}
    have = {r["spoolman_id"]: r for r in conn.execute("SELECT * FROM filament_spools WHERE spoolman_id IS NOT NULL FOR UPDATE").fetchall()}
    created = updated = 0
    for spool in spools:
        values = to_roll(spool)
        values["remaining_g"] = max(values["remaining_g"] - owed.get(spool["id"], Decimal(0)), Decimal(0))
        row = have.pop(spool["id"], None)
        if row is None:
            if values["archived"]:
                continue                                 # an archived spool that was never here is not worth a roll
            row = conn.execute(f"INSERT INTO filament_spools (spoolman_id, spoolman_synced_at, {', '.join(values)}) "
                               f"VALUES (%s, now(), {', '.join(['%s'] * len(values))}) RETURNING *", (spool["id"], *values.values())).fetchone()
            _share_notify(conn, row, explicit=False, creating=True)      # a new roll of a kind that is watched is watched too
            created += 1
            continue
        if _differs(row, values):
            conn.execute(f"UPDATE filament_spools SET {', '.join(f'{k} = %s' for k in values)} WHERE id = %s", (*values.values(), row["id"]))
            updated += 1
        conn.execute("UPDATE filament_spools SET spoolman_synced_at = now() WHERE id = %s", (row["id"],))
    gone = [r["id"] for r in have.values() if not r["archived"]]
    if gone:
        conn.execute("UPDATE filament_spools SET archived = true WHERE id = ANY(%s)", (gone,))
    return {"created": created, "updated": updated, "archived": len(gone), "skipped": skipped, "total": len(spools)}


# --- the library to Spoolman ----------------------------------------------------------------------------------------------

LOCK_PUSH = 7_210_026                   # advisory lock: one push at a time
MAX_CREATED = 300                       # new filaments per run: every one is a request, and the screen waits; run it again for the rest
DENSITY = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07, "TPU": 1.21, "PC": 1.20, "PA": 1.14, "PVA": 1.23, "HIPS": 1.04, "PET": 1.38}
DEFAULT_DENSITY = 1.24                  # Spoolman insists on one; it is only used to turn grams into metres, so a rough value is harmless


def _density(material: str) -> float:
    word = re.split(r"[^A-Za-z]+", material.strip())[0].upper() if material.strip() else ""
    return DENSITY.get(word, DEFAULT_DENSITY)


def filament_of(entry: dict) -> dict:
    """The Spoolman filament for a library entry: the colour (with the type before it, as SpoolmanDB names them) is the name, the barcode
    (else the SKU) the article number, and the reference price, excl. VAT as everywhere in this app, the price. The reverse of `to_roll`."""
    name = " ".join(x for x in (entry["product_type"], entry["colour"]) if x)[:64]
    material = entry["material"][:64]
    body = {"name": name, "material": material, "price": float(entry["price"]) if entry["price"] is not None else None,
            "density": _density(material), "diameter": float(entry["diameter_mm"]), "weight": float(entry["roll_weight_g"]),
            "article_number": (entry["barcode"] or entry["sku"])[:64], "settings_extruder_temp": entry["print_temp_c"],
            "settings_bed_temp": entry["bed_temp_c"], "color_hex": entry["colour_hex"].lstrip("#").upper(), "comment": entry["notes"][:1024]}
    return {k: v for k, v in body.items() if v not in (None, "")}


def _same(filament: dict, vendor: str, wanted: dict) -> bool:
    """Whether Spoolman already has this filament: the vendor and the article number, else the vendor, name and material."""
    other = (filament.get("vendor") or {}).get("name") if isinstance(filament.get("vendor"), dict) else None
    if (other or "").strip().lower() != vendor.lower():
        return False
    article = wanted.get("article_number")
    if article and str(filament.get("article_number") or "").strip().lower() == article.lower():
        return True
    return (bool(wanted.get("name")) and str(filament.get("name") or "").strip().lower() == wanted["name"].lower()
            and str(filament.get("material") or "").strip().lower() == wanted.get("material", "").lower())


def push_library(conn, *, dry_run: bool) -> dict:
    """Put the filaments of the library in Spoolman that it does not have yet (a vendor first, when that is new too). Like everywhere in the
    library, what exists is only ever *completed*: a filament Spoolman already has is left as it is, and nothing is ever deleted there. It
    creates filaments, not spools: the rolls on the shelf are Spoolman's own business (a spool is added in Spoolman, and arrives with a sync)."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_PUSH,))
    entries = filament_library._rows(conn)
    vendors = {str(v.get("name") or "").strip().lower(): v["id"] for v in _pages("/vendor")[0]}
    known, _ = _pages("/filament")
    created = existing = skipped = new_vendors = left = 0
    for entry in entries:
        brand = entry["brand"].strip()[:64]
        wanted = filament_of(entry)
        if not wanted.get("name") and not wanted.get("article_number"):
            skipped += 1                                  # nothing to tell it from the other filaments of the brand by
            continue
        if any(_same(f, brand, wanted) for f in known):
            existing += 1
            continue
        if created >= MAX_CREATED:
            left += 1
            continue
        created += 1
        if brand.lower() not in vendors:
            new_vendors += 1
            if dry_run:
                vendors[brand.lower()] = 0
            else:
                vendors[brand.lower()] = _json("POST", "/vendor", json={"name": brand})[1]["id"]
        if dry_run:
            known.append({"vendor": {"name": brand}, **wanted})
            continue
        made = _json("POST", "/filament", json={**wanted, "vendor_id": vendors[brand.lower()]})[1]
        known.append({"vendor": {"name": brand}, **wanted, **({"id": made["id"]} if isinstance(made, dict) and "id" in made else {})})
    return {"created": created, "existing": existing, "vendors": new_vendors, "skipped": skipped, "left": left}


@bp.post("/push-library")
def run_push_library():
    if not enabled():
        raise ApiError(400, "spoolman.off")
    dry_run = request.args.get("dry_run") == "1"
    try:
        with pool().connection() as conn:
            return jsonify(push_library(conn, dry_run=dry_run))
    except SpoolmanError as exc:
        raise exc.api() from None


@bp.get("")
def status():
    """Whether there is a Spoolman, where, when it was last read, and how much is waiting to be reported to it."""
    if not enabled():
        return jsonify({"enabled": False})
    parts = urlparse(config().spoolman_url)
    with pool().connection() as conn:
        row = conn.execute("SELECT count(*) AS rolls, max(spoolman_synced_at) AS last FROM filament_spools WHERE spoolman_id IS NOT NULL").fetchone()
        pending = conn.execute("SELECT count(*) AS n FROM spoolman_pending_use").fetchone()["n"]
    return jsonify(_serialise({"enabled": True, "host": parts.netloc, "rolls": row["rolls"], "last_sync": row["last"], "pending": pending,
                                "can_sync": getattr(g, "role", None) == "admin"}))


@bp.post("/sync")
def run_sync():
    if not enabled():
        raise ApiError(400, "spoolman.off")
    try:
        sent, dropped = flush(wait=True)                  # what is owed goes first, or the weights read below would be older than the shelf
        with pool().connection() as conn:
            result = {**sync(conn), "sent": sent, "dropped": dropped}
    except SpoolmanError as exc:
        raise exc.api() from None
    stock_changed()                                       # what is left may have changed: see whether a kind has run low
    return jsonify(result)
