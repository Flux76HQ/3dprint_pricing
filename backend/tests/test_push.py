"""Web push, held to the project baseline (section 11): terms stated rather than defaulted, no attempt
to break through Focus, a test button on the same terms, and quiet hours as a schedule."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import psycopg
import pytest
from pywebpush import WebPushException

from app import create_app, push
from app.config import Config
from app.db import run_migrations
from tests.conftest import ORIGIN, RP_ID, SECRET, SETUP_CODE
from tests.test_auth_api import H, onboard, post

ENDPOINT = "https://push.example.test/send/abc123"
FRONT = Path(__file__).resolve().parents[2] / "frontend"
UTC = timezone.utc


def config(database_url, tmp_path, **extra):
    return Config(database_url=database_url, session_secret=SECRET, setup_code=SETUP_CODE, rp_id=RP_ID, rp_name="Test",
                  rp_origins=(ORIGIN,), session_hours=24, cookie_secure=True, upload_dir=str(tmp_path / "up"),
                  static_dir=str(Path(__file__).parent / "static"), **extra)


@pytest.fixture
def pushapp(fresh_db, tmp_path):
    run_migrations(fresh_db)
    app = create_app(config(fresh_db, tmp_path, vapid_public_key="PUBKEY", vapid_private_key="PRIVKEY",
                            vapid_subject="mailto:admin@localhost"))
    yield app
    app.extensions["pool"].close()


@pytest.fixture
def owner(pushapp):
    client = pushapp.test_client()
    onboard(client)
    return client


def subscribe(client, endpoint=ENDPOINT):
    return post(client, "/api/push/subscribe", {"endpoint": endpoint, "keys": {"p256dh": "BP-key", "auth": "auth-secret"}})


def sent_calls(mocked):
    return mocked.call_args_list


# --- quiet-hours arithmetic -----------------------------------------------------------------------

NIGHT = {"enabled": True, "start": "22:00", "end": "07:00", "tz": "Europe/Amsterdam"}


def at(text):                      # an Amsterdam wall-clock moment, expressed as a UTC instant
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo("Europe/Amsterdam")).astimezone(UTC)


@pytest.mark.parametrize("moment, quiet", [
    ("2026-06-10 23:30", True), ("2026-06-11 06:59", True), ("2026-06-11 07:00", False),   # ends exclusively
    ("2026-06-10 22:00", True), ("2026-06-10 21:59", False), ("2026-06-10 12:00", False),
    ("2026-06-11 00:00", True),                                                              # wraps midnight
])
def test_a_window_that_wraps_midnight_is_the_ordinary_case(moment, quiet):
    result = push.quiet_until(at(moment), NIGHT)
    assert (result is not None) is quiet
    if quiet:
        assert result.astimezone(__import__("zoneinfo").ZoneInfo("Europe/Amsterdam")).strftime("%H:%M") == "07:00"
        assert result > at(moment)


def test_a_daytime_window_that_does_not_wrap():
    window = {"enabled": True, "start": "13:00", "end": "14:30", "tz": "Europe/Amsterdam"}
    assert push.quiet_until(at("2026-06-10 13:00"), window) == at("2026-06-10 14:30")
    assert push.quiet_until(at("2026-06-10 14:30"), window) is None
    assert push.quiet_until(at("2026-06-10 12:59"), window) is None


def test_the_window_follows_daylight_saving_instead_of_a_fixed_offset():
    # 29 March 2026: the clocks go forward at 02:00 in Amsterdam. 06:30 local is 04:30 UTC that morning
    # (UTC+2), but 05:30 UTC the evening before... an offset frozen at +1 would end the window an hour late.
    spring = push.quiet_until(at("2026-03-29 06:30"), NIGHT)
    assert spring == datetime(2026, 3, 29, 5, 0, tzinfo=UTC)          # 07:00 CEST
    winter = push.quiet_until(at("2026-01-15 06:30"), NIGHT)
    assert winter == datetime(2026, 1, 15, 6, 0, tzinfo=UTC)          # 07:00 CET
    autumn = push.quiet_until(at("2026-10-25 06:30"), NIGHT)           # clocks go back that night
    assert autumn == datetime(2026, 10, 25, 6, 0, tzinfo=UTC)          # 07:00 CET


@pytest.mark.parametrize("window", [
    None, {}, {"enabled": False, "start": "22:00", "end": "07:00", "tz": "Europe/Amsterdam"},
    {"enabled": True, "start": "22:00", "end": "07:00", "tz": "Mars/Olympus"},       # unreadable timezone
    {"enabled": True, "start": "25:00", "end": "07:00", "tz": "Europe/Amsterdam"},   # unreadable time
    {"enabled": True, "start": "22:00", "tz": "Europe/Amsterdam"},                   # half-written window
    {"enabled": True, "start": "08:00", "end": "08:00", "tz": "Europe/Amsterdam"},   # empty window
])
def test_anything_unreadable_fails_open_and_sends(window):
    assert push.quiet_until(at("2026-06-10 23:30"), window) is None


# --- delivery terms (baseline MUSTs) ----------------------------------------------------------------

def test_every_push_sets_a_nonzero_ttl_an_explicit_urgency_and_a_topic(owner, pushapp):
    subscribe(owner)
    with mock.patch("app.push.webpush") as mocked:
        post(owner, "/api/push/test")
    (call,) = sent_calls(mocked)
    assert call.kwargs["ttl"] > 0 and call.kwargs["ttl"] == push.TTL_SECONDS == 24 * 3600
    headers = call.kwargs["headers"]
    assert headers["Urgency"] in ("very-low", "low", "normal"), "'high' needs a written justification and a changed test"
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,32}", headers["Topic"])
    assert call.kwargs["timeout"] and call.kwargs["vapid_claims"]["sub"].startswith("mailto:")


def test_the_topic_is_per_kind_and_an_invalid_one_is_dropped_not_sent():
    assert push.topic_for("release") == "release" and push.topic_for("test") == "test"
    assert push.topic_for("x" * 33) is None and push.topic_for("no spaces!") is None and push.topic_for("") is None


def test_the_test_button_sends_on_exactly_the_terms_of_a_real_notification(owner, pushapp):
    subscribe(owner)
    cfg = pushapp.config["APP_CONFIG"]
    pool = pushapp.extensions["pool"]
    with pool.connection() as conn:
        user_id = conn.execute("SELECT id FROM users").fetchone()["id"]
    with mock.patch("app.push.webpush") as mocked:
        push.notify(pool, cfg, user_id, "release", "t", "real")       # a real notification kind
        post(owner, "/api/push/test")                                  # the button
    real, test = sent_calls(mocked)
    for key in ("ttl", "timeout"):
        assert real.kwargs[key] == test.kwargs[key]
    assert real.kwargs["headers"]["Urgency"] == test.kwargs["headers"]["Urgency"]
    real_body, test_body = json.loads(real.kwargs["data"]), json.loads(test.kwargs["data"])
    assert real_body["silent"] == test_body["silent"] is True
    assert real.kwargs["headers"]["Topic"] != test.kwargs["headers"]["Topic"]        # own subject each


def test_the_payload_never_asks_to_break_through_focus_or_vibrate():
    payload = push.build_payload("release", "t", "b", "/")
    assert payload["silent"] is True
    assert not {"requireInteraction", "vibrate"} & set(payload)


def test_the_service_worker_never_sets_require_interaction_or_a_vibration_pattern():
    source = (FRONT / "sw.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("//"))
    assert "requireInteraction" not in code and "vibrate" not in code
    assert "addEventListener('push'" in code and "addEventListener('notificationclick'" in code
    assert "showNotification" in code


def test_delivery_failures_are_handled_and_gone_subscriptions_are_removed(owner, pushapp):
    subscribe(owner)
    subscribe(owner, "https://push.example.test/send/second")
    gone = mock.Mock(status_code=410)
    boom = [WebPushException("gone", response=gone), RuntimeError("network down")]
    with mock.patch("app.push.webpush", side_effect=boom):
        result = post(owner, "/api/push/test").get_json()
    assert result["sent"] == 0 and result["failed"] == 2
    with pushapp.extensions["pool"].connection() as conn:
        left = [r["endpoint"] for r in conn.execute("SELECT endpoint FROM push_subscriptions").fetchall()]
    assert len(left) == 1                                    # the 410 one is gone, the network failure is kept


# --- quiet hours: defer, do not discard ---------------------------------------------------------------

def set_quiet(client, window):
    assert client.put("/api/preferences", json={"quiet_hours": window}, headers=H).status_code == 200


def test_during_quiet_hours_a_notification_is_held_then_delivered_when_the_window_ends(owner, pushapp):
    subscribe(owner)
    cfg, pool = pushapp.config["APP_CONFIG"], pushapp.extensions["pool"]
    set_quiet(owner, NIGHT)
    with pool.connection() as conn:
        user_id = conn.execute("SELECT id FROM users").fetchone()["id"]
    night = at("2026-06-10 23:30")
    with mock.patch("app.push.webpush") as mocked:
        result = push.notify(pool, cfg, user_id, "release", "t", "v1", now=night)
        assert result["deferred_until"].startswith(at("2026-06-11 07:00").isoformat()[:16]) and mocked.call_count == 0
        push.notify(pool, cfg, user_id, "release", "t", "v2 (newer)", now=night)           # replaces, never piles up
        assert push.run_outbox_once(pool, cfg, now=at("2026-06-11 03:00")) == 0           # still night: nothing sent
        assert mocked.call_count == 0
        assert push.run_outbox_once(pool, cfg, now=at("2026-06-11 07:00")) == 1           # morning: delivered
    (call,) = sent_calls(mocked)
    assert json.loads(call.kwargs["data"])["body"] == "v2 (newer)" and call.kwargs["ttl"] == push.TTL_SECONDS
    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM push_outbox").fetchone()["n"] == 0


def test_the_test_button_also_respects_quiet_hours_and_says_so(owner, pushapp):
    subscribe(owner)
    set_quiet(owner, {"enabled": True, "start": "00:00", "end": "23:59", "tz": "Europe/Amsterdam"})
    with mock.patch("app.push.webpush") as mocked:
        result = post(owner, "/api/push/test").get_json()
    assert "deferred_until" in result and mocked.call_count == 0


def test_an_unreadable_window_sends_instead_of_silencing(owner, pushapp):
    subscribe(owner)
    with pushapp.extensions["pool"].connection() as conn:
        conn.execute("UPDATE users SET preferences = jsonb_set(preferences, '{quiet_hours}', %s::jsonb, true)",
                     (json.dumps({"enabled": True, "start": "22:00", "end": "07:00", "tz": "Nowhere/Land"}),))
    with mock.patch("app.push.webpush") as mocked:
        result = post(owner, "/api/push/test").get_json()
    assert result["sent"] == 1 and mocked.call_count == 1


# --- API ------------------------------------------------------------------------------------------------

def test_config_reports_whether_push_is_set_up(owner, client):
    cfg = owner.get("/api/push/config").get_json()
    assert cfg["configured"] is True and cfg["public_key"] == "PUBKEY" and cfg["devices"] == 0 and cfg["ttl_hours"] == 24


def test_without_vapid_keys_push_is_off_and_says_so(app):
    client = app.test_client()
    onboard(client)
    cfg = client.get("/api/push/config").get_json()
    assert cfg["configured"] is False and cfg["public_key"] is None
    assert subscribe(client).status_code == 409 and post(client, "/api/push/test").status_code == 409


def test_subscribe_is_idempotent_validated_and_removable(owner):
    assert subscribe(owner).status_code == 200 and subscribe(owner).status_code == 200
    assert owner.get("/api/push/config").get_json()["devices"] == 1
    for bad in ("http://push.example.test/x", "https://127.0.0.1/x", "https://localhost/x", "https://db.internal/x",
                "https://push.example.test:8443/x", "not a url", ""):
        assert subscribe(owner, bad).status_code == 400, bad
    assert post(owner, "/api/push/subscribe", {"endpoint": ENDPOINT, "keys": {}}).status_code == 400
    assert post(owner, "/api/push/unsubscribe", {"endpoint": ENDPOINT}).status_code == 200
    assert owner.get("/api/push/config").get_json()["devices"] == 0
    assert post(owner, "/api/push/test").status_code == 409          # nobody to send to


def test_push_routes_need_a_session(pushapp):
    anonymous = pushapp.test_client()
    assert anonymous.get("/api/push/config").status_code == 401
    assert subscribe(anonymous).status_code == 401


def test_notification_preferences_are_validated(owner):
    assert owner.put("/api/preferences", json={"notify_release": False}, headers=H).get_json()["notify_release"] is False
    assert owner.put("/api/preferences", json={"notify_release": "no"}, headers=H).status_code == 400
    for bad in ({"enabled": True, "start": "22:00", "end": "07:00", "tz": "Mars/Olympus"},
                {"enabled": True, "start": "9pm", "end": "07:00", "tz": "Europe/Amsterdam"},
                {"enabled": "yes", "start": "22:00", "end": "07:00", "tz": "Europe/Amsterdam"}, "night", None):
        assert owner.put("/api/preferences", json={"quiet_hours": bad}, headers=H).status_code == 400, bad
    ok = owner.put("/api/preferences", json={"quiet_hours": NIGHT}, headers=H).get_json()
    assert ok["quiet_hours"] == NIGHT


# --- release announcement ---------------------------------------------------------------------------------

def test_a_new_release_is_announced_once_to_opted_in_devices(owner, pushapp):
    from announce_release import announce
    cfg, pool = pushapp.config["APP_CONFIG"], pushapp.extensions["pool"]
    subscribe(owner)
    with mock.patch("app.push.webpush") as mocked:
        assert announce(pool, cfg, "v0.6.0 (aaa1111)") == 0 and mocked.call_count == 0     # first run only records
        assert announce(pool, cfg, "v0.6.0 (aaa1111)") == 0                                 # same release: silent
        assert announce(pool, cfg, "v0.7.0 (bbb2222)") == 1                                 # new release: once
        assert announce(pool, cfg, "v0.7.0 (bbb2222)") == 0                                 # and not again
    (call,) = sent_calls(mocked)
    body = json.loads(call.kwargs["data"])
    assert "v0.7.0 (bbb2222)" in body["body"] and body["kind"] == "release" and call.kwargs["ttl"] == push.TTL_SECONDS


def test_the_announcement_respects_the_opt_out(owner, pushapp):
    from announce_release import announce
    cfg, pool = pushapp.config["APP_CONFIG"], pushapp.extensions["pool"]
    subscribe(owner)
    owner.put("/api/preferences", json={"notify_release": False}, headers=H)
    with mock.patch("app.push.webpush") as mocked:
        announce(pool, cfg, "v1 (a)")
        announce(pool, cfg, "v2 (b)")
    assert mocked.call_count == 0


# --- the service worker carries the release ----------------------------------------------------------------

def test_the_service_worker_is_served_with_the_running_release(client, monkeypatch):
    monkeypatch.setenv("APP_COMMIT", "0123456789")
    body = client.get("/sw.js")
    assert body.status_code == 200 and "javascript" in body.headers["Content-Type"]
    assert "no-cache" in body.headers["Cache-Control"] and body.headers["Service-Worker-Allowed"] == "/"
    assert re.search(r"const APP_VERSION = '[^']*\(0123456\)';", body.get_data(as_text=True))


# --- on the wire -----------------------------------------------------------------------------------------

def test_what_pywebpush_really_sends_carries_the_terms_and_decrypts(tmp_path):
    """Not mocked: a real VAPID key, a real subscription keypair and a local HTTP server standing in for
    the push service, so the headers asserted are the ones that actually leave the app."""
    import base64
    import http.server
    import os
    import sys
    import threading

    import http_ece
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from generate_vapid import generate

    def b64u(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    device_key = ec.generate_private_key(ec.SECP256R1())
    auth_secret = os.urandom(16)
    seen = {}

    class Service(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["headers"] = {k.lower(): v for k, v in self.headers.items()}
            seen["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(201)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Service)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        keys = generate()
        cfg = config("postgresql://unused", tmp_path, vapid_public_key=keys["VAPID_PUBLIC_KEY"],
                     vapid_private_key=keys["VAPID_PRIVATE_KEY"], vapid_subject="mailto:admin@localhost")
        subscription = {"endpoint": f"http://127.0.0.1:{server.server_port}/push/abc",
                        "p256dh": b64u(device_key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)),
                        "auth": b64u(auth_secret)}
        push.send_one(cfg, subscription, push.build_payload("release", "Titel", "Tekst", "/"))
    finally:
        server.shutdown()

    h = seen["headers"]
    assert h["ttl"] == "86400"                                   # not pywebpush's default of 0
    assert h["urgency"] == "low" and h["topic"] == "release"
    assert h["content-encoding"] == "aes128gcm"
    assert h["authorization"].startswith("vapid t=") and "k=" in h["authorization"]
    plain = http_ece.decrypt(seen["body"], private_key=device_key, auth_secret=auth_secret, version="aes128gcm")
    body = json.loads(plain)
    assert body["title"] == "Titel" and body["silent"] is True and not {"requireInteraction", "vibrate"} & set(body)
