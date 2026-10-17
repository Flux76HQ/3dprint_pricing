"""Optional password login with mandatory two-step verification (TOTP).

Off by default. Turning it on, changing it, or turning it off needs a fresh passkey confirmation, and it
only switches on once an authenticator code has been confirmed, so a password never exists without its
second factor. Logging in takes password then code; the session is issued only after both.
"""
import uuid

from flask import Blueprint, g, jsonify, make_response

from . import passwords
from .auth import _hash_code, _purpose, _verify_assertion, generate_code, issue_session, normalise_code
from .http import ApiError, RateLimiter, config, json_body, login_required, pool

bp = Blueprint("password_api", __name__, url_prefix="/api/auth/password")

BACKUP_CODE_COUNT = 8
MAX_FAILURES = 5                       # in a row, passwords and codes together, before a lock
ip_limiter = RateLimiter(limit=20, window_seconds=900)
FAILED = "Inloggen mislukt."           # one message for every refusal: unknown, wrong, locked-out-of-reason...


def _locked_message(minutes: int) -> str:
    return f"Te veel mislukte pogingen. Probeer het over {minutes} minuten opnieuw, of log in met een passkey."


def _register_failure(conn, user_id) -> None:
    """Atomic, so parallel guesses cannot out-run the counter. From the 5th failure: 15 minutes, then doubling."""
    conn.execute(
        "UPDATE password_credentials SET failed_count = failed_count + 1, updated_at = now(), "
        "locked_until = CASE WHEN failed_count + 1 >= %s THEN now() + interval '1 minute' * "
        "LEAST(15 * power(2, (failed_count + 1 - %s) / 5), 1440) ELSE locked_until END WHERE user_id = %s",
        (MAX_FAILURES, MAX_FAILURES, user_id))


def _lock_minutes(row) -> int:
    """Whole minutes left on a lock, or 0. Checked before anything else, so a lock gives no oracle."""
    until = row["locked_until"]
    if until is None:
        return 0
    from datetime import datetime, timezone
    left = (until - datetime.now(timezone.utc)).total_seconds()
    return max(0, int(left // 60) + 1) if left > 0 else 0


def _new_backup_codes(conn, user_id) -> list[str]:
    import os
    conn.execute("DELETE FROM mfa_backup_codes WHERE user_id = %s", (user_id,))
    codes = [generate_code() for _ in range(BACKUP_CODE_COUNT)]
    for code in codes:
        salt = os.urandom(16)
        conn.execute("INSERT INTO mfa_backup_codes (user_id, salt, code_hash) VALUES (%s, %s, %s)",
                     (user_id, salt, _hash_code(salt, code)))
    return codes


# --- login (no session yet) -----------------------------------------------------------------------------

@bp.post("/login")
def login():
    ip_limiter.check(_client_ip())
    password = str(json_body().get("password", ""))[:passwords.MAX_LENGTH + 1]
    refusal = None
    with pool().connection() as conn:
        row = conn.execute("SELECT user_id, password_hash, locked_until FROM password_credentials WHERE enabled").fetchone()
        if row is None:
            passwords.burn_time(password)                   # same cost as a real check
            refusal = ApiError(401, FAILED)
        elif _lock_minutes(row):
            refusal = ApiError(429, _locked_message(_lock_minutes(row)))
        elif passwords.verify_password(row["password_hash"], password):
            token = passwords.make_mfa_token(config().session_secret, row["user_id"])
            return jsonify({"mfa_required": True, "mfa_token": token})
        else:
            _register_failure(conn, row["user_id"])
            refusal = ApiError(401, FAILED)
    raise refusal                                            # outside the block: the failure must commit


@bp.post("/mfa")
def mfa():
    ip_limiter.check(_client_ip())
    body = json_body()
    user_id = passwords.read_mfa_token(config().session_secret, str(body.get("mfa_token", "")))
    code = str(body.get("code", ""))
    refusal = ApiError(401, FAILED)
    if not user_id:
        raise refusal
    with pool().connection() as conn:
        row = conn.execute("SELECT user_id, totp_secret, last_totp_step, locked_until FROM password_credentials "
                           "WHERE user_id = %s AND enabled", (uuid.UUID(user_id),)).fetchone()
        if row is None:
            raise refusal
        if _lock_minutes(row):
            refusal = ApiError(429, _locked_message(_lock_minutes(row)))
        else:
            ok = _check_second_factor(conn, row, code)
            if ok:
                conn.execute("UPDATE password_credentials SET failed_count = 0, locked_until = NULL, updated_at = now() "
                             "WHERE user_id = %s", (row["user_id"],))
                response = make_response(jsonify({"ok": True}))
                issue_session(response, row["user_id"])
                return response
            _register_failure(conn, row["user_id"])
    raise refusal


def _check_second_factor(conn, row, code: str) -> bool:
    """A 6-digit authenticator code (once only), or a backup code (consumed)."""
    compact = "".join(code.split())
    if len(compact) == passwords.TOTP_DIGITS and compact.isascii() and compact.isdigit():
        secret = passwords.unseal(config().session_secret, row["totp_secret"])
        if secret is None:                                   # SESSION_SECRET changed: fail closed
            return False
        step = passwords.verify_totp(secret, compact, last_step=row["last_totp_step"])
        if step is None:
            return False
        # Only the first request to use this step wins, even if two arrive together.
        won = conn.execute("UPDATE password_credentials SET last_totp_step = %s WHERE user_id = %s AND last_totp_step < %s "
                           "RETURNING user_id", (step, row["user_id"], step)).fetchone()
        return won is not None
    if not normalise_code(code):
        return False
    for backup in conn.execute("SELECT id, salt, code_hash FROM mfa_backup_codes WHERE user_id = %s AND used_at IS NULL",
                               (row["user_id"],)).fetchall():
        if _same(bytes(backup["code_hash"]), _hash_code(bytes(backup["salt"]), code)):
            used = conn.execute("UPDATE mfa_backup_codes SET used_at = now() WHERE id = %s AND used_at IS NULL RETURNING id",
                                (backup["id"],)).fetchone()
            return used is not None
    return False


def _same(a: bytes, b: bytes) -> bool:
    import hmac
    return hmac.compare_digest(a, b)


def _client_ip() -> str:
    from flask import request
    return request.remote_addr or "?"


# --- managing it (signed in, fresh passkey confirmation) ------------------------------------------------------

def _credential(body: dict) -> dict:
    cred = body.get("credential")
    if not isinstance(cred, dict) or not isinstance(cred.get("response"), dict):
        raise ApiError(400, "Bevestig dit met je passkey.")
    return cred


def _confirm(conn, body: dict, action: str) -> None:
    _verify_assertion(conn, _credential(body), "confirm", purpose=_purpose(action, None), user_id=g.user_id)


@bp.get("/status")
@login_required
def status():
    with pool().connection() as conn:
        row = conn.execute("SELECT enabled FROM password_credentials WHERE user_id = %s", (g.user_id,)).fetchone()
        remaining = conn.execute("SELECT count(*) AS n FROM mfa_backup_codes WHERE user_id = %s AND used_at IS NULL",
                                 (g.user_id,)).fetchone()["n"]
    return jsonify({"enabled": bool(row and row["enabled"]), "pending": bool(row and not row["enabled"]),
                    "backup_codes_remaining": remaining})


@bp.post("/setup/start")
@login_required
def setup_start():
    body = json_body()
    password = str(body.get("password", ""))
    with pool().connection() as conn:
        existing = conn.execute("SELECT enabled FROM password_credentials WHERE user_id = %s", (g.user_id,)).fetchone()
        if existing and existing["enabled"]:
            raise ApiError(409, "Wachtwoord-login staat al aan. Schakel het eerst uit of wijzig het wachtwoord.")
        user = conn.execute("SELECT display_name FROM users WHERE id = %s", (g.user_id,)).fetchone()
        try:
            passwords.check_policy(password, user["display_name"])
        except ValueError as exc:
            raise ApiError(400, str(exc)) from None
        secret = passwords.new_secret()
        conn.execute(
            "INSERT INTO password_credentials (user_id, password_hash, totp_secret, enabled) VALUES (%s, %s, %s, false) "
            "ON CONFLICT (user_id) DO UPDATE SET password_hash = EXCLUDED.password_hash, totp_secret = EXCLUDED.totp_secret, "
            "enabled = false, last_totp_step = 0, failed_count = 0, locked_until = NULL, updated_at = now()",
            (g.user_id, passwords.hash_password(password), passwords.seal(config().session_secret, secret)))
        uri = passwords.otpauth_uri(secret, user["display_name"])
    return jsonify({"secret": passwords.b32(secret), "uri": uri, "qr": passwords.qr_data_uri(uri)})


@bp.post("/setup/confirm")
@login_required
def setup_confirm():
    code = str(json_body().get("code", ""))
    with pool().connection() as conn:
        row = conn.execute("SELECT totp_secret, enabled FROM password_credentials WHERE user_id = %s FOR UPDATE",
                           (g.user_id,)).fetchone()
        if row is None or row["enabled"]:
            raise ApiError(409, "Er is geen installatie bezig. Begin opnieuw.")
        secret = passwords.unseal(config().session_secret, row["totp_secret"])
        step = passwords.verify_totp(secret, code) if secret else None
        if step is None:
            raise ApiError(400, "Die code klopt niet. Controleer de tijd op je toestel en probeer de volgende code.")
        conn.execute("UPDATE password_credentials SET enabled = true, last_totp_step = %s, failed_count = 0, "
                     "locked_until = NULL, updated_at = now() WHERE user_id = %s", (step, g.user_id))
        codes = _new_backup_codes(conn, g.user_id)
    return jsonify({"ok": True, "backup_codes": codes})


@bp.post("/setup/cancel")
@login_required
def setup_cancel():
    with pool().connection() as conn:
        conn.execute("DELETE FROM password_credentials WHERE user_id = %s AND NOT enabled", (g.user_id,))
    return jsonify({"ok": True})


@bp.post("/disable")
@login_required
def disable():
    with pool().connection() as conn:
        _confirm(conn, json_body(), "password-disable")
        conn.execute("DELETE FROM password_credentials WHERE user_id = %s", (g.user_id,))
        conn.execute("DELETE FROM mfa_backup_codes WHERE user_id = %s", (g.user_id,))
    return jsonify({"ok": True})


@bp.post("/change")
@login_required
def change():
    body = json_body()
    with pool().connection() as conn:
        _confirm(conn, body, "password-change")
        row = conn.execute("SELECT enabled FROM password_credentials WHERE user_id = %s", (g.user_id,)).fetchone()
        if not row or not row["enabled"]:
            raise ApiError(409, "Wachtwoord-login staat niet aan.")
        user = conn.execute("SELECT display_name FROM users WHERE id = %s", (g.user_id,)).fetchone()
        try:
            passwords.check_policy(str(body.get("password", "")), user["display_name"])
        except ValueError as exc:
            raise ApiError(400, str(exc)) from None
        conn.execute("UPDATE password_credentials SET password_hash = %s, failed_count = 0, locked_until = NULL, "
                     "updated_at = now() WHERE user_id = %s", (passwords.hash_password(str(body["password"])), g.user_id))
    return jsonify({"ok": True})


@bp.post("/backup-codes/regenerate")
@login_required
def regenerate_backup_codes():
    with pool().connection() as conn:
        _confirm(conn, json_body(), "password-backup-codes")
        row = conn.execute("SELECT enabled FROM password_credentials WHERE user_id = %s", (g.user_id,)).fetchone()
        if not row or not row["enabled"]:
            raise ApiError(409, "Wachtwoord-login staat niet aan.")
        codes = _new_backup_codes(conn, g.user_id)
    return jsonify({"backup_codes": codes})
