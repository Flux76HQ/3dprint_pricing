"""Webhooks: telling another application that something happened (an invoice was made, an order changed).

**What is sent.** A small message that says what happened to which order, with its numbers and where to read the rest (`/api/v1`,
`public_api.py`): `{"type": "invoice.created", "timestamp": "...", "data": {...}}`. No customer details and no prices beyond the total travel
in it, so little is lost when a message is logged somewhere.

**Signed, by a standard.** Every message is signed as Standard Webhooks describes (the headers `webhook-id`, `webhook-timestamp` and
`webhook-signature`), by the `standardwebhooks` package (baseline §19: a standard is used from a module, not written here). The receiver
checks it with the same package and the key it was shown once. That key has to be readable to sign, so it is sealed (`passwords.seal`) and
never returned again; with a changed SESSION_SECRET it cannot be read and nothing is sent until a new key is made (`rotate`).

**Kept with what it reports.** `emit(conn, ...)` writes the message in the transaction of the change itself (`webhook_deliveries`, the outbox
and the delivery log in one), so there is never a message without the change or a change without its message. A worker in every web process
sends them: a row is claimed by moving its time ahead in one statement (the lease of `push.run_outbox_once`), sent with no connection held,
and marked after. A crash in between sends it again, never loses it: **at least once**, so a receiver must ignore a `webhook-id` it has seen.
A failure is tried again after `BACKOFF`; after the last one the message is `dead` and can be sent again by hand. An address that takes
nothing for `GIVE_UP_AFTER`, or answers 410 Gone, is switched off.

**The address is an administrator's, and may be on the own network** (the owner's other applications often are, as Spoolman is), so private
addresses are allowed; only what is never an application is refused (link-local, where cloud metadata lives, multicast, the unspecified
address), checked on what the name resolves to at the moment of sending. Redirects are not followed, the answer is not read beyond its
status, and only a verdict is kept: a status and a reason key, never what the other side said.

Endpoints and their keys describe one installation's network and are credentials: they are in no backup, and a factory reset removes them."""
import base64
import ipaddress
import json
import logging
import os
import random
import secrets
import socket
import threading
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests
from flask import Blueprint, current_app, g, jsonify
from standardwebhooks.webhooks import Webhook

from . import passwords
from .api import _serialise, text
from .db import id_list
from .http import ApiError, config, json_body, pool
from .password_api import _confirm

bp = Blueprint("webhooks", __name__, url_prefix="/api/integrations/webhooks")
log = logging.getLogger("printpricing.webhooks")

# What can be reported. A name is a past-tense fact and never changes meaning; a new one is added to the end.
EVENTS = ("invoice.created", "invoice.updated", "order.created", "order.updated", "order.status_changed", "order.deleted")
PING = "ping"                                # the test message of the settings screen; not something to subscribe to
KEY_INFO = b"printpricing/webhook-key/v1"
MAX_ENDPOINTS = 10
MAX_URL = 500
TIMEOUT = (5, 10)                            # seconds to connect and to get an answer: a receiver takes the message and answers, the work comes after
LEASE = timedelta(minutes=2)                 # how long a claimed message is left alone; longer than a send can take
BACKOFF = (1, 5, 15, 60, 180, 360, 720, 1440)       # minutes before the next try, after each failure; then it is dead (about two days in all)
GIVE_UP_AFTER = timedelta(days=3)            # an address that took nothing for this long is switched off
KEEP = timedelta(days=30)                    # how long a message that arrived or was given up stays in the log
BATCH = 20
SHOWN_DELIVERIES = 50


# --- the address ---------------------------------------------------------------------------------------------------

def _not_an_application(address: str) -> bool:
    """An address that is never another application: link-local (169.254.x.x, where cloud metadata is served), multicast, or unspecified."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    return ip.is_link_local or ip.is_multicast or ip.is_unspecified


def check_url(value) -> str:
    """The address of an endpoint as it is kept: http(s) with a host, no login in it and no fragment. Raises ApiError otherwise."""
    raw = str(value or "").strip()
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise ApiError(400, "webhook.err_url") from None
    if (len(raw) > MAX_URL or parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.fragment or port == 0 or any(ch.isspace() for ch in raw)):
        raise ApiError(400, "webhook.err_url")
    if _not_an_application(parts.hostname):
        raise ApiError(400, "webhook.err_address")
    return raw


def _resolve(host: str, port: int) -> list:
    """The addresses a name stands for right now (a seam for the tests, which never ask a real name server)."""
    return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


# --- signing and sending -------------------------------------------------------------------------------------------

def new_signing_key() -> str:
    return "whsec_" + base64.b64encode(secrets.token_bytes(24)).decode("ascii")


def _signing_key(cfg, sealed) -> "str | None":
    opened = passwords.unseal(cfg.session_secret, str(sealed).encode("ascii"), KEY_INFO)
    return opened.decode("ascii") if opened else None


def message(event: str, data: dict, now: datetime) -> str:
    """The body of a message, serialised once: what is signed is what is sent, also on a retry."""
    return json.dumps({"type": event, "timestamp": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "data": data},
                      ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def send(cfg, url: str, sealed_key, message_id, body: str, now: datetime) -> "tuple[bool, int | None, str]":
    """One attempt. Returns (arrived, the HTTP status if there was an answer, a reason key when it did not arrive). Nothing of the answer
    but its status is kept, and no connection to the database is open while this runs."""
    key = _signing_key(cfg, sealed_key)
    if key is None:
        return False, None, "webhook.err_key_unreadable"
    parts = urlsplit(url)
    try:
        if any(_not_an_application(address) for address in _resolve(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))):
            return False, None, "webhook.err_address"
    except OSError:
        return False, None, "webhook.err_unreachable"
    from . import VERSION                                             # the package imports this module, so not at the top
    headers = {"Content-Type": "application/json", "User-Agent": f"3DPrintPricing-Webhooks/{VERSION}", "webhook-id": str(message_id),
               "webhook-timestamp": str(int(now.timestamp())), "webhook-signature": Webhook(key).sign(str(message_id), now, body)}
    try:
        response = requests.request("POST", url, data=body.encode("utf-8"), headers=headers, timeout=TIMEOUT, allow_redirects=False, stream=True)
        status = response.status_code
        response.close()                                              # the answer is not read: only its status says anything
    except requests.Timeout:
        return False, None, "webhook.err_timeout"
    except requests.RequestException as exc:
        log.info("Webhook to an endpoint failed: %s", type(exc).__name__)      # never the address or what was sent
        return False, None, "webhook.err_unreachable"
    if 200 <= status < 300:
        return True, status, ""
    if 300 <= status < 400:
        return False, status, "webhook.err_redirect"
    return False, status, "webhook.err_gone" if status == 410 else "webhook.err_status"


# --- the outbox ------------------------------------------------------------------------------------------------------

def emit(conn, event: str, data: dict, now: "datetime | None" = None) -> int:
    """Report `event` to every endpoint that asked for it, in the transaction `conn` is in. Returns how many messages were written.
    Two events of one change are written in the same millisecond: what keeps them in the order they happened is the order of the rows
    (`rowid`), which the sending and the log both follow."""
    now = now or datetime.now(timezone.utc)
    written = 0
    for endpoint in conn.execute("SELECT id, events FROM webhook_endpoints WHERE enabled").fetchall():
        if event in endpoint["events"]:
            conn.execute("INSERT INTO webhook_deliveries (id, endpoint_id, event, body, next_attempt_at, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                         (uuid.uuid4(), endpoint["id"], event, message(event, data, now), now, now))
            written += 1
    return written


def _settle(conn, row, endpoint_id, arrived: bool, status, reason: str, now: datetime) -> None:
    """Write down how an attempt ended: arrived, to be tried again, or given up; and what that says about the address."""
    if arrived:
        conn.execute("UPDATE webhook_deliveries SET state = 'delivered', delivered_at = %s, next_attempt_at = NULL, last_status = %s, last_error = '' WHERE id = %s",
                     (now, status, row["id"]))
        conn.execute("UPDATE webhook_endpoints SET failing_since = NULL WHERE id = %s", (endpoint_id,))
        return
    again = BACKOFF[row["attempts"] - 1] if row["attempts"] <= len(BACKOFF) else None
    if again is None:
        conn.execute("UPDATE webhook_deliveries SET state = 'dead', next_attempt_at = NULL, last_status = %s, last_error = %s WHERE id = %s", (status, reason, row["id"]))
    else:
        wait = timedelta(minutes=again) * random.uniform(0.9, 1.1)            # not all at the same second after an outage
        conn.execute("UPDATE webhook_deliveries SET next_attempt_at = %s, last_status = %s, last_error = %s WHERE id = %s", (now + wait, status, reason, row["id"]))
    endpoint = conn.execute("UPDATE webhook_endpoints SET failing_since = COALESCE(failing_since, %s) WHERE id = %s RETURNING failing_since", (now, endpoint_id)).fetchone()
    if endpoint and (reason == "webhook.err_gone" or now - endpoint["failing_since"] >= GIVE_UP_AFTER):
        conn.execute("UPDATE webhook_endpoints SET enabled = false, disabled_reason = %s WHERE id = %s", ("gone" if reason == "webhook.err_gone" else "failing", endpoint_id))


def run_once(database, cfg, now: "datetime | None" = None) -> int:
    """Send what is due. Safe to run in every web worker at once: a message is claimed by moving its time `LEASE` ahead in one statement, and
    the attempt is counted there, before the sending. Returns how many were tried."""
    now = now or datetime.now(timezone.utc)
    with database.connection() as conn:
        rows = conn.execute(
            "UPDATE webhook_deliveries SET next_attempt_at = %s, attempts = attempts + 1 WHERE id IN ("
            "SELECT d.id FROM webhook_deliveries d JOIN webhook_endpoints e ON e.id = d.endpoint_id "
            "WHERE d.state = 'pending' AND d.next_attempt_at <= %s AND e.enabled ORDER BY d.next_attempt_at, d.rowid LIMIT %s) "
            "RETURNING id, endpoint_id, body, attempts", (now + LEASE, now, BATCH)).fetchall()
        endpoints = {e["id"]: e for e in conn.execute("SELECT id, url, signing_key_enc FROM webhook_endpoints WHERE id IN (SELECT value FROM json_each(%s))",
                                                       (id_list([r["endpoint_id"] for r in rows]),)).fetchall()} if rows else {}
        conn.execute("DELETE FROM webhook_deliveries WHERE state <> 'pending' AND created_at < %s", (now - KEEP,))
    for row in rows:                                                  # no connection is held while a message is on its way
        endpoint = endpoints[row["endpoint_id"]]
        arrived, status, reason = send(cfg, endpoint["url"], endpoint["signing_key_enc"], row["id"], row["body"], now)
        with database.connection() as conn:
            _settle(conn, row, endpoint["id"], arrived, status, reason, now)
    return len(rows)


def start_worker(app, every_seconds: float = 15, stop: "threading.Event | None" = None) -> threading.Thread:
    """The loop that sends what is due, in every web worker. A run that fails is logged and the next one tries again."""
    stop = stop or threading.Event()
    database, cfg = app.extensions["pool"], app.config["APP_CONFIG"]

    def loop():
        while not stop.wait(every_seconds):
            try:
                run_once(database, cfg)
            except Exception:
                log.exception("The webhook run failed")

    thread = threading.Thread(target=loop, name="webhooks", daemon=True)
    thread.start()
    return thread


def worker_wanted(app) -> bool:
    return not app.testing and os.environ.get("WEBHOOK_WORKER", "on") != "off"


# --- the settings: endpoints, their key, the delivery log ------------------------------------------------------------------

def _events(value) -> list:
    if not isinstance(value, list) or not value or any(event not in EVENTS for event in value):
        raise ApiError(400, "webhook.err_events")
    return [event for event in EVENTS if event in value]                # each once, in the order of the catalogue


def _public(cfg, row, counts: dict) -> dict:
    out = _serialise({k: row[k] for k in ("id", "name", "url", "events", "enabled", "disabled_reason", "failing_since", "created_at")})
    out["readable"] = _signing_key(cfg, row["signing_key_enc"]) is not None      # false after SESSION_SECRET changed: a new key is needed
    out["waiting"], out["dead"] = counts.get((row["id"], "pending"), 0), counts.get((row["id"], "dead"), 0)
    return out


def _counts(conn) -> dict:
    return {(r["endpoint_id"], r["state"]): r["n"] for r in conn.execute(
        "SELECT endpoint_id, state, count(*) AS n FROM webhook_deliveries WHERE state <> 'delivered' GROUP BY endpoint_id, state").fetchall()}


def _endpoint(conn, endpoint_id):
    row = conn.execute("SELECT * FROM webhook_endpoints WHERE id = %s", (endpoint_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.not_found")
    return row


@bp.get("")
def list_endpoints():
    with pool().connection() as conn:
        rows = conn.execute("SELECT * FROM webhook_endpoints ORDER BY created_at, id").fetchall()
        counts = _counts(conn)
    return jsonify({"endpoints": [_public(config(), r, counts) for r in rows], "events": list(EVENTS), "max": MAX_ENDPOINTS})


@bp.post("")
def create_endpoint():
    body = json_body()
    name, url, events = text("f.name", max_len=60)(body.get("name")), check_url(body.get("url")), _events(body.get("events"))
    _confirm(body, "webhook-create")                                  # before the work, so a refused attempt is counted
    key = new_signing_key()
    sealed = passwords.seal(config().session_secret, key.encode("ascii"), KEY_INFO).decode("ascii")
    with pool().connection() as conn:
        if conn.execute("SELECT count(*) AS n FROM webhook_endpoints").fetchone()["n"] >= MAX_ENDPOINTS:
            raise ApiError(409, "webhook.too_many", max=MAX_ENDPOINTS)
        row = conn.execute("INSERT INTO webhook_endpoints (name, url, events, signing_key_enc, created_by) VALUES (%s, %s, %s, %s, %s) RETURNING *",
                           (name, url, json.dumps(events), sealed, g.user_id)).fetchone()
    return jsonify({"endpoint": _public(config(), row, {}), "signing_key": key}), 201      # the only time the key leaves the server


@bp.patch("/<uuid:endpoint_id>")
def update_endpoint(endpoint_id):
    """The name, what it is told, and on or off. The address cannot change: another address is another endpoint, with a key of its own."""
    body = json_body()
    with pool().connection() as conn:
        row = _endpoint(conn, endpoint_id)
        name = text("f.name", max_len=60)(body["name"]) if "name" in body else row["name"]
        events = _events(body["events"]) if "events" in body else row["events"]
        enabled = body["enabled"] if "enabled" in body else row["enabled"]
        if not isinstance(enabled, bool):
            raise ApiError(400, "webhook.err_enabled")
        fresh = enabled and not row["enabled"]                         # switched on again: it starts with a clean slate
        row = conn.execute("UPDATE webhook_endpoints SET name = %s, events = %s, enabled = %s, disabled_reason = %s, failing_since = %s WHERE id = %s RETURNING *",
                           (name, json.dumps(events), enabled, "" if enabled else row["disabled_reason"], None if fresh else row["failing_since"], endpoint_id)).fetchone()
        counts = _counts(conn)
    return jsonify({"endpoint": _public(config(), row, counts)})


@bp.post("/<uuid:endpoint_id>/rotate")
def rotate_key(endpoint_id):
    """A new signing key (the old one stops at once): after it leaked, or after SESSION_SECRET changed and the kept one cannot be read."""
    _confirm(json_body(), "webhook-rotate", str(endpoint_id))
    key = new_signing_key()
    sealed = passwords.seal(config().session_secret, key.encode("ascii"), KEY_INFO).decode("ascii")
    with pool().connection() as conn:
        row = conn.execute("UPDATE webhook_endpoints SET signing_key_enc = %s WHERE id = %s RETURNING id", (sealed, endpoint_id)).fetchone()
    if row is None:
        raise ApiError(404, "err.not_found")
    return jsonify({"signing_key": key})


@bp.delete("/<uuid:endpoint_id>")
def delete_endpoint(endpoint_id):
    _confirm(json_body(), "webhook-delete", str(endpoint_id))
    with pool().connection() as conn:
        row = conn.execute("DELETE FROM webhook_endpoints WHERE id = %s RETURNING id", (endpoint_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.not_found")
    return jsonify({"ok": True})


@bp.get("/<uuid:endpoint_id>/deliveries")
def list_deliveries(endpoint_id):
    with pool().connection() as conn:
        _endpoint(conn, endpoint_id)
        rows = conn.execute("SELECT id, event, state, attempts, next_attempt_at, last_status, last_error, created_at, delivered_at FROM webhook_deliveries "
                            "WHERE endpoint_id = %s ORDER BY created_at DESC, rowid DESC LIMIT %s", (endpoint_id, SHOWN_DELIVERIES)).fetchall()
    return jsonify({"deliveries": [_serialise(r) for r in rows]})


@bp.post("/<uuid:endpoint_id>/deliveries/<uuid:delivery_id>/retry")
def retry_delivery(endpoint_id, delivery_id):
    """A message that was given up goes back in the queue, with its tries counted from the start."""
    with pool().connection() as conn:
        row = conn.execute("UPDATE webhook_deliveries SET state = 'pending', attempts = 0, next_attempt_at = now(), last_error = '' "
                           "WHERE id = %s AND endpoint_id = %s AND state = 'dead' RETURNING id", (delivery_id, endpoint_id)).fetchone()
    if row is None:
        raise ApiError(404, "err.not_found")
    return jsonify({"ok": True})


@bp.post("/<uuid:endpoint_id>/test")
def test_endpoint(endpoint_id):
    """Send a test message now and say how it went: a verdict (arrived or not, the status, a reason), never what the other side answered."""
    now = datetime.now(timezone.utc)
    with pool().connection() as conn:
        endpoint = _endpoint(conn, endpoint_id)
    message_id, body = uuid.uuid4(), message(PING, {"message": "This is a test from 3D Print Pricing."}, now)
    arrived, status, reason = send(config(), endpoint["url"], endpoint["signing_key_enc"], message_id, body, now)       # no connection is open here
    with pool().connection() as conn:
        conn.execute("INSERT INTO webhook_deliveries (id, endpoint_id, event, body, state, attempts, last_status, last_error, created_at, delivered_at) "
                     "VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s, %s)",
                     (message_id, endpoint_id, PING, body, "delivered" if arrived else "dead", status, reason, now, now if arrived else None))
    if not arrived and reason == "webhook.err_status":
        raise ApiError(502, reason, code=status)
    if not arrived:
        raise ApiError(502, reason)
    return jsonify({"ok": True, "status": status})
