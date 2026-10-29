"""Users: who may sign in, and what an administrator can do about it.

Follows App-Guidance's shared/guidelines/user-management.md: an administrator makes a link, the guest opens it (`invites.py`) and
chooses their own password or passkey, so nobody ever learns anybody's credentials. Two roles, `admin` and `user`. The first person
is the owner: an administrator who cannot be invited, reset, demoted or removed, so the installation always has one. This app
adds one thing the guideline leaves out: an administrator can *promote* a regular user to administrator (and take it back), because
the person who runs the business is not always the person who set the app up.

Everything here is under `/api/users`, which `access.py` lists as administrator-only. Making someone an administrator, and
resetting an administrator, change who can act with every right, so those two ask for a fresh passkey confirmation (or the
password plus a code) bound to that person, like the other things that change access.
"""
import hashlib
import secrets
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify

from . import relying_party
from .http import ApiError, json_body, pool, require_admin
from .password_api import _confirm

bp = Blueprint("users", __name__, url_prefix="/api/users")
bp.before_request(require_admin)              # also on the blueprint itself: `access.py` is the control, this is a second lock

ROLES = ("admin", "user")
INVITE_TTL = timedelta(days=7)
MAX_USERS = 50                                 # people, counting the open invitations for new people as people
MAX_INVITES = 50
NAME_MAX = 60


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def clean_name(raw) -> str:
    """The name a person signs in with and is shown under: 1-60 characters, no control characters."""
    name = " ".join(str(raw or "").split())            # one space between words, none at the ends
    if not name or len(name) > NAME_MAX:
        raise ApiError(400, "users.name_length", max=NAME_MAX)
    if any(unicodedata.category(c).startswith("C") for c in name):
        raise ApiError(400, "users.name_chars")
    return name


def name_taken(conn, name: str, *, except_user=None, except_invite=None) -> bool:
    """Taken by a person, or reserved by an invitation for a new person (a reset invitation carries a name that is already theirs)."""
    if conn.execute("SELECT 1 FROM users WHERE lower(display_name) = lower(%s) AND id IS NOT %s",
                    (name, except_user)).fetchone():
        return True
    return conn.execute("SELECT 1 FROM invitations WHERE kind = 'new' AND lower(display_name) = lower(%s) AND id IS NOT %s",
                        (name, except_invite)).fetchone() is not None


def _target(conn, user_id):
    row = conn.execute("SELECT id, display_name, role, is_owner FROM users WHERE id = %s", (user_id,)).fetchone()
    if row is None:
        raise ApiError(404, "users.not_found")
    return row


def _not_the_owner(row, *, hidden=False) -> None:
    """The owner cannot be reset, demoted or removed. A reset link answers as if there were no such person (the guideline's rule)."""
    if row["is_owner"]:
        raise ApiError(404, "users.not_found") if hidden else ApiError(400, "users.owner_fixed")


def _not_yourself(row) -> None:
    if row["id"] == g.user_id:
        raise ApiError(400, "users.self")


def _iso(value):
    return value.isoformat() if value else None


@bp.get("")
def list_users():
    with pool().connection() as conn:
        users = conn.execute(
            "SELECT u.id, u.display_name, u.role, u.is_owner, u.created_at, "
            "(SELECT count(*) FROM webauthn_credentials c WHERE c.user_id = u.id) AS passkeys, "
            "EXISTS (SELECT 1 FROM password_credentials p WHERE p.user_id = u.id AND p.enabled) AS password "
            "FROM users u ORDER BY u.is_owner DESC, u.created_at, u.id").fetchall()
        invites = conn.execute(
            "SELECT i.id, i.kind, i.display_name, i.created_at, i.expires_at, c.display_name AS invited_by "
            "FROM invitations i LEFT JOIN users c ON c.id = i.created_by WHERE i.expires_at > now() ORDER BY i.created_at").fetchall()
    return jsonify({
        "users": [{"id": str(u["id"]), "name": u["display_name"], "role": u["role"], "is_owner": u["is_owner"],
                   "you": u["id"] == g.user_id, "created_at": _iso(u["created_at"]), "passkeys": u["passkeys"], "password": bool(u["password"])}
                  for u in users],
        "invitations": [{"id": str(i["id"]), "kind": i["kind"], "name": i["display_name"], "invited_by": i["invited_by"],
                         "created_at": _iso(i["created_at"]), "expires_at": _iso(i["expires_at"])} for i in invites],
        "limits": {"users": MAX_USERS, "invitations": MAX_INVITES},
    })


def _make_invitation(conn, *, kind, name, user_id=None):
    """Stores the invitation and returns what the administrator is shown, once: the token and the link."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    conn.execute("DELETE FROM invitations WHERE expires_at <= now()")           # expired ones go whenever a new one is made
    row = conn.execute(
        "INSERT INTO invitations (token_hash, kind, user_id, display_name, created_by, expires_at) VALUES (%s, %s, %s, %s, %s, %s) "
        "RETURNING id, expires_at", (token_hash(token), kind, user_id, name, g.user_id, now + INVITE_TTL)).fetchone()
    return {"id": str(row["id"]), "token": token, "url": f"{relying_party.public_origin()}/#invite={token}", "expires_at": row["expires_at"].isoformat()}


@bp.post("/invites")
def create_invite():
    body = json_body()
    name = clean_name(body["name"]) if str(body.get("name") or "").strip() else ""
    with pool().connection() as conn:
        conn.execute("DELETE FROM invitations WHERE expires_at <= now()")
        if conn.execute("SELECT (SELECT count(*) FROM users) + (SELECT count(*) FROM invitations WHERE kind = 'new') AS n").fetchone()["n"] >= MAX_USERS:
            raise ApiError(409, "users.cap_users", max=MAX_USERS)
        if conn.execute("SELECT count(*) AS n FROM invitations").fetchone()["n"] >= MAX_INVITES:
            raise ApiError(409, "users.cap_invites", max=MAX_INVITES)
        if name and name_taken(conn, name):
            raise ApiError(409, "users.name_taken")
        made = _make_invitation(conn, kind="new", name=name)
    return jsonify(made), 201


@bp.delete("/invites/<uuid:invite_id>")
def revoke_invite(invite_id):
    with pool().connection() as conn:
        gone = conn.execute("DELETE FROM invitations WHERE id = %s RETURNING id", (invite_id,)).fetchone()
    if gone is None:
        raise ApiError(404, "users.invite_not_found")
    return jsonify({"ok": True})


@bp.post("/<uuid:user_id>/reset")
def reset_user(user_id):
    """A link for someone who can no longer sign in. Nothing of what they have now is touched until they have finished with it."""
    body = json_body()
    with pool().connection() as conn:
        target = _target(conn, user_id)
    _not_the_owner(target, hidden=True)
    _not_yourself(target)
    if target["role"] == "admin":
        _confirm(body, "user-reset", str(user_id))              # a link for an administrator is the keys to everything
    with pool().connection() as conn:
        _target(conn, user_id)                          # two administrators resetting the same person take turns (the write lock)
        conn.execute("DELETE FROM invitations WHERE user_id = %s AND kind = 'reset'", (user_id,))
        made = _make_invitation(conn, kind="reset", name=target["display_name"], user_id=user_id)
    return jsonify(made), 201


@bp.put("/<uuid:user_id>/role")
def set_role(user_id):
    """Promote a regular user to administrator, or take that back. Whoever is promoted can do everything, so it needs the same
    fresh confirmation as the other ways of changing access; taking it away does not."""
    body = json_body()
    role = body.get("role")
    if role not in ROLES:
        raise ApiError(400, "users.bad_role")
    with pool().connection() as conn:
        target = _target(conn, user_id)
    _not_the_owner(target)
    _not_yourself(target)
    if target["role"] == role:
        return jsonify({"ok": True, "role": role})
    if role == "admin":
        _confirm(body, "user-promote", str(user_id))
    with pool().connection() as conn:
        # Re-checked in the update itself: not the owner, not yourself, and the same role as when we looked.
        done = conn.execute("UPDATE users SET role = %s WHERE id = %s AND NOT is_owner AND id <> %s RETURNING id",
                            (role, user_id, g.user_id)).fetchone()
    if done is None:
        raise ApiError(404, "users.not_found")
    return jsonify({"ok": True, "role": role})


@bp.delete("/<uuid:user_id>")
def delete_user(user_id):
    """The person and everything hanging off them (passkeys, recovery codes, password, notification subscriptions, open reset link)
    go in one transaction, by the foreign keys on `users`. Their session ends because every request looks the user up. What they
    made (calculations, orders, customers) belongs to the business and stays."""
    with pool().connection() as conn:
        target = _target(conn, user_id)
        _not_the_owner(target)
        _not_yourself(target)
        conn.execute("DELETE FROM users WHERE id = %s AND NOT is_owner", (user_id,))
    return jsonify({"ok": True})
