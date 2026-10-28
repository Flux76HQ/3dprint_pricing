"""Optional password login, with optional two-step verification (TOTP).

Off by default. A password is something a person adds (Settings), chooses when invited, or the owner starts with when no passkey
can work on the address in use (an IP address on a home network). Two-step verification is a second, separate choice: with it,
logging in takes the password and then a code, and the session is issued only after both; without it the password alone signs in.
Turning either on needs only the session; changing the password, turning it or the second factor off and new backup codes need a
fresh passkey confirmation, or the password (plus a code when there is a second factor).
"""
import uuid

from flask import Blueprint, g, jsonify, make_response

from . import passwords
from .auth import _hash_code, _purpose, _verify_assertion, generate_code, issue_session, normalise_code, store_password
from .http import ApiError, RateLimiter, config, json_body, login_required, pool
from .i18n import L

bp = Blueprint("password_api", __name__, url_prefix="/api/auth/password")

BACKUP_CODE_COUNT = 8
MAX_FAILURES = 5                       # in a row, passwords and codes together, before a lock
ip_limiter = RateLimiter(limit=20, window_seconds=900)
FAILED = "pwapi.failed"           # one message for every refusal: unknown, wrong, locked-out-of-reason...


def _locked_message(minutes: int) -> str:
    return L("pwapi.locked", minutes=minutes)


def _register_failure(conn, user_id) -> None:
    """Atomic, so parallel guesses cannot out-run the counter. From the 5th failure: 15 minutes, then doubling."""
    conn.execute(
        "UPDATE password_credentials SET failed_count = failed_count + 1, updated_at = now(), "
        "locked_until = CASE WHEN failed_count + 1 >= %s THEN strftime('%%Y-%%m-%%d %%H:%%M:%%f', 'now', '+' || "
        "min(15 * (1 << min((failed_count + 1 - %s) / 5, 7)), 1440) || ' minutes') ELSE locked_until END WHERE user_id = %s",
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

def _credential_of(conn, name: str):
    """The password login of the person who types this name (the name they were given, any case). Without a name it is the only
    person there is; with several people a name is needed, and a missing or unknown one finds nothing, like a wrong password."""
    if name:
        return conn.execute("SELECT c.user_id, c.password_hash, c.totp_secret, c.locked_until FROM password_credentials c "
                            "JOIN users u ON u.id = c.user_id WHERE c.enabled AND lower(u.display_name) = lower(%s)", (name,)).fetchone()
    if conn.execute("SELECT count(*) > 1 AS m FROM users").fetchone()["m"]:
        return None
    return conn.execute("SELECT user_id, password_hash, totp_secret, locked_until FROM password_credentials WHERE enabled").fetchone()


@bp.post("/login")
def login():
    ip_limiter.check(_client_ip())
    body = json_body()
    password = str(body.get("password", ""))[:passwords.MAX_LENGTH + 1]
    name = str(body.get("name", "")).strip()[:100]
    refusal = None
    with pool().connection() as conn:
        row = _credential_of(conn, name)
        if row is None:
            passwords.burn_time(password)                   # same cost as a real check
            refusal = ApiError(401, FAILED)
        elif _lock_minutes(row):
            refusal = ApiError(429, _locked_message(_lock_minutes(row)))
        elif passwords.verify_password(row["password_hash"], password):
            if row["totp_secret"] is None:                   # no second factor: the password is the whole login
                conn.execute("UPDATE password_credentials SET failed_count = 0, locked_until = NULL, updated_at = now() "
                             "WHERE user_id = %s", (row["user_id"],))
                response = make_response(jsonify({"ok": True}))
                issue_session(response, row["user_id"], conn)
                return response
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
                           "WHERE user_id = %s AND enabled AND totp_secret IS NOT NULL", (uuid.UUID(user_id),)).fetchone()
        if row is None:                                      # also: the second factor was switched off since the password step
            raise refusal
        if _lock_minutes(row):
            refusal = ApiError(429, _locked_message(_lock_minutes(row)))
        else:
            ok = _check_second_factor(conn, row, code)
            if ok:
                conn.execute("UPDATE password_credentials SET failed_count = 0, locked_until = NULL, updated_at = now() "
                             "WHERE user_id = %s", (row["user_id"],))
                response = make_response(jsonify({"ok": True}))
                issue_session(response, row["user_id"], conn)
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

def _reauthenticate(body: dict) -> None:
    """Confirm with the password (and a second-factor code, when the person has one): for a device where the passkey cannot be
    used. It is the whole login again, with the same lock, the same failure counter, the same replay guard; nothing is cheaper
    than logging in."""
    ip_limiter.check(_client_ip())
    password = str(body.get("current_password", ""))[:passwords.MAX_LENGTH + 1]
    code = str(body.get("code", ""))
    refusal = ApiError(401, "pwapi.confirm_failed")
    with pool().connection() as conn:
        row = conn.execute("SELECT user_id, password_hash, totp_secret, last_totp_step, locked_until FROM password_credentials "
                           "WHERE user_id = %s AND enabled", (g.user_id,)).fetchone()
        if row is None:
            passwords.burn_time(password)
            refusal = ApiError(409, "pwapi.not_on")
        elif _lock_minutes(row):
            refusal = ApiError(429, _locked_message(_lock_minutes(row)))
        elif not passwords.verify_password(row["password_hash"], password):
            _register_failure(conn, row["user_id"])
        elif row["totp_secret"] is not None and not _check_second_factor(conn, row, code):   # only reached with the right password: no code is burnt otherwise
            _register_failure(conn, row["user_id"])
        else:
            conn.execute("UPDATE password_credentials SET failed_count = 0, locked_until = NULL, updated_at = now() "
                         "WHERE user_id = %s", (row["user_id"],))
            return
    raise refusal                                            # outside the block: the failure must commit


def _confirm(body: dict, action: str, target: str | None = None) -> None:
    """A fresh passkey confirmation for exactly this action (and, for one done to another person, exactly that person), or the
    password plus a code. Call it before opening the connection that does the work, so a refused attempt is still counted."""
    cred = body.get("credential")
    if isinstance(cred, dict) and isinstance(cred.get("response"), dict):
        with pool().connection() as conn:
            _verify_assertion(conn, cred, "confirm", purpose=_purpose(action, target), user_id=g.user_id)
    elif "current_password" in body:
        _reauthenticate(body)
    else:
        raise ApiError(400, "pwapi.need_confirmation")


@bp.get("/status")
@login_required
def status():
    with pool().connection() as conn:
        row = conn.execute("SELECT enabled, totp_secret IS NOT NULL AS totp FROM password_credentials WHERE user_id = %s", (g.user_id,)).fetchone()
        remaining = conn.execute("SELECT count(*) AS n FROM mfa_backup_codes WHERE user_id = %s AND used_at IS NULL",
                                 (g.user_id,)).fetchone()["n"]
        passkeys = conn.execute("SELECT count(*) AS n FROM webauthn_credentials WHERE user_id = %s", (g.user_id,)).fetchone()["n"]
    on = bool(row and row["enabled"])
    return jsonify({"enabled": on, "totp": on and bool(row["totp"]), "backup_codes_remaining": remaining, "passkeys": passkeys})


@bp.post("/setup")
@login_required
def setup():
    password = str(json_body().get("password", ""))
    with pool().connection() as conn:
        user = conn.execute("SELECT display_name FROM users WHERE id = %s", (g.user_id,)).fetchone()
        try:
            passwords.check_policy(password, user["display_name"])
        except ValueError as exc:
            raise ApiError(400, exc) from None
        if conn.execute("SELECT 1 FROM password_credentials WHERE user_id = %s", (g.user_id,)).fetchone():
            raise ApiError(409, "pwapi.already_on")
        store_password(conn, g.user_id, password)
    return jsonify({"ok": True})


@bp.post("/totp/start")
@login_required
def totp_start():
    """Begin adding an authenticator app. The secret waits as pending: nothing about signing in changes until a code is confirmed."""
    with pool().connection() as conn:
        row = conn.execute("SELECT totp_secret FROM password_credentials WHERE user_id = %s", (g.user_id,)).fetchone()
        if row is None:
            raise ApiError(409, "pwapi.not_on")
        if row["totp_secret"] is not None:
            raise ApiError(409, "pwapi.totp_already_on")
        user = conn.execute("SELECT display_name FROM users WHERE id = %s", (g.user_id,)).fetchone()
        secret = passwords.new_secret()
        conn.execute("UPDATE password_credentials SET pending_totp_secret = %s, updated_at = now() WHERE user_id = %s",
                     (passwords.seal(config().session_secret, secret), g.user_id))
        uri = passwords.otpauth_uri(secret, user["display_name"])
    return jsonify({"secret": passwords.b32(secret), "uri": uri, "qr": passwords.qr_data_uri(uri)})


@bp.post("/totp/confirm")
@login_required
def totp_confirm():
    code = str(json_body().get("code", ""))
    with pool().connection() as conn:
        row = conn.execute("SELECT pending_totp_secret, totp_secret FROM password_credentials WHERE user_id = %s",
                           (g.user_id,)).fetchone()
        if row is None or row["pending_totp_secret"] is None or row["totp_secret"] is not None:
            raise ApiError(409, "pwapi.no_setup")
        secret = passwords.unseal(config().session_secret, row["pending_totp_secret"])
        step = passwords.verify_totp(secret, code) if secret else None
        if step is None:
            raise ApiError(400, "pwapi.bad_code")
        conn.execute("UPDATE password_credentials SET totp_secret = pending_totp_secret, pending_totp_secret = NULL, last_totp_step = %s, "
                     "failed_count = 0, locked_until = NULL, updated_at = now() WHERE user_id = %s", (step, g.user_id))
        codes = _new_backup_codes(conn, g.user_id)
    return jsonify({"ok": True, "backup_codes": codes})


@bp.post("/totp/disable")
@login_required
def totp_disable():
    _confirm(json_body(), "password-totp-disable")
    with pool().connection() as conn:
        row = conn.execute("SELECT totp_secret FROM password_credentials WHERE user_id = %s", (g.user_id,)).fetchone()
        if row is None or row["totp_secret"] is None:
            raise ApiError(409, "pwapi.no_totp")
        conn.execute("UPDATE password_credentials SET totp_secret = NULL, pending_totp_secret = NULL, last_totp_step = 0, updated_at = now() "
                     "WHERE user_id = %s", (g.user_id,))
        conn.execute("DELETE FROM mfa_backup_codes WHERE user_id = %s", (g.user_id,))
    return jsonify({"ok": True})


@bp.post("/disable")
@login_required
def disable():
    with pool().connection() as conn:                         # before a confirmation is spent: without a passkey the password is their only way in
        if not conn.execute("SELECT 1 FROM webauthn_credentials WHERE user_id = %s", (g.user_id,)).fetchone():
            raise ApiError(409, "pwapi.last_method")
    _confirm(json_body(), "password-disable")
    with pool().connection() as conn:
        conn.execute("DELETE FROM password_credentials WHERE user_id = %s", (g.user_id,))
        conn.execute("DELETE FROM mfa_backup_codes WHERE user_id = %s", (g.user_id,))
    return jsonify({"ok": True})


@bp.post("/change")
@login_required
def change():
    body = json_body()
    with pool().connection() as conn:                         # a weak password is refused before a confirmation is spent
        user = conn.execute("SELECT display_name FROM users WHERE id = %s", (g.user_id,)).fetchone()
        try:
            passwords.check_policy(str(body.get("password", "")), user["display_name"])
        except ValueError as exc:
            raise ApiError(400, exc) from None
    _confirm(body, "password-change")
    with pool().connection() as conn:
        row = conn.execute("SELECT enabled FROM password_credentials WHERE user_id = %s", (g.user_id,)).fetchone()
        if not row or not row["enabled"]:
            raise ApiError(409, "pwapi.not_on")
        conn.execute("UPDATE password_credentials SET password_hash = %s, failed_count = 0, locked_until = NULL, "
                     "updated_at = now() WHERE user_id = %s", (passwords.hash_password(str(body["password"])), g.user_id))
    return jsonify({"ok": True})


@bp.post("/backup-codes/regenerate")
@login_required
def regenerate_backup_codes():
    _confirm(json_body(), "password-backup-codes")
    with pool().connection() as conn:
        row = conn.execute("SELECT totp_secret FROM password_credentials WHERE user_id = %s AND enabled", (g.user_id,)).fetchone()
        if not row:
            raise ApiError(409, "pwapi.not_on")
        if row["totp_secret"] is None:
            raise ApiError(409, "pwapi.no_totp")
        codes = _new_backup_codes(conn, g.user_id)
    return jsonify({"backup_codes": codes})
