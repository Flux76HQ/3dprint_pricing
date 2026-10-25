"""Passkey authentication: onboarding, login, recovery codes, step-up.

One owner signs in; the owner may hold several passkeys. Onboarding is closed as
soon as the first user exists, and is guarded by SETUP_CODE from the environment
so that whoever reaches the URL first cannot claim the app.
"""
import hashlib
import hmac
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from flask import Blueprint, g, jsonify, make_response, request

from . import webauthn as wa
from .http import ApiError, RateLimiter, config, json_body, login_required, pool

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

COOKIE = "pp_session"
CHALLENGE_TTL = 300
RECOVERY_CODE_COUNT = 8
# No 0/O/1/I: these are copied off paper, so the alphabet avoids look-alikes.
RECOVERY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_DASHES = "-‐‑‒–—−"  # hyphen-minus and typographic dashes are transcription noise

setup_limiter = RateLimiter(limit=10, window_seconds=900)


# --- sessions ---------------------------------------------------------------

def issue_session(response, user_id) -> None:
    cfg = config()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=cfg.session_hours)},
        cfg.session_secret,
        algorithm="HS256",
    )
    response.set_cookie(
        COOKIE, token, max_age=cfg.session_hours * 3600, httponly=True,
        secure=cfg.cookie_secure, samesite="Strict", path="/",
    )


def load_session() -> None:
    g.user_id = None
    token = request.cookies.get(COOKIE)
    if not token:
        return
    try:
        claims = jwt.decode(token, config().session_secret, algorithms=["HS256"])
        g.user_id = uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        g.user_id = None


# --- challenges ---------------------------------------------------------------

def _store_challenge(conn, kind, *, purpose=None, user_id=None, data=None) -> bytes:
    challenge = wa.new_challenge()
    conn.execute("DELETE FROM webauthn_challenges WHERE expires_at < now()")
    conn.execute(
        "INSERT INTO webauthn_challenges (challenge, kind, purpose, user_id, data, expires_at) "
        "VALUES (%s, %s, %s, %s, %s, now() + %s * interval '1 second')",
        (challenge, kind, purpose, user_id, json.dumps(data or {}), CHALLENGE_TTL),
    )
    return challenge


def _consume_challenge(conn, client_data_json: bytes, kind, *, purpose=None, user_id=None):
    """Single-use. Purpose and user are matched in the query, not checked afterwards."""
    try:
        challenge = wa.b64u_decode(json.loads(client_data_json)["challenge"])
    except Exception:
        raise ApiError(400, "auth.bad_request") from None
    row = conn.execute(
        "DELETE FROM webauthn_challenges WHERE challenge = %s AND kind = %s "
        "AND purpose IS NOT DISTINCT FROM %s AND user_id IS NOT DISTINCT FROM %s "
        "AND expires_at > now() RETURNING challenge, data",
        (challenge, kind, purpose, user_id),
    ).fetchone()
    if row is None:
        raise ApiError(400, "auth.challenge_expired")
    return row


def _credential_payload(body: dict) -> dict:
    cred = body.get("credential")
    if not isinstance(cred, dict) or not isinstance(cred.get("response"), dict):
        raise ApiError(400, "auth.bad_passkey_data")
    return cred


def _registration_options(user_id, name, display_name, challenge, exclude) -> dict:
    cfg = config()
    return {
        "challenge": wa.b64u_encode(challenge),
        "rp": {"id": cfg.rp_id, "name": cfg.rp_name},
        "user": {"id": wa.b64u_encode(user_id.bytes), "name": name, "displayName": display_name},
        "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
        "authenticatorSelection": {"residentKey": "required", "userVerification": "required"},
        "attestation": "none",
        "timeout": 120000,
        "excludeCredentials": [
            {"type": "public-key", "id": wa.b64u_encode(bytes(c))} for c in exclude
        ],
    }


def _verify_registration(conn, cred: dict, challenge_row_kind, *, purpose=None, user_id=None):
    try:
        client_data = wa.b64u_decode(cred["response"]["clientDataJSON"])
        attestation = wa.b64u_decode(cred["response"]["attestationObject"])
        raw_id = wa.b64u_decode(cred["rawId"])
    except (KeyError, wa.WebAuthnError, ValueError):
        raise ApiError(400, "auth.bad_passkey_data") from None
    row = _consume_challenge(conn, client_data, challenge_row_kind, purpose=purpose, user_id=user_id)
    cfg = config()
    try:
        result = wa.verify_registration(client_data, attestation, bytes(row["challenge"]),
                                        cfg.rp_id, cfg.rp_origins)
    except wa.WebAuthnError as exc:
        raise ApiError(400, "auth.passkey_refused", reason=exc) from None
    if result["credential_id"] != raw_id:
        raise ApiError(400, "auth.cred_id_mismatch")
    return result, row


def _verify_assertion(conn, cred: dict, kind, *, purpose=None, user_id=None):
    """Return (credential row, new counter). One message for every refusal."""
    fail = ApiError(401 if kind == "login" else 403, "auth.verification_failed")
    try:
        r = cred["response"]
        raw_id = wa.b64u_decode(cred["rawId"])
        client_data = wa.b64u_decode(r["clientDataJSON"])
        auth_data = wa.b64u_decode(r["authenticatorData"])
        signature = wa.b64u_decode(r["signature"])
    except (KeyError, wa.WebAuthnError, ValueError):
        raise fail from None
    stored = conn.execute(
        "SELECT id, user_id, public_key, sign_count FROM webauthn_credentials WHERE credential_id = %s",
        (raw_id,),
    ).fetchone()
    # A confirmation must come from one of the signed-in user's own credentials.
    if stored is None or (user_id is not None and stored["user_id"] != user_id):
        raise fail
    try:
        row = _consume_challenge(conn, client_data, kind, purpose=purpose, user_id=user_id)
    except ApiError:
        raise fail from None
    cfg = config()
    try:
        count = wa.verify_assertion(client_data, auth_data, signature, bytes(row["challenge"]),
                                    cfg.rp_id, cfg.rp_origins, bytes(stored["public_key"]),
                                    stored["sign_count"])
    except wa.WebAuthnError:
        raise fail from None
    conn.execute(
        "UPDATE webauthn_credentials SET sign_count = %s, last_used_at = now() WHERE id = %s",
        (count, stored["id"]),
    )
    return stored


def _save_credential(conn, user_id, result, cred, label) -> None:
    transports = cred["response"].get("transports")
    transports = [t for t in transports if isinstance(t, str)] if isinstance(transports, list) else []
    conn.execute(
        "INSERT INTO webauthn_credentials (user_id, credential_id, public_key, sign_count, transports, label) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (user_id, result["credential_id"], result["public_key"], result["sign_count"],
         json.dumps(transports), (label or "Passkey")[:60]),
    )


# --- recovery codes -----------------------------------------------------------

def normalise_code(raw: str) -> str:
    """Strip spaces and dashes, uppercase. Deliberately does NOT map look-alikes."""
    cleaned = re.sub(rf"[\s{re.escape(_DASHES)}]", "", str(raw))
    return cleaned.upper()


def generate_code() -> str:
    raw = "".join(RECOVERY_ALPHABET[b % len(RECOVERY_ALPHABET)] for b in os.urandom(12))
    return "-".join(raw[i:i + 4] for i in range(0, 12, 4))


def _hash_code(salt: bytes, code: str) -> bytes:
    return hashlib.sha256(salt + normalise_code(code).encode()).digest()


def _create_recovery_codes(conn, user_id) -> list[str]:
    conn.execute("DELETE FROM recovery_codes WHERE user_id = %s", (user_id,))
    codes = [generate_code() for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        salt = os.urandom(16)
        conn.execute(
            "INSERT INTO recovery_codes (user_id, salt, code_hash) VALUES (%s, %s, %s)",
            (user_id, salt, _hash_code(salt, code)),
        )
    return codes


# --- routes -------------------------------------------------------------------

@bp.get("/status")
def status():
    with pool().connection() as conn:
        onboarded = conn.execute("SELECT EXISTS (SELECT 1 FROM users) AS e").fetchone()["e"]
        user = None
        if g.user_id:
            row = conn.execute("SELECT id, display_name FROM users WHERE id = %s", (g.user_id,)).fetchone()
            user = {"id": str(row["id"]), "display_name": row["display_name"]} if row else None
        password_login = conn.execute("SELECT EXISTS (SELECT 1 FROM password_credentials WHERE enabled) AS e").fetchone()["e"]
    return jsonify({"onboarded": onboarded, "authenticated": user is not None, "user": user,
                    "rp_id": config().rp_id, "password_login": password_login,
                    "ai_images": config().ai_images_enabled})


@bp.post("/onboarding/options")
def onboarding_options():
    body = json_body()
    setup_limiter.check(request.remote_addr or "?")
    supplied = hashlib.sha256(str(body.get("setup_code", "")).encode()).digest()
    expected = hashlib.sha256(config().setup_code.encode()).digest()
    if not hmac.compare_digest(supplied, expected):
        raise ApiError(403, "auth.bad_setup_code")
    display_name = str(body.get("display_name", "")).strip()
    if not 1 <= len(display_name) <= 60:
        raise ApiError(400, "auth.name_required")
    with pool().connection() as conn:
        if conn.execute("SELECT EXISTS (SELECT 1 FROM users) AS e").fetchone()["e"]:
            raise ApiError(409, "auth.onboarded")
        user_id = uuid.uuid4()
        challenge = _store_challenge(conn, "onboarding",
                                     data={"user_id": str(user_id), "display_name": display_name})
    return jsonify(_registration_options(user_id, display_name, display_name, challenge, []))


@bp.post("/onboarding/verify")
def onboarding_verify():
    body = json_body()
    cred = _credential_payload(body)
    with pool().connection() as conn:
        result, row = _verify_registration(conn, cred, "onboarding")
        conn.execute("SELECT pg_advisory_xact_lock(7603002)")  # two onboardings at once: one wins
        if conn.execute("SELECT EXISTS (SELECT 1 FROM users) AS e").fetchone()["e"]:
            raise ApiError(409, "auth.onboarded")
        data = row["data"]
        user_id = uuid.UUID(data["user_id"])
        conn.execute("INSERT INTO users (id, display_name) VALUES (%s, %s)", (user_id, data["display_name"]))
        _save_credential(conn, user_id, result, cred, str(body.get("label") or "Eerste passkey"))
        codes = _create_recovery_codes(conn, user_id)
    response = make_response(jsonify({"ok": True, "recovery_codes": codes}))
    issue_session(response, user_id)
    return response


@bp.post("/login/options")
def login_options():
    with pool().connection() as conn:
        challenge = _store_challenge(conn, "login")
    return jsonify({
        "challenge": wa.b64u_encode(challenge), "rpId": config().rp_id,
        "userVerification": "required", "timeout": 120000, "allowCredentials": [],
    })


@bp.post("/login/verify")
def login_verify():
    cred = _credential_payload(json_body())
    with pool().connection() as conn:
        stored = _verify_assertion(conn, cred, "login")
    response = make_response(jsonify({"ok": True}))
    issue_session(response, stored["user_id"])
    return response


@bp.post("/logout")
def logout():
    response = make_response(jsonify({"ok": True}))
    response.delete_cookie(COOKIE, path="/")
    return response


@bp.post("/recovery/redeem")
def recovery_redeem():
    code = json_body().get("code", "")
    refusal = ApiError(401, "auth.bad_recovery")  # same text for every rejection
    if not normalise_code(code):
        raise refusal
    with pool().connection() as conn:
        rows = conn.execute(
            "SELECT id, user_id, salt, code_hash FROM recovery_codes WHERE used_at IS NULL"
        ).fetchall()
        match = None
        for row in rows:
            if hmac.compare_digest(bytes(row["code_hash"]), _hash_code(bytes(row["salt"]), code)):
                match = row
        if match is None:
            raise refusal
        # Consume first, so a code cannot be retried after any later failure.
        used = conn.execute(
            "UPDATE recovery_codes SET used_at = now() WHERE id = %s AND used_at IS NULL RETURNING user_id",
            (match["id"],),
        ).fetchone()
        if used is None:
            raise refusal
    response = make_response(jsonify({"ok": True}))
    issue_session(response, used["user_id"])
    return response


@bp.get("/credentials")
@login_required
def list_credentials():
    with pool().connection() as conn:
        rows = conn.execute(
            "SELECT id, label, created_at, last_used_at FROM webauthn_credentials "
            "WHERE user_id = %s ORDER BY created_at", (g.user_id,)).fetchall()
        remaining = conn.execute(
            "SELECT count(*) AS n FROM recovery_codes WHERE user_id = %s AND used_at IS NULL",
            (g.user_id,)).fetchone()["n"]
    return jsonify({
        "credentials": [{"id": str(r["id"]), "label": r["label"], "created_at": r["created_at"].isoformat(),
                         "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None}
                        for r in rows],
        "recovery_codes_remaining": remaining,
    })


@bp.post("/credentials/options")
@login_required
def add_credential_options():
    with pool().connection() as conn:
        user = conn.execute("SELECT display_name FROM users WHERE id = %s", (g.user_id,)).fetchone()
        existing = [r["credential_id"] for r in conn.execute(
            "SELECT credential_id FROM webauthn_credentials WHERE user_id = %s", (g.user_id,)).fetchall()]
        challenge = _store_challenge(conn, "register", user_id=g.user_id)
    return jsonify(_registration_options(g.user_id, user["display_name"], user["display_name"],
                                         challenge, existing))


@bp.post("/credentials/verify")
@login_required
def add_credential_verify():
    body = json_body()
    cred = _credential_payload(body)
    with pool().connection() as conn:
        result, _ = _verify_registration(conn, cred, "register", user_id=g.user_id)
        _save_credential(conn, g.user_id, result, cred, str(body.get("label") or "Passkey"))
    return jsonify({"ok": True})


def _purpose(action: str, target: str | None) -> str:
    """Composed server-side from the thing acted on; never taken from the request."""
    if action == "delete-credential" and target:
        return f"credential:{target}:delete"
    if action == "regenerate-recovery":
        return "recovery:regenerate"
    if action == "factory-reset":
        return "system:reset"
    if action in ("password-disable", "password-change", "password-backup-codes"):
        return f"password:{action.split('-', 1)[1]}"
    raise ApiError(400, "auth.unknown_action")


@bp.post("/stepup/options")
@login_required
def stepup_options():
    body = json_body()
    purpose = _purpose(str(body.get("action", "")), body.get("target"))
    with pool().connection() as conn:
        creds = [r["credential_id"] for r in conn.execute(
            "SELECT credential_id FROM webauthn_credentials WHERE user_id = %s", (g.user_id,)).fetchall()]
        challenge = _store_challenge(conn, "confirm", purpose=purpose, user_id=g.user_id)
    return jsonify({
        "challenge": wa.b64u_encode(challenge), "rpId": config().rp_id,
        "userVerification": "required", "timeout": 120000,
        "allowCredentials": [{"type": "public-key", "id": wa.b64u_encode(bytes(c))} for c in creds],
    })


@bp.delete("/credentials/<credential_id>")
@login_required
def delete_credential(credential_id):
    try:
        target = str(uuid.UUID(credential_id))
    except ValueError:
        raise ApiError(404, "auth.passkey_not_found") from None
    cred = _credential_payload(json_body())
    with pool().connection() as conn:
        _verify_assertion(conn, cred, "confirm", purpose=_purpose("delete-credential", target),
                          user_id=g.user_id)
        count = conn.execute("SELECT count(*) AS n FROM webauthn_credentials WHERE user_id = %s",
                             (g.user_id,)).fetchone()["n"]
        if count <= 1:
            raise ApiError(409, "auth.last_passkey")
        deleted = conn.execute("DELETE FROM webauthn_credentials WHERE id = %s AND user_id = %s",
                               (target, g.user_id)).rowcount
        if not deleted:
            raise ApiError(404, "auth.passkey_not_found")
    return jsonify({"ok": True})


@bp.post("/recovery/regenerate")
@login_required
def recovery_regenerate():
    cred = _credential_payload(json_body())
    with pool().connection() as conn:
        _verify_assertion(conn, cred, "confirm", purpose=_purpose("regenerate-recovery", None),
                          user_id=g.user_id)
        codes = _create_recovery_codes(conn, g.user_id)
    return jsonify({"recovery_codes": codes})
