"""What a Bambu Lab printer is doing now and what is loaded in it, read from the Bambu cloud: the live panel of the Printers page for an installation
that is signed in to the Bambu account (`bambu_cloud.py`) and has no HaspelSync.

**How it is read.** A printer reports its state over MQTT, and the Bambu cloud passes those reports on to whoever is signed in to the account that owns the
printer (`us.mqtt.bambulab.com` / `cn.mqtt.bambulab.com`, TLS on port 8883, the user name `u_<uid>` and the token as the password). That is how Bambu Studio,
Bambu Handy and Home Assistant read a printer from afar; no IP address or access code of the printer is needed or stored. **It is not an official interface**,
like the Filament Manager: every field of a report is validated and clamped before it reaches a screen (`build_view`), and a report that does not read as one
is dropped. The app **only reads**: the one message it ever sends is `pushall`, the request for a full report that every one of those clients sends after it
subscribes (a printer otherwise sends only what changed). It never sends a command to a printer.

**Only while someone looks.** Each worker of the web server keeps one connection (`Listener`), opened by the first `GET /live` and closed `IDLE_SECONDS` after
the last one, so nothing runs while nobody has the Printers page open. The reports are merged in memory (a printer sends partial reports: `merge`), under a
lock, because Gunicorn runs threads. Nothing of it is written to the database.

**Which roll is in a slot.** A slot is the roll whose RFID chip it reports (`bambu_tag`, the SHA-256 the sync keeps, `bambu_cloud.trace`), else the roll the
Filament Manager last saw in that very slot (`bambu_slot`) when its material agrees; never a guess by colour. A slot that is no roll here shows what the AMS
itself reports (its estimate of what is left, when it gives one).

The printers here name the printer they are by its serial number (`printers.haspelsync_serial`, the same column HaspelSync uses: it is the serial number of the
Bambu printer, whichever service reads it). The list to pick from is the account's own (`GET /printers`).
"""
import hashlib
import json
import logging
import math
import re
import ssl
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import certifi
import jwt
import paho.mqtt.client as mqtt
from flask import Blueprint, jsonify

from . import bambu_cloud
from .api import SERIAL
from .http import ApiError, login_required, pool
from .i18n import L, render, request_language

log = logging.getLogger(__name__)
bp = Blueprint("bambu_live", __name__, url_prefix="/api/bambu-cloud")

BROKERS = {"global": "us.mqtt.bambulab.com", "china": "cn.mqtt.bambulab.com"}       # fixed; never taken from a request
PORT = 8883
KEEPALIVE = 60
IDLE_SECONDS = 90                 # a connection nobody has asked for this long is closed (the panel asks every 5 s while it is on screen)
WAIT_SECONDS = 20                 # how long a printer that has not reported since the connection opened is "waiting", before it is "not answering"
MAX_PAYLOAD = 1024 * 1024         # a full report with four AMS units is about 20 kB; a larger one is not a report
MAX_PRINTERS = 50
MAX_UNITS = 16
DEVICES = "/v1/iot-service/api/user/bind"
PREFERENCE = "/v1/design-user-service/my/preference"
STATES = ("IDLE", "PREPARE", "RUNNING", "PAUSE", "FINISH", "FAILED", "CANCEL")
HEX = re.compile(r"^#?([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?$")
USER = re.compile(r"^u_[0-9]{1,20}$")
PUSHALL = json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}})
REFUSED = {4, 5, 134, 135}        # bad user name or password, not authorised (MQTT 3.1.1 and 5): the token is no longer valid


class LiveError(Exception):
    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key, self.params = key, params

    def words(self) -> str:
        return render(L(self.key, **self.params), request_language())


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session; both only read, so they are for any signed-in person."""


# --- the reports: merged as they come, read under a lock --------------------------------------------------------------------

def merge(old, new):
    """A partial report laid over what is known: objects key by key, a list of objects that carry an `id` (AMS units, slots) item by item, anything else replaced."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = dict(old)
        for key, value in new.items():
            out[key] = merge(old.get(key), value)
        return out
    if isinstance(old, list) and isinstance(new, list) and all(isinstance(i, dict) and "id" in i for i in old + new):
        out = {str(i["id"]): i for i in old}
        for item in new:
            out[str(item["id"])] = merge(out.get(str(item["id"])), item)
        return list(out.values())
    return new


def make_client(client_id: str):
    """The MQTT client; tests replace this function and never reach the broker."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311, clean_session=True)
    client.tls_set_context(ssl.create_default_context(cafile=certifi.where()))
    client.reconnect_delay_set(min_delay=2, max_delay=60)
    return client


class Listener:
    """One connection to the Bambu cloud's MQTT, for the printers of one sign-in, in one worker. Started by `listener()`, stopped when nobody asked for
    `IDLE_SECONDS` or when the sign-in changed."""

    def __init__(self, region: str, user: str, token: str):
        self.key = (region, user, hashlib.sha256(token.encode()).hexdigest())
        self.lock = threading.Lock()
        self.serials: set = set()
        self.reports: dict = {}               # serial -> the merged `print` part of its reports
        self.heard: dict = {}                 # serial -> when it last reported (UTC)
        self.gone: set = set()                # serials the cloud said went offline
        self.connected = False
        self.error: "str | None" = None
        self.opened = datetime.now(timezone.utc)
        self.asked = time.monotonic()
        self.stopped = False
        self.client = make_client(f"printpricing-{uuid.uuid4().hex[:12]}")
        self.client.username_pw_set(user, password=token)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.connect_async(BROKERS.get(region, BROKERS["global"]), PORT, keepalive=KEEPALIVE)
        self.client.loop_start()

    # paho calls these from its own thread
    def _on_connect(self, client, userdata, flags, reason, properties=None):
        code = getattr(reason, "value", reason)
        with self.lock:
            if code:
                self.connected = False
                self.error = "bambu.expired" if code in REFUSED else "bambu.live_refused"
                serials = []
            else:
                self.connected, self.error = True, None
                serials = sorted(self.serials)
        if code in REFUSED:
            client.disconnect()                # a token that is refused stays refused: do not knock again every minute
        for serial in serials:
            self._follow(serial)

    def _on_disconnect(self, client, userdata, flags, reason, properties=None):
        with self.lock:
            self.connected = False

    def _on_message(self, client, userdata, message):
        parts = message.topic.split("/")
        if len(parts) != 3 or parts[0] != "device" or parts[2] != "report" or len(message.payload) > MAX_PAYLOAD:
            return
        serial = parts[1]
        try:
            data = json.loads(message.payload)
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        event = _dict(data.get("event")).get("event")          # the cloud says that the printer came online or went away
        report = data.get("print")
        with self.lock:
            if serial not in self.serials:
                return
            if event == "client.disconnected":
                self.gone.add(serial)
            elif event == "client.connected":
                self.gone.discard(serial)
            elif isinstance(report, dict):
                self.reports[serial] = merge(self.reports.get(serial, {}), report)
                self.heard[serial] = datetime.now(timezone.utc)
                self.gone.discard(serial)
        if event == "client.connected":
            self._ask(serial)                                    # back online: it sends only what changes, so ask for all of it once

    def _follow(self, serial: str) -> None:
        self.client.subscribe(f"device/{serial}/report")
        self._ask(serial)

    def _ask(self, serial: str) -> None:
        self.client.publish(f"device/{serial}/request", PUSHALL)

    # called by the request threads
    def want(self, serials) -> None:
        """Follow exactly these printers from now on, and note that somebody looked."""
        serials = set(serials)
        with self.lock:
            self.asked = time.monotonic()
            new, old = serials - self.serials, self.serials - serials
            self.serials = serials
            for serial in old:
                self.reports.pop(serial, None)
                self.heard.pop(serial, None)
            connected = self.connected
        for serial in old:
            self.client.unsubscribe(f"device/{serial}/report")
        if connected:
            for serial in sorted(new):
                self._follow(serial)

    def snapshot(self, serial: str) -> dict:
        with self.lock:
            return {"report": self.reports.get(serial), "heard": self.heard.get(serial), "gone": serial in self.gone, "connected": self.connected,
                    "error": self.error, "opened": self.opened}

    def idle(self) -> bool:
        with self.lock:
            return time.monotonic() - self.asked > IDLE_SECONDS

    def stop(self) -> None:
        self.stopped = True
        try:
            self.client.disconnect()
            self.client.loop_stop()
        except Exception:                      # noqa: BLE001  (a client that is already gone is stopped too)
            log.debug("Closing the Bambu live connection failed", exc_info=True)


_listener: "Listener | None" = None
_guard_lock = threading.Lock()
_reaper: "threading.Thread | None" = None


def reap_once() -> None:
    """Close the connection of this worker if nobody has asked for it for `IDLE_SECONDS`."""
    global _listener
    with _guard_lock:
        if _listener is not None and _listener.idle():
            _listener.stop()
            _listener = None


def _reap() -> None:
    """One thread per worker, started with the first connection: looks every ten seconds."""
    while True:
        time.sleep(10)
        reap_once()


def listener(region: str, user: str, token: str) -> Listener:
    """The connection of this worker for this sign-in: the running one, or a new one (a changed sign-in closes the old one first)."""
    global _listener, _reaper
    key = (region, user, hashlib.sha256(token.encode()).hexdigest())
    with _guard_lock:
        if _listener is not None and (_listener.key != key or _listener.stopped):
            _listener.stop()
            _listener = None
        if _listener is None:
            _listener = Listener(region, user, token)
        if _reaper is None or not _reaper.is_alive():
            _reaper = threading.Thread(target=_reap, name="bambu-live-reaper", daemon=True)
            _reaper.start()
        return _listener


def close() -> None:
    """Close this worker's connection now (signing out, a test)."""
    global _listener
    with _guard_lock:
        if _listener is not None:
            _listener.stop()
            _listener = None


# --- who the account is ---------------------------------------------------------------------------------------------------------

_users: dict = {}                 # token hash -> u_<uid>, so the preference route is asked once per sign-in


def user_name(token: str) -> str:
    """The MQTT user name of the account, `u_<uid>`: in the token when it is a JWT (only read, never trusted for anything else), else from Bambu's preference route."""
    key = hashlib.sha256(token.encode()).hexdigest()
    if key in _users:
        return _users[key]
    name = None
    try:
        claim = jwt.decode(token, options={"verify_signature": False}).get("username")
        name = claim if isinstance(claim, str) and USER.fullmatch(claim) else None
    except jwt.PyJWTError:
        pass
    if name is None:
        answer = bambu_cloud._authed("GET", PREFERENCE)
        uid = answer.get("uid") if isinstance(answer, dict) else None
        if isinstance(uid, bool) or not isinstance(uid, (int, str)) or not USER.fullmatch(f"u_{uid}"):
            raise bambu_cloud.BambuCloudError("bambu.bad_reply", retry=False)
        name = f"u_{uid}"
    _users[key] = name
    return name


# --- what a screen gets: every field named, validated and clamped -------------------------------------------------------------

def _num(value, low: float, high: float):
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return min(max(value, low), high)


def _int(value, low: int, high: int):
    number = _num(value, low, high)
    return None if number is None else int(round(number))


def _text(value, limit: int):
    return (" ".join(value.split())[:limit] or None) if isinstance(value, str) else None


def _colour(value):
    match = HEX.fullmatch(value.strip()) if isinstance(value, str) else None
    return f"#{match.group(1).lower()}" if match and value.strip().upper() not in ("00000000", "#00000000") else None


def _colours(tray: dict) -> list:
    found = [c for c in (_colour(i) for i in (tray.get("cols") if isinstance(tray.get("cols"), list) else [])[:8]) if c]
    return found or [c for c in (_colour(tray.get("tray_color")),) if c]


def _unit_label(ams_id: int) -> "str | None":
    """The letter of an AMS as the printer's screen shows it: 0-3 are A-D (an AMS 2 Pro too), 128 and up an AMS HT (HT-A, HT-B ...)."""
    if 0 <= ams_id <= 25:
        return chr(ord("A") + ams_id)
    if 128 <= ams_id <= 153:
        return f"HT-{chr(ord('A') + ams_id - 128)}"
    return None


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _roll_for(tray: dict, serial: str, ams_id: "int | None", tray_id: "int | None", rolls: list) -> "dict | None":
    """The roll that is in this slot: by its chip, else where the Filament Manager last saw it, when the material agrees. Never by colour."""
    tag = bambu_cloud.tag_of(tray.get("tag_uid"))
    if tag:
        found = next((r for r in rolls if r["bambu_tag"] == tag), None)
        if found:
            return found
    if ams_id is None or tray_id is None:
        return None
    place, material = f"{serial}/{ams_id}/{tray_id}", (_text(tray.get("tray_type"), 40) or "").lower()
    return next((r for r in rolls if r["bambu_slot"] == place and (not material or not r["material"] or r["material"].strip().lower() == material)), None)


def _slot(tray, label: str, active: bool, serial: str, ams_id, tray_id, rolls: list) -> dict:
    tray = _dict(tray)
    material = _text(tray.get("tray_type"), 40)
    if not material:
        return {"label": label, "loaded": False, "active": False}
    roll = _roll_for(tray, serial, ams_id, tray_id, rolls)
    remain = _int(tray.get("remain"), -1, 100)
    weight = _num(tray.get("tray_weight"), 0, 100_000)
    if roll is not None:
        left, total = float(roll["remaining_g"]), float(roll["roll_weight_g"])
        pct = round(min(left / total * 100, 100)) if total > 0 else None
    elif remain is not None and remain >= 0 and weight:                 # the AMS's own estimate (a Bambu spool with "update remaining" on)
        left, total, pct = round(weight * remain / 100, 1), weight, remain
    else:
        left = total = pct = None
    return {"label": label, "loaded": True, "active": active, "material": material,
            "vendor": None if roll is None else _text(roll["brand"], 60),
            "name": (" ".join(x for x in (roll["product_type"], roll["colour"]) if x)[:80] or None) if roll is not None else _text(tray.get("tray_sub_brands"), 80),
            "colours": _colours(tray), "linked": roll is not None, "spoolman_id": None, "roll_id": None if roll is None else str(roll["id"]),
            "estimate": roll is None and left is not None,
            "remaining_g": None if left is None else round(left, 1), "initial_g": None if total is None else round(total, 1), "remaining_pct": pct}


def _slots(report: dict, serial: str, rolls: list) -> tuple[list, list]:
    """Every slot of every AMS and the external holder, and per AMS its humidity, temperature and drying, as far as they are reported."""
    ams = _dict(report.get("ams"))
    now = _int(ams.get("tray_now"), 0, 255)
    slots, units = [], []
    for unit in (ams.get("ams") if isinstance(ams.get("ams"), list) else [])[:MAX_UNITS]:
        unit = _dict(unit)
        ams_id = _int(unit.get("id"), 0, 255)
        letter = _unit_label(ams_id) if ams_id is not None else None
        if letter is None:
            continue
        for tray in (unit.get("tray") if isinstance(unit.get("tray"), list) else [])[:4]:
            tray_id = _int(_dict(tray).get("id"), 0, 3)
            if tray_id is None:
                continue
            label = letter if letter.startswith("HT-") else f"{letter}{tray_id + 1}"
            active = now is not None and now < 254 and (now == ams_id * 4 + tray_id if ams_id < 128 else now == ams_id)
            slots.append(_slot(tray, label, active, serial, ams_id, tray_id, rolls))
        drying = _int(unit.get("dry_time"), 0, 100_000)
        units.append({"id": letter, "model": None, "humidity": _int(unit.get("humidity"), 1, 5), "humidity_pct": _int(unit.get("humidity_raw"), 0, 100),
                      "temperature": _int(unit.get("temp"), -40, 150), "drying": bool(drying), "drying_min": drying or None})
    holders = report.get("vir_slot") if isinstance(report.get("vir_slot"), list) else ([report["vt_tray"]] if isinstance(report.get("vt_tray"), dict) else [])
    for n, tray in enumerate(holders[:2]):                     # the printer always reports its external holder: an empty one is left out
        slot = _slot(tray, "Ext" if n == 0 else "Ext-2", now == 254 and n == 0, serial, None, None, rolls)
        if slot["loaded"]:
            slots.append(slot)
    return slots, units


def _job(report: dict) -> dict:
    state = report.get("gcode_state") if report.get("gcode_state") in STATES else None
    busy = state in ("PREPARE", "RUNNING", "PAUSE")
    total = _int(report.get("total_layer_num"), 0, 100_000) or None
    layer = _int(report.get("layer_num"), 0, 100_000)
    if layer is not None and total is not None:
        layer = min(layer, total)
    percent = _int(report.get("mc_percent"), 0, 100)
    remaining = _int(report.get("mc_remaining_time"), 0, 100_000)
    started = _int(report.get("gcode_start_time"), 946_684_800, 4_102_444_800)
    return {"state": state, "busy": busy, "name": _text(report.get("subtask_name"), 200), "layer": layer, "total_layers": total,
            "progress_pct": percent if percent is not None else (round(layer / total * 100) if layer is not None and total else None),
            "preparing": state == "PREPARE",
            "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(timespec="seconds") if started else None, "elapsed_s": None,
            "remaining_min": remaining, "ends_at": (datetime.now(timezone.utc) + timedelta(minutes=remaining)).isoformat(timespec="seconds") if busy and remaining else None}


def build_view(report, heard, serial: str, rolls: list, *, online: bool = True) -> dict:
    """What the Printers page shows of one printer: the same shape as the view of HaspelSync (`haspelsync.build_view`), so one panel draws both."""
    report = _dict(report)
    slots, units = _slots(report, serial, rolls)
    return {"name": None, "connected": online, "monitoring": True, "last_report": heard.isoformat(timespec="seconds") if heard else None,
            "job": _job(report), "uses": [], "slots": slots, "ams": units}


# --- the routes ------------------------------------------------------------------------------------------------------------------

_devices: dict = {}               # (token hash) -> (monotonic, [printers]); the account's printers change rarely


def fetch_printers() -> list:
    """The printers of the account (serial number and name), for choosing which one a printer here is. Kept 60 seconds. Nothing else of what Bambu reports about
    them (the access code, the IP address) is read."""
    token = bambu_cloud.settings()["token"]
    key = hashlib.sha256(token.encode()).hexdigest()
    hit = _devices.get(key)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    answer = bambu_cloud._authed("GET", DEVICES)
    devices = answer.get("devices") if isinstance(answer, dict) else None
    if not isinstance(devices, list):
        raise bambu_cloud.BambuCloudError("bambu.bad_reply", retry=False)
    found = []
    for item in devices[:MAX_PRINTERS]:
        item = _dict(item)
        serial = item.get("dev_id").strip().upper() if isinstance(item.get("dev_id"), str) else ""
        if SERIAL.fullmatch(serial):
            found.append({"id": serial, "name": _text(item.get("name"), 80) or serial})
    _devices.clear()
    _devices[key] = (time.monotonic(), found)
    return found


@bp.get("/printers")
def printers():
    if not bambu_cloud.connected():
        raise ApiError(400, "bambu.off")
    try:
        return jsonify(fetch_printers())
    except bambu_cloud.BambuCloudError as exc:
        raise exc.api() from None


def _entry(row, snap: dict, rolls: list) -> dict:
    entry = {"printer_id": str(row["id"]), "name": row["name"], "serial": row["haspelsync_serial"]}
    if snap["error"]:
        problem = LiveError(snap["error"])
    elif snap["report"] is None:
        waited = (datetime.now(timezone.utc) - snap["opened"]).total_seconds()
        problem = LiveError("bambu.live_waiting" if waited < WAIT_SECONDS else "bambu.live_silent" if snap["connected"] else "bambu.live_no_connection")
    else:
        view = build_view(snap["report"], snap["heard"], row["haspelsync_serial"], rolls, online=snap["connected"] and not snap["gone"])
        return {**entry, "live": view, "error": None, "message": None}
    return {**entry, "live": None, "error": problem.key, "message": problem.words()}


@bp.get("/live")
def live():
    """The running print and the filament of every printer here that names a printer of the account, as reported over the Bambu cloud. A printer that has
    not reported yet, or cannot be, carries `error` and its words; the connection opens with the first call and closes when nobody asks any more."""
    found = bambu_cloud.settings()
    if not found["connected"]:
        return jsonify({"enabled": False, "printers": []})
    with pool().read() as conn:
        rows = conn.execute("SELECT id, name, haspelsync_serial FROM printers WHERE haspelsync_serial <> '' AND NOT archived ORDER BY name").fetchall()
        rolls = conn.execute("SELECT id, brand, product_type, colour, material, remaining_g, roll_weight_g, bambu_tag, bambu_slot FROM filament_spools "
                             "WHERE bambu_id IS NOT NULL AND NOT archived AND (bambu_tag <> '' OR bambu_slot <> '')").fetchall()
    rows = rows[:MAX_PRINTERS]
    if not rows:
        return jsonify({"enabled": True, "printers": []})
    try:
        if not found["readable"]:
            raise bambu_cloud.BambuCloudError("bambu.token_unreadable", retry=False)
        user = user_name(found["token"])
    except bambu_cloud.BambuCloudError as exc:
        message = exc.words()
        return jsonify({"enabled": True, "printers": [{"printer_id": str(r["id"]), "name": r["name"], "serial": r["haspelsync_serial"], "live": None,
                                                        "error": exc.key, "message": message} for r in rows]})
    conn_ = listener(found["region"], user, found["token"])
    conn_.want(r["haspelsync_serial"] for r in rows)
    return jsonify({"enabled": True, "printers": [_entry(r, conn_.snapshot(r["haspelsync_serial"]), rolls) for r in rows]})
