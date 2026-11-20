"""The Filament Manager of Bambu Lab (the spools a Bambu account keeps in the Bambu cloud, shown by Bambu Studio and Bambu Handy) as the source of
the rolls, for an installation without Spoolman.

**The interface is not an official one.** Bambu Lab publishes no API for it; the routes and fields are the ones Bambu Studio itself uses (its source
is open: `src/slic3r/GUI/fila_manager/`), and Bambu can change them at any time. Everything here is written so that such a change gives a readable
error and never a wrong roll: an answer is validated and clamped field by field (`to_roll`), a malformed spool is skipped and counted.

**Signing in.** An administrator types the e-mail address and password of the Bambu account once (`POST /login`); Bambu then usually mails a code, or
asks for the code of an authenticator app, which completes the login (`POST /login/code`). The password is sent to Bambu's login route and nowhere else,
and is never stored or logged. What comes back is a token, valid for about three months and not renewable (Bambu's refresh route does not work): after
that the card asks to sign in again. The token is sealed (`passwords.seal`, `TOKEN_INFO`), never returned, never logged and not in a backup. The address
of Bambu is fixed per region (`HOSTS`), never taken from a request; no redirect is followed and every answer is capped in size. Bambu puts its login
behind bot protection that refuses a plain HTTP client, so the calls go through `curl_cffi` (a libcurl that presents itself as a browser), in one
function, `transport`, which is all a test has to replace.

**One roll, one row**, as with Spoolman: a sync mirrors every spool as a `filament_spools` row keyed on the cloud's number (`bambu_id`); a spool that
is new here and that a roll typed in by hand already is (`_twins`) is linked to that roll instead of added next to it; a spool that is gone from the
cloud is archived here, never deleted, because calculations point at the roll.

**What the cloud keeps and what the app keeps.** The cloud knows the brand, material, line, colour code, the full and the remaining weight (`OWNED`):
those are its to change, a sync overwrites them and the app refuses to change them while it is signed in (`api._refuse_mirrored`). It does not know a
colour *name*, a price, a barcode, the diameter or the temperatures: those are filled in once when the roll is made here (from the library entry with
the same Bambu article code, else from SpoolmanDB by colour code, `_extra`), and are the app's own afterwards, editable like on any roll. So are the notes
and the low-stock alert.

**What is used is written back.** The cloud itself never takes off what a print used for a spool without an RFID chip, so a calculation books it here
(`api.book_stock`, as without Spoolman) and the same grams go to the cloud: the booking writes them to `bambu_cloud_pending_use` in its own transaction,
and `flush` subtracts them from the spool in the cloud (a read of the spool and a `PUT` of its new weight, the way Bambu Studio edits one) right after
the booking and first in every sync. Until a use is sent, a sync subtracts it from the weight the cloud reports, so the shelf does not jump back up.

**One source at a time.** While a Spoolman is set, the rolls are Spoolman's: signing in here is refused, and so is a sync. Typing a Spoolman address
while signed in here is refused by `spoolman.save_settings`.
"""
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import jwt
from curl_cffi import requests as curl
from flask import Blueprint, g, jsonify

from . import filament_library, passwords, spoolmandb
from .api import _serialise, _share_notify, stock_changed
from .colour_names import same_name
from .db import id_list, named_lock
from .http import ApiError, config, json_body, login_required, pool
from .i18n import L, render, request_language

log = logging.getLogger(__name__)
bp = Blueprint("bambu_cloud", __name__, url_prefix="/api/bambu-cloud")

# The two Bambu clouds: the API, and the web site that finishes a login with an authenticator app. Fixed; never taken from a request.
HOSTS = {"global": ("https://api.bambulab.com", "https://bambulab.com"), "china": ("https://api.bambulab.cn", "https://bambulab.cn")}
LOGIN = "/v1/user-service/user/login"
SPOOLS = "/v1/design-user-service/my/filament/v2"
TOKEN_INFO = b"printpricing/bambu-cloud-token/v1"     # its own label: what is sealed for one purpose cannot be opened for another
PENDING_INFO = b"printpricing/bambu-cloud-login/v1"
LOCK = "bambu-cloud"                                   # named lock (db.named_lock): one sync at a time
PAGE = 100
MAX_SPOOLS = 5_000
MAX_BYTES = 8 * 1024 * 1024                            # a page of 100 spools is a few tens of kB; this only stops a server that never ends
TIMEOUT = (5, 20)                                      # connect, read: the screen waits for a sync, so it must end
PENDING_FOR = timedelta(minutes=10)                    # how long a login waits for its code; Bambu's mailed code is valid for about as long
KEPT_COOKIES = ("token", "bbl_csrf_token")             # the only cookies read from an answer: the token of a 2FA login, and the CSRF token it needs
HEX = re.compile(r"^#?([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?$")
TRAY = re.compile(r"^[A-Z0-9]{2,4}-[A-Z0-9]{1,4}$")      # a Bambu article code as the RFID chip carries it ("A00-K0"); a SKU starts with it
ACCOUNT = re.compile(r"^[^\s\x00-\x1f\x7f]{3,254}$")
CODE = re.compile(r"^[0-9]{4,10}$")
OWNED = ("brand", "product_type", "material", "colour_hex", "roll_weight_g", "remaining_g", "archived")      # the cloud's to change; see the docstring
EXTRA = ("colour", "price", "barcode", "diameter_mm", "print_temp_c", "bed_temp_c", "spoolmandb_id")       # filled in once, the app's own afterwards
TOP_WEIGHT = Decimal("99999999.9")


class BambuCloudError(Exception):
    """The Bambu cloud could not be reached, refused, or did not answer as it does. `retry` is whether trying again later can help."""

    def __init__(self, key: str, *, retry: bool = True, **params):
        super().__init__(key)
        self.key, self.retry, self.params = key, retry, params

    def api(self) -> ApiError:
        return ApiError(502, self.key, **self.params)          # 502, never Bambu's own 401: the screens read a 401 as "signed out"

    def words(self) -> str:
        return render(L(self.key, **self.params), request_language())


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session; signing in, out and syncing are for administrators (`access.ADMIN_ONLY`, writes only)."""


# --- the one way out -------------------------------------------------------------------------------------------------------

@dataclass
class Reply:
    status: int
    body: bytes
    cookies: dict = field(default_factory=dict)


def transport(method: str, url: str, *, headers: dict, body) -> Reply:
    """The one function that reaches the network. No redirect is followed (a token would go with it), the answer is capped at `MAX_BYTES`, and of its
    cookies only `KEPT_COOKIES` are kept. Tests replace this function."""
    try:
        reply = curl.request(method, url, headers=headers, json=body, timeout=TIMEOUT, allow_redirects=False, impersonate="chrome", stream=True)
    except (curl.RequestsError, OSError) as exc:
        log.warning("Bambu cloud %s %s failed: %s", method, url.split("?")[0], type(exc).__name__)
        raise BambuCloudError("bambu.unreachable") from None
    try:
        data = b""
        for chunk in reply.iter_content(chunk_size=65536):
            data += chunk
            if len(data) > MAX_BYTES:
                raise BambuCloudError("bambu.bad_reply", retry=False)
        cookies = {name: reply.cookies.get(name) for name in KEPT_COOKIES if reply.cookies.get(name)}
        return Reply(reply.status_code, data, cookies)
    except (curl.RequestsError, OSError) as exc:
        log.warning("Bambu cloud %s %s broke off: %s", method, url.split("?")[0], type(exc).__name__)
        raise BambuCloudError("bambu.unreachable") from None
    finally:
        reply.close()


def _send(method: str, url: str, *, body=None, token: "str | None" = None, headers: "dict | None" = None) -> Reply:
    """A call to Bambu, with the answers that mean the same for every route turned into errors: a redirect, and the bot protection."""
    sent = {"Accept": "application/json", **(headers or {})}
    if token:
        sent["Authorization"] = f"Bearer {token}"
    reply = transport(method, url, headers=sent, body=body)
    if 300 <= reply.status < 400:
        raise BambuCloudError("bambu.redirect", retry=False)
    if reply.status in (403, 429) and b"cloudflare" in reply.body[:20000].lower():
        raise BambuCloudError("bambu.blocked")
    return reply


def _parsed(reply: Reply):
    try:
        return json.loads(reply.body)
    except ValueError:
        raise BambuCloudError("bambu.bad_reply", retry=False) from None


# --- the sign-in ----------------------------------------------------------------------------------------------------------------

def settings() -> dict:
    """The sign-in as it is stored, read once per request and before the request holds a connection of its own. `connected` says there is a token,
    even when it can no longer be read (SESSION_SECRET was changed) or has expired: the rolls are still the cloud's, and the card asks to sign in again."""
    if getattr(g, "bambu_cloud", None) is None:
        with pool().read() as conn:
            row = conn.execute("SELECT * FROM bambu_cloud_settings").fetchone()
        found = {"region": "global", "account": "", "token": "", "connected": False, "readable": True, "expires_at": None, "pending": None}
        if row:
            secret = config().session_secret
            found.update(region=row["region"], account=row["account"], expires_at=row["expires_at"], connected=bool(row["token_enc"]))
            if row["token_enc"]:
                raw = passwords.unseal(secret, row["token_enc"].encode(), TOKEN_INFO)
                found.update(token=raw.decode() if raw is not None else "", readable=raw is not None)
            until = row["pending_until"]
            if row["pending_enc"] and until and until > datetime.now(timezone.utc):
                raw = passwords.unseal(secret, row["pending_enc"].encode(), PENDING_INFO)
                try:
                    found["pending"] = json.loads(raw) if raw is not None else None
                except ValueError:
                    found["pending"] = None
        g.bambu_cloud = found
    return g.bambu_cloud


def connected() -> bool:
    """Whether the app is signed in to a Bambu account (a token is kept, whether or not the cloud is in use)."""
    return settings()["connected"]


def active() -> bool:
    """Whether the Bambu cloud is in use: signed in, and part of the chosen source of the filament (`sources.uses`). Otherwise the sign-in rests."""
    from . import sources                                 # imported here: it is asked by what this module imports
    return connected() and sources.uses("bambu_cloud")


def _hosts(region: str) -> tuple[str, str]:
    return HOSTS.get(region, HOSTS["global"])


def _expiry(token: str, seconds) -> "datetime | None":
    """When a token stops working: the `exp` of the token when it is a JWT (it is only read, never trusted for anything else), else what the login said."""
    try:
        exp = jwt.decode(token, options={"verify_signature": False}).get("exp")
        if isinstance(exp, (int, float)) and not isinstance(exp, bool) and 946_684_800 < exp < 4_102_444_800:
            return datetime.fromtimestamp(exp, timezone.utc)
    except jwt.PyJWTError:
        pass
    if isinstance(seconds, int) and not isinstance(seconds, bool) and 0 < seconds < 10 * 365 * 86400:
        return datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return None


def _save(conn, **values) -> None:
    current = conn.execute("SELECT * FROM bambu_cloud_settings").fetchone()
    row = {"region": "global", "account": "", "token_enc": None, "expires_at": None, "pending_enc": None, "pending_until": None,
           **({k: current[k] for k in ("region", "account", "token_enc", "expires_at", "pending_enc", "pending_until")} if current else {}), **values}
    conn.execute("INSERT INTO bambu_cloud_settings (singleton, region, account, token_enc, expires_at, pending_enc, pending_until) "
                 "VALUES (true, %s, %s, %s, %s, %s, %s) ON CONFLICT (singleton) DO UPDATE SET region = EXCLUDED.region, account = EXCLUDED.account, "
                 "token_enc = EXCLUDED.token_enc, expires_at = EXCLUDED.expires_at, pending_enc = EXCLUDED.pending_enc, pending_until = EXCLUDED.pending_until",
                 (row["region"], row["account"], row["token_enc"], row["expires_at"], row["pending_enc"], row["pending_until"]))


def _keep_token(region: str, account: str, token: str, seconds=None) -> None:
    if not isinstance(token, str) or not 10 <= len(token) <= 8192 or not token.isascii() or any(c.isspace() for c in token):
        raise BambuCloudError("bambu.bad_reply", retry=False)
    sealed = passwords.seal(config().session_secret, token.encode("ascii"), TOKEN_INFO).decode("ascii")
    with pool().connection() as conn:
        _save(conn, region=region, account=account, token_enc=sealed, expires_at=_expiry(token, seconds), pending_enc=None, pending_until=None)
    g.bambu_cloud = None


def _keep_pending(region: str, account: str, step: dict) -> None:
    sealed = passwords.seal(config().session_secret, json.dumps(step).encode(), PENDING_INFO).decode("ascii")
    with pool().connection() as conn:
        _save(conn, region=region, account=account, pending_enc=sealed, pending_until=datetime.now(timezone.utc) + PENDING_FOR)
    g.bambu_cloud = None


def _refuse_unless_chosen() -> None:
    from . import sources                                 # imported here: it is asked by what this module imports
    if not sources.uses("bambu_cloud"):
        raise ApiError(409, "bambu.not_chosen")


def _account(body: dict) -> str:
    account = body.get("account")
    if not isinstance(account, str) or not ACCOUNT.fullmatch(account.strip()):
        raise ApiError(400, "bambu.bad_account")
    return account.strip()


@bp.post("/login")
def login():
    """Sign in with the account and password of Bambu. Either it is done (`step: done`), or Bambu sent a code by e-mail (`step: code`) or wants the code of
    an authenticator app (`step: tfa`), which `POST /login/code` takes. The password goes to Bambu's login route only and is never kept."""
    body = json_body()
    region = body.get("region", "global")
    if not isinstance(region, str) or region not in HOSTS:
        raise ApiError(400, "bambu.bad_region")
    account = _account(body)
    password = body.get("password")
    if not isinstance(password, str) or not 1 <= len(password) <= 256:
        raise ApiError(400, "bambu.bad_password")
    try:
        reply = _send("POST", _hosts(region)[0] + LOGIN, body={"account": account, "password": password, "apiError": ""})
        if reply.status in (400, 401, 403, 404):
            raise ApiError(400, "bambu.login_failed")
        if reply.status != 200:
            raise BambuCloudError("bambu.bad_status", code=reply.status)
        answer = _parsed(reply)
        answer = answer if isinstance(answer, dict) else {}
        if answer.get("accessToken"):
            _keep_token(region, account, answer["accessToken"], answer.get("expiresIn"))
            return jsonify({"step": "done", **_status()})
        kind = answer.get("loginType")
        if kind == "verifyCode":                              # Bambu has mailed a code as part of this attempt: asking for another would send two
            _keep_pending(region, account, {"kind": "code"})
            return jsonify({"step": "code", **_status()})
        if kind == "tfa" and isinstance(answer.get("tfaKey"), str) and 0 < len(answer["tfaKey"]) <= 512:
            _keep_pending(region, account, {"kind": "tfa", "tfa_key": answer["tfaKey"]})
            return jsonify({"step": "tfa", **_status()})
        raise ApiError(400, "bambu.login_failed")
    except BambuCloudError as exc:
        raise exc.api() from None


@bp.post("/login/code")
def login_code():
    """The code from the e-mail, or from the authenticator app, that finishes a login `POST /login` started (within `PENDING_FOR`)."""
    found = settings()
    step = found["pending"]
    if not isinstance(step, dict) or step.get("kind") not in ("code", "tfa"):
        raise ApiError(400, "bambu.no_login")
    code = json_body().get("code")
    code = re.sub(r"\s+", "", code) if isinstance(code, str) else ""
    if not CODE.fullmatch(code):
        raise ApiError(400, "bambu.bad_code")
    api_host, web_host = _hosts(found["region"])
    try:
        if step["kind"] == "code":
            reply = _send("POST", api_host + LOGIN, body={"account": found["account"], "code": code})
            answer = _parsed(reply) if reply.status == 200 else {}
            token = answer.get("accessToken") if isinstance(answer, dict) else None
            if not token:
                raise ApiError(400, "bambu.code_wrong")
            _keep_token(found["region"], found["account"], token, answer.get("expiresIn"))
        else:
            # The web site refuses the second step without its CSRF token: fetched first, sent back as a cookie and a header (as the browser does).
            csrf = _send("GET", web_host + "/api/csrf").cookies.get("bbl_csrf_token")
            if not csrf or not re.fullmatch(r"[A-Za-z0-9._~+/=-]{8,512}", csrf):
                raise BambuCloudError("bambu.bad_reply", retry=False)
            reply = _send("POST", web_host + "/api/sign-in/tfa", body={"tfaKey": step.get("tfa_key", ""), "tfaCode": code},
                          headers={"x-bbl-csrf-token": csrf, "Cookie": f"bbl_csrf_token={csrf}"})
            token = reply.cookies.get("token") if reply.status == 200 else None
            if not token:
                raise ApiError(400, "bambu.code_wrong")
            _keep_token(found["region"], found["account"], token)
    except BambuCloudError as exc:
        raise exc.api() from None
    return jsonify({"step": "done", **_status()})


@bp.post("/login/resend")
def login_resend():
    """Ask Bambu for a new code for the login that waits for one (an e-mail, or a text message for an account that is a phone number)."""
    found = settings()
    step = found["pending"]
    if not isinstance(step, dict) or step.get("kind") != "code":
        raise ApiError(400, "bambu.no_login")
    account = found["account"]
    path, body = (("/v1/user-service/user/sendemail/code", {"email": account, "type": "codeLogin"}) if "@" in account
                  else ("/v1/user-service/user/sendsmscode", {"phone": account, "type": "codeLogin"}))
    try:
        reply = _send("POST", _hosts(found["region"])[0] + path, body=body)
        if reply.status != 200:
            raise BambuCloudError("bambu.bad_status", code=reply.status)
    except BambuCloudError as exc:
        raise exc.api() from None
    _keep_pending(found["region"], account, step)              # a new code, a new ten minutes
    return jsonify({"ok": True})


@bp.delete("/login")
def logout():
    """Sign out: the token and a login that waits are forgotten (the account and region stay, to fill in the next sign-in). The rolls stay as they are and
    keep their link, so signing in to the same account again updates them; until then they can be edited like any roll. What still waits to be written
    back waits too: signed in again, the next sync sends it (to another account, whose spools have other numbers, it is dropped)."""
    with pool().connection() as conn:
        _save(conn, token_enc=None, expires_at=None, pending_enc=None, pending_until=None)
    g.bambu_cloud = None
    from . import bambu_live                              # imported here: that module imports this one
    bambu_live.close()                                    # this worker's live connection; another worker's closes when nobody asks for it
    return jsonify(_status())


# --- reading the spools ------------------------------------------------------------------------------------------------------

def _authed(method: str, path: str, body=None):
    """A call with the token, answered as JSON. 401 means the token is no longer valid: sign in again."""
    found = settings()
    if not found["connected"]:
        raise BambuCloudError("bambu.off", retry=False)
    if not found["readable"]:
        raise BambuCloudError("bambu.token_unreadable", retry=False)
    reply = _send(method, _hosts(found["region"])[0] + path, body=body, token=found["token"])
    if reply.status == 401:
        raise BambuCloudError("bambu.expired", retry=False)
    if reply.status >= 400:
        raise BambuCloudError("bambu.bad_status", retry=reply.status >= 500, code=reply.status)
    return _parsed(reply)


def fetch_spools() -> tuple[list[dict], int]:
    """Every spool of the account, and how many entries were not an object with a whole-number id."""
    found, skipped, offset = [], 0, 0
    while True:
        page = _authed("GET", f"{SPOOLS}?offset={offset}&limit={PAGE}")
        hits = page.get("hits") if isinstance(page, dict) else None
        if not isinstance(hits, list):
            raise BambuCloudError("bambu.bad_reply", retry=False)
        for item in hits:
            if isinstance(item, dict) and isinstance(item.get("id"), int) and not isinstance(item["id"], bool) and item["id"] > 0:
                found.append(item)
            else:
                skipped += 1
        offset += len(hits)
        total = page.get("total")
        if not hits or len(hits) < PAGE or (isinstance(total, int) and offset >= total):
            return found, skipped
        if offset >= MAX_SPOOLS:
            raise BambuCloudError("bambu.too_many", retry=False, max=MAX_SPOOLS)


def _dec(value, places: str):
    """A number as Decimal rounded to `places`, or None when it is not a finite number."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number.quantize(Decimal(places)) if number.is_finite() else None


def _text(value, limit: int) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _hex(spool: dict) -> str:
    """`#rrggbb` from the spool's first colour (the alpha byte Bambu appends is dropped), or ""."""
    colours = spool.get("colors")
    first = colours[0] if isinstance(colours, list) and colours else spool.get("color")
    match = HEX.fullmatch(first.strip()) if isinstance(first, str) else None
    return f"#{match.group(1).lower()}" if match else ""


def to_roll(spool: dict) -> dict:
    """The columns of a roll that the cloud keeps (`OWNED`), from one spool. Bambu's *filamentName* is the material with its line ("PLA Basic", "PETG HF"):
    the line is what a roll calls its type."""
    material = _text(spool.get("filamentType"), 40) or _text(spool.get("category"), 40)
    name = _text(spool.get("filamentName"), 100)
    line = name[len(material):].strip() if material and name.lower().startswith(material.lower()) else name
    total = _dec(spool.get("totalNetWeight"), "0.1")
    left = _dec(spool.get("netWeight"), "0.1")
    return {"brand": _text(spool.get("filamentVendor"), 100) or "Bambu Lab", "product_type": line[:60], "material": material, "colour_hex": _hex(spool),
            "roll_weight_g": min(total, TOP_WEIGHT) if total and total > 0 else Decimal("1000.0"),
            "remaining_g": min(max(left or Decimal(0), Decimal(0)), TOP_WEIGHT), "archived": False}


RFID = re.compile(r"^[0-9A-F]{8,32}$")
SERIAL = re.compile(r"^[0-9A-Z]{6,32}$")


def tag_of(rfid) -> str:
    """The trace of an RFID chip that this app keeps: its SHA-256, never the chip's number. "" for no chip (Bambu writes zeros for a spool without one)."""
    chip = rfid.strip().upper() if isinstance(rfid, str) else ""
    return hashlib.sha256(chip.encode()).hexdigest() if RFID.fullmatch(chip) and chip.strip("0") else ""


def _slot_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    return value if isinstance(value, int) and 0 <= value <= 255 else None


def trace(spool: dict) -> dict:
    """Where the cloud says a spool is, for the live view (`bambu_live`): the trace of its chip, and the printer, AMS and slot the Filament Manager last saw
    it in ("<serial>/<AMS>/<slot>"), or "" when it is not in a printer or a part of that does not read as one."""
    serial = spool.get("devId").strip().upper() if isinstance(spool.get("devId"), str) else ""
    ams, slot = _slot_number(spool.get("amsId")), _slot_number(spool.get("slotId"))
    place = f"{serial}/{ams}/{slot}" if spool.get("inPrinter") is True and SERIAL.fullmatch(serial) and ams is not None and slot is not None else ""
    return {"bambu_tag": tag_of(spool.get("RFID")), "bambu_slot": place}


def _article(spool: dict) -> str:
    code = _text(spool.get("trayIdName"), 20).upper()
    return code if TRAY.fullmatch(code) else ""


def _from_library(entries: list, spool: dict, owned: dict) -> "dict | None":
    """The library entry this spool is: the same brand and the Bambu article code its SKU starts with (an RFID spool says it), the same weight first;
    else the same brand, material, line and colour code."""
    brand = owned["brand"].lower()
    mine = [e for e in entries if e["brand"].strip().lower() == brand]
    code = _article(spool)
    if code:
        found = [e for e in mine if (e["sku"] or "").upper().startswith(code + "-")]
        if found:
            return min(found, key=lambda e: (e["roll_weight_g"] != owned["roll_weight_g"], e["created_at"]))
    if owned["colour_hex"]:
        found = [e for e in mine if e["colour_hex"] == owned["colour_hex"] and e["material"].strip().lower() == owned["material"].lower()
                 and e["product_type"].strip().lower() == owned["product_type"].lower()]
        if found:
            return found[0]
    return None


def _from_spoolmandb(owned: dict) -> "dict | None":
    """The SpoolmanDB filament with this brand, material and colour code. SpoolmanDB names a line before the colour ("HF Black", "Matte Ivory White") and
    Bambu Lab's standard line without one ("Black"): the line of the spool picks the name that starts with it, and without a line (or "Basic") the shortest."""
    if not owned["colour_hex"]:
        return None
    try:
        rows = spoolmandb.current()["rows"]
    except (OSError, ValueError):
        return None
    colour, brand, material = owned["colour_hex"][1:], owned["brand"].lower(), owned["material"].lower()
    found = [r for r in rows if r["hex"] == colour and r["brand"].lower() == brand and r["material"].lower() == material]
    line = owned["product_type"].lower()
    if line and line != "basic":
        named = [r for r in found if r["name"].lower().startswith(line + " ")]
        return min(named, key=lambda r: (r["weight"] != float(owned["roll_weight_g"]), r["id"])) if named else None
    return min(found, key=lambda r: (len(r["name"]), r["weight"] != float(owned["roll_weight_g"]), r["id"])) if found else None


def _extra(entries: list, spool: dict, owned: dict) -> dict:
    """What the cloud does not know about a spool, filled in once when its roll is made here: from the library entry it is, else the colour name and
    specs from SpoolmanDB, else the colour code as its name (two colours of one line must never become one kind). The price is the library's, or 0."""
    entry = _from_library(entries, spool, owned)
    if entry:
        return {"colour": entry["colour"][:40] or owned["colour_hex"].upper(), "price": entry["price"] if entry["price"] is not None else Decimal("0.00"),
                "barcode": entry["barcode"], "diameter_mm": entry["diameter_mm"], "print_temp_c": entry["print_temp_c"], "bed_temp_c": entry["bed_temp_c"],
                "spoolmandb_id": entry["spoolmandb_id"]}
    row = _from_spoolmandb(owned)
    if row:
        line = owned["product_type"]
        name = row["name"][len(line):].strip() if line and row["name"].lower().startswith(line.lower() + " ") else row["name"]
        return {"colour": name[:40], "price": Decimal("0.00"), "barcode": "", "diameter_mm": _dec(row["diameter"], "0.01") or Decimal("1.75"),
                "print_temp_c": row["extruder_temp"], "bed_temp_c": row["bed_temp"], "spoolmandb_id": row["id"]}
    return {"colour": owned["colour_hex"].upper(), "price": Decimal("0.00"), "barcode": "", "diameter_mm": Decimal("1.75"), "print_temp_c": None,
            "bed_temp_c": None, "spoolmandb_id": ""}


# --- one roll, one row ----------------------------------------------------------------------------------------------------------

def _same(roll: dict, owned: dict, extra: dict) -> bool:
    """Whether a roll typed in here is this spool: the same brand and material, the same line (or one of them has none), and the same colour, by its code
    or by its name read in either language. A roll without a colour is nobody's twin."""
    if roll["brand"].strip().lower() != owned["brand"].lower() or roll["material"].strip().lower() != owned["material"].lower():
        return False
    lines = (roll["product_type"].strip().lower(), owned["product_type"].lower())
    if all(lines) and lines[0] != lines[1]:
        return False
    if roll["colour_hex"] and owned["colour_hex"]:
        return roll["colour_hex"] == owned["colour_hex"]
    return bool(roll["colour"]) and same_name(roll["colour"], extra["colour"])


def _twins(spools: list, typed: list, described: dict) -> dict:
    """Which roll typed in here is which of these spools: {spool id: roll}. One roll is never two spools and one spool never two rolls; where several of
    one kind could be each other's, the nearest in weight are paired first, then the first spool read and the oldest roll."""
    close = sorted((abs(roll["remaining_g"] - described[s["id"]][0]["remaining_g"]), i, j) for i, s in enumerate(spools) for j, roll in enumerate(typed)
                   if _same(roll, *described[s["id"]]))
    twins, paired = {}, set()
    for _, i, j in close:
        if spools[i]["id"] not in twins and j not in paired:
            twins[spools[i]["id"]] = typed[j]
            paired.add(j)
    return twins


def _link(conn, roll: dict, spool_id: int, owned: dict, extra: dict, traces: dict) -> None:
    """A roll typed in here turns out to be this spool: it is that spool's roll from now on, with the cloud's details. It keeps its id (calculations point
    at it), its notes and alert, and of `EXTRA` whatever it already had; only what it lacked is filled in."""
    values = {**owned, **traces, **{k: v for k, v in extra.items() if roll[k] in ("", None) or (k == "price" and roll[k] == 0)}}
    conn.execute(f"UPDATE filament_spools SET bambu_id = %s, bambu_synced_at = now(), {', '.join(f'{k} = %s' for k in values)} WHERE id = %s",
                 (spool_id, *values.values(), roll["id"]))


# --- writing back what was used ---------------------------------------------------------------------------------------------------

LEASE = timedelta(minutes=2)            # how long a use that is being sent is left alone by other flushes; longer than the request can take


def _claim_use(last: int, *, wait: bool):
    """The oldest use after `last` that no other flush is sending, now claimed for `LEASE`; None when there is none. With `wait`, a use that another
    flush is sending is waited for instead of skipped."""
    while True:
        now = datetime.now(timezone.utc)
        with pool().connection() as conn:
            row = conn.execute("UPDATE bambu_cloud_pending_use SET claimed_until = %s WHERE id = (SELECT id FROM bambu_cloud_pending_use WHERE id > %s "
                               "AND (claimed_until IS NULL OR claimed_until < %s) ORDER BY id LIMIT 1) RETURNING id, bambu_id, grams",
                               (now + LEASE, last, now)).fetchone()
            busy = wait and row is None and conn.execute("SELECT 1 FROM bambu_cloud_pending_use WHERE id > %s AND claimed_until >= %s",
                                                         (last, now)).fetchone()
        if row is not None or not busy:
            return row
        time.sleep(0.2)


def _release(use_id: int) -> None:
    with pool().connection() as conn:
        conn.execute("UPDATE bambu_cloud_pending_use SET claimed_until = NULL WHERE id = %s", (use_id,))


def flush(spools: "dict | None" = None, *, wait: bool) -> tuple[int, int]:
    """Write what calculations used back to the cloud, oldest first; (sent, dropped). `spools` is what was just read ({id: spool}; read here when it is
    None and there is something to send) and is kept current, so a second use of one spool starts from the weight the first one left. Each use is
    claimed, sent and deleted on its own. A use of a spool that is no longer in the cloud, or that Bambu refuses as malformed, is dropped; any other
    failure leaves it for the next time and ends the run. No transaction is open while Bambu is called."""
    sent = dropped = last = 0
    while True:
        row = _claim_use(last, wait=wait)
        if row is None:
            return sent, dropped
        last = row["id"]
        try:
            if spools is None:
                spools = {s["id"]: s for s in fetch_spools()[0]}
            spool = spools.get(row["bambu_id"])
            if spool is None:
                dropped += 1
                log.warning("A use of %s g on Bambu spool %s was dropped: the spool is no longer in the cloud", row["grams"], row["bambu_id"])
            else:
                left = max((_dec(spool.get("netWeight"), "0.1") or Decimal(0)) - row["grams"], Decimal(0))
                grams = int(left.to_integral_value())
                name = _text(spool.get("filamentName"), 100) or _text(spool.get("filamentType"), 40)       # an edit must name it, as Bambu Studio's does
                _authed("PUT", SPOOLS, {"id": spool["id"], "filamentName": name, "netWeight": grams})
                spool["netWeight"] = grams
                sent += 1
        except BambuCloudError as exc:
            if exc.key == "bambu.bad_status" and exc.params.get("code") in (400, 404, 422):
                dropped += 1
                log.warning("Bambu refused a use of %s g on spool %s (status %s); dropped", row["grams"], row["bambu_id"], exc.params["code"])
            else:
                _release(row["id"])
                raise
        with pool().connection() as conn:
            conn.execute("DELETE FROM bambu_cloud_pending_use WHERE id = %s", (row["id"],))


def write_back() -> int:
    """After a booking: send what it used now, if the cloud answers; what it does not take waits for the next sync. Returns how many uses still wait."""
    try:
        flush(wait=False)
    except BambuCloudError as exc:
        log.warning("Writing a booking back to the Bambu cloud failed (%s); it is sent with the next sync", exc.key)
    with pool().read() as conn:
        return conn.execute("SELECT count(*) AS n FROM bambu_cloud_pending_use").fetchone()["n"]


# --- the sync ------------------------------------------------------------------------------------------------------------------

def sync(conn, spools: list, skipped: int) -> dict:
    """Bring the rolls in line with the spools just read (what was owed to the cloud has been sent by now, as far as it went: see `run_sync`)."""
    owed: dict[int, Decimal] = {}                       # added up here, not in SQL: a SUM would come back as a float
    for r in conn.execute("SELECT bambu_id, grams FROM bambu_cloud_pending_use").fetchall():
        owed[r["bambu_id"]] = owed.get(r["bambu_id"], Decimal(0)) + r["grams"]
    have = {r["bambu_id"]: r for r in conn.execute("SELECT * FROM filament_spools WHERE bambu_id IS NOT NULL").fetchall()}
    typed = conn.execute("SELECT * FROM filament_spools WHERE bambu_id IS NULL AND spoolman_id IS NULL AND NOT archived ORDER BY created_at, id").fetchall()
    entries = filament_library._rows(conn)
    spoolmandb.refresh(conn)                            # the list in use, which a sync in another worker may have replaced
    described = {}
    for spool in spools:
        owned = to_roll(spool)
        owned["remaining_g"] = max(owned["remaining_g"] - owed.get(spool["id"], Decimal(0)), Decimal(0))
        described[spool["id"]] = (owned, None)
    new = [s for s in spools if s["id"] not in have]
    for spool in new:                                    # only a roll that is made or linked needs what the cloud does not know
        described[spool["id"]] = (described[spool["id"]][0], _extra(entries, spool, described[spool["id"]][0]))
    twins = _twins(new, typed, described)
    created = updated = linked = 0
    for spool in spools:
        owned, extra = described[spool["id"]]
        row = have.pop(spool["id"], None)
        if row is None:
            twin = twins.pop(spool["id"], None)
            if twin is not None:                         # typed in here before it was read from the cloud: the same roll, so not a second row
                _link(conn, twin, spool["id"], owned, extra, trace(spool))
                linked += 1
                continue
            values = {**owned, **extra, **trace(spool), "notes": _text(spool.get("note"), 1000)}
            row = conn.execute(f"INSERT INTO filament_spools (bambu_id, bambu_synced_at, {', '.join(values)}) "
                               f"VALUES (%s, now(), {', '.join(['%s'] * len(values))}) RETURNING *", (spool["id"], *values.values())).fetchone()
            _share_notify(conn, row, explicit=False, creating=True)      # a new roll of a kind that is watched is watched too
            created += 1
            continue
        if any(row[k] != v for k, v in owned.items()):
            conn.execute(f"UPDATE filament_spools SET {', '.join(f'{k} = %s' for k in owned)} WHERE id = %s", (*owned.values(), row["id"]))
            updated += 1
        traces = trace(spool)                             # where it is: not a change of the roll, so not counted as one
        if any(row[k] != v for k, v in traces.items()):
            conn.execute("UPDATE filament_spools SET bambu_tag = %s, bambu_slot = %s WHERE id = %s", (traces["bambu_tag"], traces["bambu_slot"], row["id"]))
        conn.execute("UPDATE filament_spools SET bambu_synced_at = now() WHERE id = %s", (row["id"],))
    gone = [r["id"] for r in have.values() if not r["archived"]]
    if gone:
        conn.execute("UPDATE filament_spools SET archived = true, bambu_slot = '' WHERE id IN (SELECT value FROM json_each(%s))", (id_list(gone),))
    return {"created": created, "linked": linked, "updated": updated, "archived": len(gone), "skipped": skipped, "total": len(spools)}


@bp.post("/sync")
def run_sync():
    if not connected():
        raise ApiError(400, "bambu.off")
    _refuse_unless_chosen()
    try:
        with named_lock(pool(), LOCK):                    # one sync at a time; no transaction is open while Bambu is called
            spools, skipped = fetch_spools()
            sent, dropped = flush({s["id"]: s for s in spools}, wait=True)    # what is owed goes first; the spools read are updated with it
            with pool().connection() as conn:
                result = {**sync(conn, spools, skipped), "sent": sent, "dropped": dropped}
    except BambuCloudError as exc:
        raise exc.api() from None
    stock_changed()                                       # what is left may have changed: see whether a kind has run low
    return jsonify(result)


# --- what the screens read -----------------------------------------------------------------------------------------------------

def _status() -> dict:
    """Whether the app is signed in, and how the rolls stand. An administrator also gets the account, the region, when the sign-in expires and whether a
    login waits for its code; the token never leaves the server."""
    found, admin = settings(), getattr(g, "role", None) == "admin"
    with pool().read() as conn:
        rolls = conn.execute("SELECT count(*) AS n FROM filament_spools WHERE bambu_id IS NOT NULL AND NOT archived").fetchone()["n"]
        latest = conn.execute("SELECT bambu_synced_at AS at FROM filament_spools WHERE bambu_id IS NOT NULL ORDER BY bambu_synced_at DESC LIMIT 1").fetchone()
        pending = conn.execute("SELECT count(*) AS n FROM bambu_cloud_pending_use").fetchone()["n"]
    answer = {"enabled": found["connected"], "active": active(), "can_configure": admin, "rolls": rolls,
              "last_sync": latest["at"] if latest else None, "pending": pending}
    if admin:
        expires = found["expires_at"]
        answer.update({"region": found["region"], "account": found["account"], "expires_at": expires, "token_readable": found["readable"],
                       "expired": bool(expires and expires <= datetime.now(timezone.utc)),
                       "waiting": found["pending"]["kind"] if isinstance(found["pending"], dict) else None})
    return _serialise(answer)


@bp.get("")
def status():
    return jsonify(_status())


@bp.get("/connection")
def connection():
    """The state of the connection, for the badge on the card of Settings -> Integrations: `off` (not signed in), `active` (the cloud answers the list of
    spools with this token) or `offline` (signed in, and the cloud does not answer as it should: the token expired, say, with why in the words of whoever
    asks). Nothing of what Bambu answered is passed on."""
    if not connected():
        return jsonify({"state": "off", "message": None})
    if not active():                                      # another source is chosen: the sign-in rests and Bambu is not asked
        return jsonify({"state": "resting", "message": None})
    try:
        _authed("GET", f"{SPOOLS}?offset=0&limit=1")
    except BambuCloudError as exc:
        return jsonify({"state": "offline", "message": exc.words()})
    return jsonify({"state": "active", "message": None})
