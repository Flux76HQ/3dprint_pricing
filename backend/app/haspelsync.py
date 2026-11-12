"""HaspelSync (https://github.com/Rdiger-36/HaspelSync) as the source of what a Bambu Lab printer is doing now and what is loaded in it.

HaspelSync listens to the printers over MQTT and keeps Spoolman in step with their AMS. This app only *reads* from it, to show the running print and
the filament of every slot on the Printers page; it never changes anything there. A printer here names the printer of HaspelSync it is by its serial
number (`printers.haspelsync_serial`, one printer of HaspelSync to at most one printer here).

**What leaves this module is a projection, never HaspelSync's own answer.** `build_view` names every field it passes on and validates and clamps each
one (a malformed answer gives a field that is missing, never an error and never raw text on a screen); RFID tags, chip ids, Spoolman's whole records and
whatever else HaspelSync reports stay where they are. The same rule as `/api/v1` (`public_api.py`).

**An API key of HaspelSync is a full session there** (HaspelSync has no read-only key), so what this module may do with it is limited in code: it makes
one kind of call, `_get`, a GET on one of the four fixed routes of `ROUTES`, with a serial number that matched `api.SERIAL` and is quoted. Redirects are not
followed (the key would go with them), every answer is capped in size, and the key is never logged, returned or put in a backup. It is sealed
(`passwords.seal`, `KEY_INFO`) because it has to be readable to be sent. **A key is only ever sent to the address it was saved with**: an address typed in the app
that replaces another drops the saved key unless a new one comes with it (otherwise an administrator could have the key delivered to a server of their own and
read it there), and a key from `.env` goes with the address from `.env` (`config.load_config` refuses one without the other).

The address is an administrator's and may be on the own network (as for Spoolman and the webhooks); it is never taken from a request but from `.env` or the
settings. Nothing here reaches a network in a test: `tests/test_haspelsync.py` replaces `requests.request`.
"""
import json
import logging
import math
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import requests
from flask import Blueprint, g, jsonify

from . import passwords
from .api import SERIAL
from .config import ConfigError, check_haspelsync_key, check_haspelsync_url
from .http import ApiError, config, json_body, login_required, pool
from .i18n import L, render, request_language

log = logging.getLogger(__name__)
bp = Blueprint("haspelsync", __name__, url_prefix="/api/haspelsync")

KEY_INFO = b"printpricing/haspelsync-key/v1"        # its own label: what is sealed for one purpose cannot be opened for another
TIMEOUT = (3, 8)                                    # connect, read: a screen is waiting for it, and it is asked again every few seconds
MAX_BYTES = 2 * 1024 * 1024                         # a print with a full AMS is a few tens of kB; this is only a stop for a server that never ends
CACHE_SECONDS = 4                                   # what one printer answered is kept this long, so a screen that asks every few seconds (or ten screens) cost HaspelSync one look
MAX_PRINTERS = 50                                   # printers listed: a household, not a farm, and where a malformed list is cut off
MAX_SLOTS = 40                                      # HaspelSync addresses at most 24 slots and two external holders
MAX_COLOURS = 8
STATES = ("IDLE", "PREPARE", "RUNNING", "PAUSE", "FINISH", "FAILED", "CANCEL")      # what the printer says it is doing (gcode_state)
LABEL = re.compile(r"[A-Za-z0-9-]{1,12}")           # a slot as HaspelSync names it: A1, D4, HT-A, External, External-2
HEX = re.compile(r"#?([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?")                          # six hex digits, with the alpha byte the AMS appends or without
ROUTES = {"printers": "/api/printers", "status": "/api/status/{}", "print": "/api/print/{}", "spools": "/api/spools/{}"}   # the only routes this app calls


class HaspelSyncError(Exception):
    """HaspelSync could not be reached or did not answer as HaspelSync does. `host_wide` says the address itself is the problem, so asking again for the
    next printer would only wait for the same thing; `params` are the values the sentence names."""

    def __init__(self, key: str, *, host_wide: bool = False, **params):
        super().__init__(key)
        self.key, self.host_wide, self.params = key, host_wide, params

    def api(self) -> ApiError:
        return ApiError(502, self.key, **self.params)         # 502, never HaspelSync's own 401: the screens read a 401 as "signed out"

    def words(self) -> str:
        return render(L(self.key, **self.params), request_language())


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session; the address and the key are for administrators (`access.ADMIN_ONLY`, writes only)."""


# --- where HaspelSync is -----------------------------------------------------------------------------------------

def settings() -> dict:
    """Where HaspelSync is and the key to reach it, read once per request and before the request holds a connection of its own. `.env` goes before what an
    administrator typed in the app, for each part on its own. `key_set` says there is one even when it cannot be read (SESSION_SECRET was changed)."""
    if getattr(g, "haspelsync", None) is None:
        cfg = config()
        row = None
        if not (cfg.haspelsync_url and cfg.haspelsync_api_key):
            with pool().read() as conn:
                row = conn.execute("SELECT url, api_key_enc FROM haspelsync_settings").fetchone()
        key, readable, sealed = cfg.haspelsync_api_key, True, bool(row and row["api_key_enc"])
        if not key and sealed:
            raw = passwords.unseal(cfg.session_secret, row["api_key_enc"].encode(), KEY_INFO)
            key, readable = (raw.decode() if raw is not None else ""), raw is not None
        g.haspelsync = {"url": cfg.haspelsync_url or (row["url"] if row else ""), "key": key, "key_set": bool(key) or sealed, "key_readable": readable}
    return g.haspelsync


def enabled() -> bool:
    return bool(settings()["url"])


def _get(route: str, serial: "str | None" = None):
    """The one call this module makes: a GET on one of the fixed routes of HaspelSync, answered as JSON. Nothing else of HaspelSync is ever asked."""
    found = settings()
    if not found["url"]:
        raise HaspelSyncError("haspelsync.off", host_wide=True)
    if not found["key_readable"]:
        raise HaspelSyncError("haspelsync.key_unreadable", host_wide=True)
    if not found["key"]:
        raise HaspelSyncError("haspelsync.no_key", host_wide=True)
    path = ROUTES[route]
    if "{}" in path:
        if not isinstance(serial, str) or not SERIAL.fullmatch(serial):          # it went through the same check when it was saved: this one is for a database edited by hand
            raise HaspelSyncError("haspelsync.bad_serial")
        path = path.format(quote(serial, safe=""))
    try:
        reply = requests.request("GET", found["url"] + path, timeout=TIMEOUT, allow_redirects=False, stream=True,
                                 headers={"Accept": "application/json", "Authorization": f"Bearer {found['key']}"})
    except requests.RequestException as exc:
        log.warning("HaspelSync %s failed: %s", route, type(exc).__name__)
        raise HaspelSyncError("haspelsync.unreachable", host_wide=True) from None
    try:
        status = reply.status_code
        if 300 <= status < 400:
            raise HaspelSyncError("haspelsync.redirect", host_wide=True)
        if status == 401:
            raise HaspelSyncError("haspelsync.unauthorized", host_wide=True)
        if status == 403:
            raise HaspelSyncError("haspelsync.forbidden", host_wide=True, host=urlparse(found["url"]).hostname or "")
        if status == 404 and serial:
            raise HaspelSyncError("haspelsync.not_found", serial=serial)
        if status >= 400:
            raise HaspelSyncError("haspelsync.bad_status", host_wide=status >= 500, code=status)          # `code`: `status` is a parameter of ApiError itself
        body = b""
        for chunk in reply.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES:
                raise HaspelSyncError("haspelsync.bad_reply", host_wide=True)
    finally:
        reply.close()
    try:
        return json.loads(body)
    except ValueError:
        raise HaspelSyncError("haspelsync.bad_reply", host_wide=True) from None


# --- what is passed on: every field named, validated and clamped ---------------------------------------------------------

def _num(value, low: float, high: float):
    """A finite number, held between `low` and `high`; None for anything else (a string, a boolean, NaN)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return min(max(value, low), high)


def _int(value, low: int, high: int):
    number = _num(value, low, high)
    return None if number is None else int(round(number))


def _text(value, limit: int):
    """A short text, or None when it is not one or is empty."""
    return (value.strip()[:limit] or None) if isinstance(value, str) else None


def _label(value):
    return value if isinstance(value, str) and LABEL.fullmatch(value) else None


def _colour(value):
    """`#rrggbb` in lower case from six hex digits (the alpha byte the AMS appends is dropped), or None."""
    match = HEX.fullmatch(value.strip()) if isinstance(value, str) else None
    return f"#{match.group(1).lower()}" if match else None


def _colours(*sources) -> list:
    """The colours of a slot, from the first source that has any: a list of hex strings, or the comma separated text Spoolman keeps for a multi colour filament."""
    for source in sources:
        items = source.split(",") if isinstance(source, str) else source if isinstance(source, list) else []
        found = [c for c in (_colour(i) for i in items[:MAX_COLOURS]) if c]
        if found:
            return found
    return []


def _moment(millis):
    """Epoch milliseconds as an ISO 8601 UTC moment, or None when it is not a plausible one (2000 to 2100)."""
    if isinstance(millis, bool) or not isinstance(millis, (int, float)) or not math.isfinite(millis) or not 946_684_800_000 <= millis <= 4_102_444_800_000:
        return None
    return datetime.fromtimestamp(millis / 1000, timezone.utc).isoformat(timespec="seconds")


def _iso(value):
    """A moment HaspelSync wrote as ISO 8601, written again in UTC; None when it does not read as one."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.strip()[:40].replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _slot(entry, active) -> "dict | None":
    """One slot as the screen draws it. What the printer reports about the colour goes before what Spoolman holds (it is what is really in there); the weight
    that is left is Spoolman's, because it is what the booking of every print keeps up, and is absent for a slot that no spool is linked to."""
    entry = _dict(entry)
    label = _label(entry.get("amsId"))
    if label is None:
        return None
    state = entry.get("slotState")
    if not isinstance(state, str) or state == "Empty":
        return {"label": label, "loaded": False, "active": False}
    raw, spool = _dict(entry.get("slot")), _dict(entry.get("existingSpool"))
    filament = _dict(spool.get("filament"))
    remaining = _num(spool.get("remaining_weight"), 0, 100_000)
    initial = _num(spool.get("initial_weight"), 0, 100_000)
    percentage = _num(spool.get("remaining_percentage"), 0, 100)
    if percentage is None and remaining is not None and initial:
        percentage = min(remaining / initial * 100, 100)
    return {
        "label": label, "loaded": True, "active": label == active,
        "material": _text(entry.get("material") or filament.get("material") or raw.get("tray_type"), 40),
        "vendor": _text(entry.get("vendor") or _dict(filament.get("vendor")).get("name"), 60),
        "name": _text(entry.get("filamentName") or filament.get("name") or raw.get("tray_sub_brands"), 80),
        "colours": _colours(raw.get("cols"), raw.get("tray_color"), filament.get("multi_color_hexes"), filament.get("color_hex")),
        "linked": bool(spool),
        "remaining_g": None if remaining is None else round(remaining, 1),
        "initial_g": None if initial is None else round(initial, 1),
        "remaining_pct": None if percentage is None else round(percentage),
    }


def _units(status: dict) -> list:
    """Humidity, temperature and a running drying cycle per AMS unit, as far as a unit reports them."""
    units = []
    for unit in (status.get("amsEnv") if isinstance(status.get("amsEnv"), list) else [])[:MAX_SLOTS]:
        unit = _dict(unit)
        label, drying = _label(unit.get("amsId")), _dict(unit.get("drying"))
        if label:
            running = drying.get("active") is True
            units.append({"id": label, "model": _text(unit.get("model"), 20), "humidity": _int(unit.get("humidity"), 1, 5),
                          "humidity_pct": _int(unit.get("humidityPercent"), 0, 100), "temperature": _int(unit.get("temperature"), -40, 150),
                          "drying": running, "drying_min": _int(drying.get("remainingMinutes"), 0, 100_000) if running else None})
    return units


def _uses(print_: dict) -> list:
    """What the print takes from each slot: the grams it needs in all and, once it runs, the grams used so far. HaspelSync decides which slot (`matchedAmsId`)."""
    needed, done = _dict(print_.get("fullConsumption")), _dict(print_.get("consumption"))
    uses: dict = {}
    for key, item in list(needed.items())[:MAX_SLOTS]:
        item = _dict(item)
        label = _label(item.get("matchedAmsId")) or _label(item.get("amsId"))
        if label is None:
            continue
        grams, so_far = _num(item.get("grams"), 0, 100_000), _num(_dict(done.get(key)).get("grams"), 0, 100_000)
        row = uses.setdefault(label, {"slot": label, "needed_g": 0.0, "used_g": None})          # a filament split at an AMS refill is two entries on two slots
        row["needed_g"] = round(row["needed_g"] + (grams or 0), 1)
        if so_far is not None:
            row["used_g"] = round((row["used_g"] or 0) + so_far, 1)
    return list(uses.values())


def _job(print_: dict, status: dict) -> dict:
    """The running or last print. The layers follow HaspelSync's own `humanLayers` (public/shared.js): the printer reports a count, the sliced file the index of
    its last layer, so the total is one more than that, and nothing counts past it."""
    state = print_.get("gcodeState") if print_.get("gcodeState") in STATES else status.get("gcodeState")
    state = state if state in STATES else None
    total = _int(print_.get("totalLayers"), 0, 100_000)
    total = None if total is None else total + 1
    layer = _int(print_.get("layerNum"), 0, 100_000)
    if layer is not None and total is not None:
        layer = min(layer, total)
    elapsed = _num(print_.get("elapsedMs"), 0, 10**10)
    return {
        "state": state, "busy": state in ("PREPARE", "RUNNING", "PAUSE"),
        "name": _text(print_.get("modelTitle"), 200) or _text(print_.get("jobName"), 200),
        "layer": layer, "total_layers": total, "progress_pct": round(layer / total * 100) if layer is not None and total else None,
        "preparing": print_.get("preparing") is True,
        "started_at": _moment(print_.get("startedAt")), "elapsed_s": None if elapsed is None else int(elapsed // 1000),
        "remaining_min": _int(print_.get("remainingMinutes"), 0, 100_000), "ends_at": _moment(print_.get("estimatedEndAt")),
    }


def build_view(status, print_, slots) -> dict:
    """What the Printers page shows of one printer, from the answers of HaspelSync's `status`, `print` and `spools` routes."""
    status, print_ = _dict(status), _dict(print_)
    active = _label(status.get("activeSlot"))
    shown = [s for s in (_slot(e, active) for e in (slots if isinstance(slots, list) else [])[:MAX_SLOTS]) if s]
    return {
        "name": _text(status.get("printerName"), 80),
        "connected": status.get("mqttStatus") == "Connected", "monitoring": status.get("monitoringEnabled") is not False,
        "last_report": _iso(status.get("lastMqttUpdate")),
        "job": _job(print_, status), "uses": _uses(print_), "slots": shown, "ams": _units(status),
    }


def fetch_view(serial: str) -> dict:
    status, print_ = _get("status", serial), _get("print", serial)
    if not isinstance(status, dict) or not isinstance(print_, dict):
        raise HaspelSyncError("haspelsync.bad_reply", host_wide=True)
    slots = print_.get("loadedSpools")
    if not isinstance(slots, list) or not slots:
        slots = _get("spools", serial)           # the short answer of a print whose file could not be fetched carries none
    return build_view(status, print_, slots)


def fetch_printers() -> list:
    """The printers HaspelSync knows, as the picker needs them: their serial number and name."""
    data = _get("printers")
    if not isinstance(data, list):
        raise HaspelSyncError("haspelsync.bad_reply", host_wide=True)
    found = []
    for item in data[:MAX_PRINTERS]:
        item = _dict(item)
        serial = item.get("id") if isinstance(item.get("id"), str) and SERIAL.fullmatch(item["id"]) else None
        if serial:
            found.append({"id": serial, "name": _text(item.get("name"), 80) or serial})
    return found


# --- a short memory, so asking every few seconds is not asking HaspelSync every few seconds --------------------------------

clock = time.monotonic            # a name of its own, so a test can move time
_cache: dict = {}
_lock = threading.Lock()          # Gunicorn runs threads: what is kept in the process is shared by requests that run at once


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _answer(key: tuple, make) -> dict:
    """`make()` as `{"value": ...}` or, when HaspelSync did not give one, `{"error": HaspelSyncError}`; either is kept for `CACHE_SECONDS` (a down HaspelSync
    is not asked again by every screen). The sentence is worded when read, in the language of whoever asks."""
    now = clock()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        result = {"value": make()}
    except HaspelSyncError as exc:
        result = {"error": exc}
    with _lock:
        for stale in [k for k, (at, _) in _cache.items() if now - at > 60]:
            del _cache[stale]
        _cache[key] = (now, result)
    return result


# --- the routes ----------------------------------------------------------------------------------------------------

@bp.get("")
def status():
    """Whether there is a HaspelSync, where it is and whether it has a key. An administrator also gets the whole address and what comes from .env (and
    cannot be changed here); the key itself is never part of an answer."""
    found, admin, cfg = settings(), getattr(g, "role", None) == "admin", config()
    answer = {"enabled": bool(found["url"]), "ready": bool(found["url"] and found["key"]), "can_configure": admin,
              "host": urlparse(found["url"]).netloc if found["url"] else None}
    if admin:
        answer.update({"url": found["url"], "url_from_env": bool(cfg.haspelsync_url), "key_set": found["key_set"], "key_readable": found["key_readable"],
                       "key_from_env": bool(cfg.haspelsync_api_key)})
    return jsonify(answer)


@bp.put("/settings")
def save_settings():
    """An administrator types the address and the API key. The address is checked like `HASPELSYNC_URL`, the key like `HASPELSYNC_API_KEY` and sealed. A key that is left
    out (or empty) stays, `null` removes it; **an address that replaces another removes the saved key unless a new key comes with it**. What `.env` sets is refused (409)."""
    cfg, body = config(), json_body()
    new_url = None
    if "url" in body:
        if cfg.haspelsync_url:
            raise ApiError(409, "haspelsync.locked_url")
        try:
            new_url = check_haspelsync_url(body["url"]) if isinstance(body["url"], str) else None
        except ConfigError:
            new_url = None
        if new_url is None:
            raise ApiError(400, "haspelsync.bad_url")
    typed = body.get("api_key") if "api_key" in body and body["api_key"] != "" else ...          # ... = not mentioned
    sealed = None
    if typed is not ...:
        if cfg.haspelsync_api_key:
            raise ApiError(409, "haspelsync.locked_key")
        if typed is not None:
            try:
                key = check_haspelsync_key(typed) if isinstance(typed, str) else None
            except ConfigError:
                key = None
            if not key:
                raise ApiError(400, "haspelsync.bad_key")
            sealed = passwords.seal(cfg.session_secret, key.encode("ascii"), KEY_INFO).decode("ascii")
    with pool().connection() as conn:
        row = conn.execute("SELECT url, api_key_enc FROM haspelsync_settings").fetchone()
        url, enc = (row["url"], row["api_key_enc"]) if row else ("", None)
        if new_url is not None:
            if new_url != url and typed is ...:
                enc = None                                                  # the saved key does not follow the address to a new place
            url = new_url
        if typed is not ...:
            enc = sealed
        conn.execute("INSERT INTO haspelsync_settings (singleton, url, api_key_enc) VALUES (true, %s, %s) "
                     "ON CONFLICT (singleton) DO UPDATE SET url = EXCLUDED.url, api_key_enc = EXCLUDED.api_key_enc", (url, enc))
    g.haspelsync = None
    clear_cache()
    return status()


@bp.get("/connection")
def connection():
    """The state of the connection, for the badge on the card of Settings -> Integrations: `off` (no address, or no key yet), `active` (HaspelSync answers its list of printers,
    and says how many there are) or `offline` (set up, and HaspelSync does not answer as it should, with why in the words of whoever asks). The answer is the one `/printers` keeps."""
    found = settings()
    if not found["url"]:
        return jsonify({"state": "off", "message": None, "printers": None})
    if not found["key_set"]:
        return jsonify({"state": "off", "message": HaspelSyncError("haspelsync.no_key").words(), "printers": None})
    result = _answer((found["url"], "*"), fetch_printers)
    if "error" in result:
        return jsonify({"state": "offline", "message": result["error"].words(), "printers": None})
    return jsonify({"state": "active", "message": None, "printers": len(result["value"])})


@bp.post("/test")
def test_connection():
    """Ask HaspelSync, with the saved address and key, for its printers. Passes on a verdict and how many there are, nothing else of what it answered."""
    try:
        found = fetch_printers()
    except HaspelSyncError as exc:
        raise exc.api() from None
    return jsonify({"ok": True, "printers": len(found)})


@bp.get("/printers")
def printers():
    """The printers HaspelSync knows (serial number and name), for choosing which one a printer here is."""
    if not enabled():
        raise ApiError(400, "haspelsync.off")
    result = _answer((settings()["url"], "*"), fetch_printers)
    if "error" in result:
        raise result["error"].api()
    return jsonify(result["value"])


@bp.get("/live")
def live():
    """The running print and the filament of every printer here that names a printer of HaspelSync. A printer HaspelSync does not answer for carries `error`,
    its words in the language of the person asking, and no `live`; when it is the address that fails, the printers after the first are not asked at all."""
    if not enabled():
        return jsonify({"enabled": False, "printers": []})
    url = settings()["url"]
    with pool().read() as conn:
        rows = conn.execute("SELECT id, name, haspelsync_serial FROM printers WHERE haspelsync_serial <> '' AND NOT archived ORDER BY name").fetchall()
    shown, host_down = [], None
    for row in rows[:MAX_PRINTERS]:
        serial = row["haspelsync_serial"]
        result = host_down or _answer((url, serial), lambda serial=serial: fetch_view(serial))
        if "error" in result and result["error"].host_wide:
            host_down = result
        entry = {"printer_id": str(row["id"]), "name": row["name"], "serial": serial}
        if "error" in result:
            entry.update({"live": None, "error": result["error"].key, "message": result["error"].words()})
        else:
            entry.update({"live": result["value"], "error": None, "message": None})
        shown.append(entry)
    return jsonify({"enabled": True, "printers": shown})
