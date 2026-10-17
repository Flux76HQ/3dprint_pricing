"""Web push: delivery on stated terms, quiet hours, and the outbox that defers (never discards).

The terms below are decisions, not library defaults (project baseline §11). `pywebpush` sends ttl=0,
which RFC 8030 §5.2 reads as "drop it if the device is not reachable right now": a phone that is off
or asleep would lose the message and nothing would report it.
"""
import hashlib
import ipaddress
import json
import logging
import re
import threading
import time as _time
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pywebpush import WebPushException, webpush

from .i18n import L

log = logging.getLogger(__name__)

# One day: a phone that was off overnight still gets the message in the morning, while a message
# that is a week old is noise.
TTL_SECONDS = 24 * 60 * 60
# Nothing here is time-critical (an update is available), so `low`. `high` is not used and would need
# a written justification; the test asserts it is never chosen.
URGENCY = "low"
# Not time-critical -> no sound. Safari/iOS does not implement `silent`, which is why quiet hours exist.
SILENT = True
SEND_TIMEOUT_SECONDS = 8
# RFC 8030 Topic: at most 32 characters of the URL-safe Base64 alphabet. One topic per kind, so a
# device that was unreachable only receives the newest message of each kind. An invalid topic would
# get the message rejected, so it is dropped instead (only the collapsing is lost).
TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class PushNotConfigured(RuntimeError):
    pass


def topic_for(kind: str):
    return kind if TOPIC_RE.fullmatch(kind) else None


def build_payload(kind: str, title: str, body: str, url: str = "/") -> dict:
    """What the service worker receives. Deliberately no requireInteraction and no vibration pattern:
    the app does not try to break through a Focus mode; that is the user's setting to make."""
    return {"kind": kind, "title": title, "body": body, "url": url, "tag": kind, "silent": SILENT}


def endpoint_ok(endpoint: str) -> bool:
    """The server will POST to this URL, so it must look like a public push service, not our own network."""
    try:
        parts = urlsplit(endpoint)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host or parts.port not in (None, 443) or len(endpoint) > 1000:
            return False
        try:
            ipaddress.ip_address(host)
            return False                                  # IP literals are never a push service
        except ValueError:
            pass
        return host != "localhost" and not host.endswith((".local", ".localhost", ".internal", ".lan"))
    except ValueError:
        return False


# --- quiet hours ----------------------------------------------------------------------------

def _clock(value: str) -> time:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(value)):
        raise ValueError("expected HH:MM")
    return time.fromisoformat(value)


def valid_window(window: dict) -> bool:
    try:
        ZoneInfo(window["tz"])
        _clock(window["start"])
        _clock(window["end"])
        return True
    except Exception:
        return False


def quiet_until(now_utc: datetime, window) -> "datetime | None":
    """The UTC instant at which the user's quiet window ends, if `now_utc` is inside it; otherwise None.

    A wall-clock time plus an IANA timezone name, never a UTC range or an offset (an offset starts an
    hour late after the first DST change). A window that wraps midnight is the ordinary case. Anything
    unreadable fails open (None): sending when we should have stayed quiet is the recoverable mistake.
    """
    try:
        if not window or not window.get("enabled"):
            return None
        tz = ZoneInfo(window["tz"])
        start, end = _clock(window["start"]), _clock(window["end"])
        if start == end:
            return None
        local = now_utc.astimezone(tz)
        for day in (local.date() - timedelta(days=1), local.date()):
            opens = datetime.combine(day, start, tzinfo=tz)
            closes = datetime.combine(day + timedelta(days=1 if end <= start else 0), end, tzinfo=tz)
            if opens <= local < closes:
                return closes.astimezone(timezone.utc)
        return None
    except Exception:
        return None


# --- delivery ---------------------------------------------------------------------------------

def send_one(cfg, subscription: dict, payload: dict) -> None:
    """The only place a push leaves the app; every kind (and the test button) goes through here."""
    headers = {"Urgency": URGENCY}
    topic = topic_for(payload["kind"])
    if topic:
        headers["Topic"] = topic
    webpush(
        subscription_info={"endpoint": subscription["endpoint"],
                           "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]}},
        data=json.dumps(payload),
        vapid_private_key=cfg.vapid_private_key,
        vapid_claims={"sub": cfg.vapid_subject},          # fresh dict: pywebpush adds aud/exp to it
        ttl=TTL_SECONDS,
        headers=headers,
        timeout=SEND_TIMEOUT_SECONDS,
    )


def fingerprint(endpoint: str) -> str:
    """Stable, short and not reversible: how a device finds itself in the list. The browser computes the same."""
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:16]


def describe_agent(user_agent: str):
    """"Android · Chrome" from a User-Agent string: enough to tell the owner's devices apart."""
    ua = user_agent or ""
    system = next((name for key, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
                                          ("Windows", "Windows"), ("Macintosh", "Mac"), ("CrOS", "Chromebook"),
                                          ("Linux", "Linux")) if key in ua), None)
    if system is None:
        return L("push.unknown_device")
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser", "Samsung Internet"),
                                           ("Firefox", "Firefox"), ("CriOS", "Chrome"), ("Chrome", "Chrome"),
                                           ("Safari", "Safari")) if key in ua), "")
    return f"{system} · {browser}" if browser else system


def failure_reason(exc: Exception, endpoint: str) -> L:
    """What the owner can do about it, without the push service's raw answer (that goes to the log).
    A message key, not words: it is stored as such and shown in whatever language the owner reads at the time."""
    host = urlsplit(endpoint).hostname or "?"
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (404, 410):
        return L("push.r_gone")
    if status in (401, 403):
        return L("push.r_vapid", host=host, status=status)
    if status == 413:
        return L("push.r_too_large")
    if status == 429:
        return L("push.r_rate")
    if status and status >= 500:
        return L("push.r_unavailable", host=host, status=status)
    if status:
        return L("push.r_rejected", host=host, status=status)
    return L("push.r_unreachable", host=host)


def dump_reason(reason: L) -> str:
    return json.dumps({"key": reason.key, "params": reason.params})


def load_reason(stored):
    """The stored failure as something to show: an `L` for what we wrote, or the text as it is for older rows."""
    if not stored:
        return None
    try:
        data = json.loads(stored)
        return L(data["key"], **data["params"])
    except (ValueError, KeyError, TypeError):
        return stored


def deliver_now(pool, cfg, user_id, payload: dict) -> dict:
    with pool.connection() as conn:
        subs = conn.execute("SELECT id, endpoint, p256dh, auth, user_agent FROM push_subscriptions WHERE user_id = %s "
                            "ORDER BY created_at", (user_id,)).fetchall()
    sent = failed = 0
    results = []
    for sub in subs:
        device = describe_agent(sub["user_agent"])
        try:
            send_one(cfg, sub, payload)
            sent += 1
            with pool.connection() as conn:
                conn.execute("UPDATE push_subscriptions SET last_ok_at = now(), last_error = NULL, last_error_at = NULL "
                             "WHERE id = %s", (sub["id"],))
            results.append({"id": str(sub["id"]), "device": device, "ok": True})
            continue
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):                    # the device unsubscribed or the browser dropped it
                with pool.connection() as conn:
                    conn.execute("DELETE FROM push_subscriptions WHERE id = %s", (sub["id"],))
            log.warning("push to %s failed: %s", urlsplit(sub["endpoint"]).hostname, exc)
            reason, error = failure_reason(exc, sub["endpoint"]), exc
        except Exception as exc:                        # network errors, bad keys: never take the caller down
            log.warning("push to %s failed: %s", urlsplit(sub["endpoint"]).hostname, exc)
            reason, error = failure_reason(exc, sub["endpoint"]), exc
        failed += 1
        if getattr(getattr(error, "response", None), "status_code", None) not in (404, 410):
            with pool.connection() as conn:
                conn.execute("UPDATE push_subscriptions SET last_error = %s, last_error_at = now() WHERE id = %s",
                             (dump_reason(reason), sub["id"]))
        results.append({"id": str(sub["id"]), "device": device, "ok": False, "reason": reason})
    return {"sent": sent, "failed": failed, "devices": len(subs), "results": results}


def user_window(pool, user_id):
    with pool.connection() as conn:
        row = conn.execute("SELECT preferences FROM users WHERE id = %s", (user_id,)).fetchone()
    return (row["preferences"] or {}).get("quiet_hours") if row else None


def notify(pool, cfg, user_id, kind: str, title: str, body: str, url: str = "/", now: "datetime | None" = None) -> dict:
    """Send now, or hold until the user's quiet window ends. Deferred, not discarded."""
    if not cfg.push_configured:
        raise PushNotConfigured(str(L("push.not_configured")))
    payload = build_payload(kind, title, body, url)
    until = quiet_until(now or datetime.now(timezone.utc), user_window(pool, user_id))
    if until:
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO push_outbox (user_id, kind, payload, deliver_after) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (user_id, kind) DO UPDATE SET payload = EXCLUDED.payload, "
                "deliver_after = EXCLUDED.deliver_after, created_at = now()",
                (user_id, kind, json.dumps(payload), until))
        return {"deferred_until": until.isoformat(), "sent": 0, "failed": 0}
    return deliver_now(pool, cfg, user_id, payload)


def run_outbox_once(pool, cfg, now: "datetime | None" = None) -> int:
    """Deliver what is due. Safe to run from several workers: rows are claimed with SKIP LOCKED."""
    now = now or datetime.now(timezone.utc)
    done = 0
    with pool.connection() as conn:
        rows = conn.execute("SELECT id, user_id, payload FROM push_outbox WHERE deliver_after <= %s "
                            "ORDER BY deliver_after FOR UPDATE SKIP LOCKED LIMIT 50", (now,)).fetchall()
        for row in rows:
            until = quiet_until(now, user_window(pool, row["user_id"]))
            if until:                                    # the window moved: wait again rather than send
                conn.execute("UPDATE push_outbox SET deliver_after = %s WHERE id = %s", (until, row["id"]))
                continue
            deliver_now(pool, cfg, row["user_id"], row["payload"])
            conn.execute("DELETE FROM push_outbox WHERE id = %s", (row["id"],))
            done += 1
    return done


def start_outbox_worker(app, interval_seconds: int = 60) -> None:
    """A tiny background loop per web worker; SKIP LOCKED keeps them from stepping on each other."""
    def loop():
        while True:
            _time.sleep(interval_seconds)
            try:
                run_outbox_once(app.extensions["pool"], app.config["APP_CONFIG"])
            except Exception:
                log.exception("push outbox run failed; will retry")

    threading.Thread(target=loop, name="push-outbox", daemon=True).start()
