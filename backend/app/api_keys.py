"""API keys: how another application (a finance app, a script) reads this one without a browser session.

A key is a long random text, shown once when it is made. Only its SHA-256 is kept, as for an invitation: it is 32 random bytes, so there
is nothing to guess and no salt would add to it, and the hash is what it is looked up by. A key is **not a person and not a session**: it
is accepted on the read-only API under `/api/v1` (`public_api.py`) and nowhere else, and a browser session is not accepted there. So a
key can never reach what is for administrators, change anything, or confirm anything.

Making and revoking keys is for administrators (`access.ADMIN_ONLY`) and needs a fresh confirmation, like the other things that open or
close a door. Keys are credentials: they are in no backup, and a factory reset removes them."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request

from .api import _serialise, text
from .http import ApiError, RateLimiter, json_body, pool
from .password_api import _confirm

bp = Blueprint("api_keys", __name__, url_prefix="/api/integrations/keys")
PREFIX = "ppk_"                              # recognisable: a secret scanner knows it, and a foreign bearer text is refused without a look in the database
SHOWN = len(PREFIX) + 6                      # what of a key is kept readable, to tell keys apart
MAX_KEYS = 20
USED_EVERY = timedelta(minutes=1)            # "last used" is written at most this often, not on every request

# Per web worker, in memory (http.RateLimiter), like the limiters of signing in: a key gets this many requests a minute in each worker,
# and an address that keeps offering keys that do not exist is slowed down.
per_key = RateLimiter(300, 60)
wrong_key = RateLimiter(20, 900)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def authenticate() -> dict:
    """The key this request carries (`Authorization: Bearer ppk_...`), or 401. Called by the routes that take a key; nothing else does."""
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    value = value.strip()
    if scheme.lower() != "bearer" or not value.startswith(PREFIX) or len(value) > 200:
        raise ApiError(401, "apikey.missing")
    now = datetime.now(timezone.utc)
    with pool().connection() as conn:
        row = conn.execute("SELECT id, name FROM api_keys WHERE key_hash = %s", (_hash(value),)).fetchone()
        if row is not None:
            conn.execute("UPDATE api_keys SET last_used_at = %s WHERE id = %s AND (last_used_at IS NULL OR last_used_at < %s)", (now, row["id"], now - USED_EVERY))
    if row is None:
        wrong_key.check(request.remote_addr or "?")
        raise ApiError(401, "apikey.invalid")
    per_key.check(str(row["id"]))
    return row


def _public(row) -> dict:
    return _serialise({k: row[k] for k in ("id", "name", "shown", "created_at", "last_used_at")})


@bp.get("")
def list_keys():
    with pool().connection() as conn:
        rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at, id").fetchall()
    return jsonify({"keys": [_public(r) for r in rows], "max": MAX_KEYS})


@bp.post("")
def create_key():
    body = json_body()
    name = text("f.name", max_len=60)(body.get("name"))
    _confirm(body, "api-key-create")                                 # before the work, so a refused attempt is counted
    key = PREFIX + secrets.token_urlsafe(32)
    with pool().connection() as conn:
        if conn.execute("SELECT count(*) AS n FROM api_keys").fetchone()["n"] >= MAX_KEYS:
            raise ApiError(409, "apikey.too_many", max=MAX_KEYS)
        row = conn.execute("INSERT INTO api_keys (name, shown, key_hash, created_by) VALUES (%s, %s, %s, %s) RETURNING *",
                           (name, key[:SHOWN], _hash(key), g.user_id)).fetchone()
    return jsonify({"key": key, "item": _public(row)}), 201           # the only time the key itself leaves the server


@bp.delete("/<uuid:key_id>")
def revoke_key(key_id):
    _confirm(json_body(), "api-key-revoke", str(key_id))
    with pool().connection() as conn:
        row = conn.execute("DELETE FROM api_keys WHERE id = %s RETURNING id", (key_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.not_found")
    return jsonify({"ok": True})
