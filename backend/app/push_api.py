"""Push subscriptions: opt in/out per device, and a test button that sends on the real terms."""
from flask import Blueprint, jsonify, request

from . import push
from .i18n import L, render, request_language, translate
from .http import ApiError, config, json_body, login_required, pool
from flask import g

bp = Blueprint("push_api", __name__, url_prefix="/api/push")


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


def _require_configured():
    if not config().push_configured:
        raise ApiError(409, "pushapi.not_configured")


@bp.get("/config")
def get_config():
    cfg = config()
    with pool().connection() as conn:
        devices = conn.execute("SELECT count(*) AS n FROM push_subscriptions WHERE user_id = %s", (g.user_id,)).fetchone()["n"]
    return jsonify({"configured": cfg.push_configured, "public_key": cfg.vapid_public_key if cfg.push_configured else None,
                    "devices": devices, "ttl_hours": push.TTL_SECONDS // 3600})


def _reason_text(stored):
    reason = push.load_reason(stored)
    return render(reason, request_language()) if isinstance(reason, L) else reason


@bp.get("/devices")
def devices():
    """The owner's devices that receive notifications. `fingerprint` lets a device recognise itself
    (it hashes its own endpoint) without the endpoint, which is a secret, ever coming back."""
    with pool().connection() as conn:
        rows = conn.execute("SELECT id, endpoint, user_agent, created_at, last_ok_at, last_error, last_error_at "
                            "FROM push_subscriptions WHERE user_id = %s ORDER BY created_at", (g.user_id,)).fetchall()
    return jsonify({"devices": [{
        "id": str(r["id"]), "name": render(push.describe_agent(r["user_agent"]), request_language()), "fingerprint": push.fingerprint(r["endpoint"]),
        "created_at": r["created_at"].isoformat(),
        "last_ok_at": r["last_ok_at"].isoformat() if r["last_ok_at"] else None,
        "last_error": _reason_text(r["last_error"]), "last_error_at": r["last_error_at"].isoformat() if r["last_error_at"] else None,
    } for r in rows]})


@bp.delete("/devices/<uuid:device_id>")
def remove_device(device_id):
    with pool().connection() as conn:
        gone = conn.execute("DELETE FROM push_subscriptions WHERE id = %s AND user_id = %s RETURNING id",
                            (device_id, g.user_id)).fetchone()
    if gone is None:
        raise ApiError(404, "pushapi.device_not_found")
    return jsonify({"ok": True})


@bp.post("/check")
def check():
    """Can the server reach the push services? Fixed list of hosts; shows which step fails (DNS, connect, TLS)."""
    lang = request_language()
    results = []
    for item in push.check_connectivity():
        key = "push.c_ok" if item["ok"] else f"push.c_{item['stage']}"
        results.append({**item, "message": translate(lang, key, host=item["host"], error=item["error"])})
    vapid = push.check_vapid(config())
    key = "push.v_ok" if vapid["ok"] else f"push.v_{vapid['stage']}"
    return jsonify({"hosts": results, "vapid": {**vapid, "message": translate(lang, key, error=vapid["error"])}})


@bp.post("/subscribe")
def subscribe():
    _require_configured()
    body = json_body()
    endpoint = str(body.get("endpoint", ""))
    keys = body.get("keys") if isinstance(body.get("keys"), dict) else {}
    p256dh, auth = str(keys.get("p256dh", "")), str(keys.get("auth", ""))
    if not push.endpoint_ok(endpoint):
        raise ApiError(400, "pushapi.bad_endpoint")
    if not (0 < len(p256dh) <= 200 and 0 < len(auth) <= 100):
        raise ApiError(400, "pushapi.bad_keys")
    with pool().connection() as conn:
        conn.execute(
            "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (endpoint) DO UPDATE SET user_id = EXCLUDED.user_id, p256dh = EXCLUDED.p256dh, "
            "auth = EXCLUDED.auth, user_agent = EXCLUDED.user_agent",
            (g.user_id, endpoint, p256dh, auth, request.headers.get("User-Agent", "")[:300]))
    return jsonify({"ok": True})


@bp.post("/unsubscribe")
def unsubscribe():
    endpoint = str(json_body().get("endpoint", ""))
    with pool().connection() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = %s AND user_id = %s", (endpoint, g.user_id))
    return jsonify({"ok": True})


@bp.post("/test")
def test():
    """Same delivery function, TTL, urgency, topic scheme and silence as every real notification."""
    _require_configured()
    with pool().connection() as conn:
        devices = conn.execute("SELECT count(*) AS n FROM push_subscriptions WHERE user_id = %s", (g.user_id,)).fetchone()["n"]
    if not devices:
        raise ApiError(409, "pushapi.no_device")
    lang = request_language()
    result = push.notify(pool(), config(), g.user_id, "test", translate(lang, "push.test_title"), translate(lang, "push.test_body"))
    for item in result.get("results", []):
        item["device"] = render(item["device"], lang)
        if "reason" in item:
            item["reason"] = render(item["reason"], lang)
    return jsonify(result)
