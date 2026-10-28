"""Invitations, the guest's half: opening a link and choosing how to sign in.

An administrator makes the link (`users.py`); here a person with no session uses it. The link is `https://host/#invite=<token>`: the
token is in the fragment, so no server, proxy or Referer ever sees it, and the page sends it back in the `X-Invite-Token` header,
which keeps it out of access logs. Only its SHA-256 is stored. Every unknown, expired or used token gets the same 404.

Two ways in, ending the same way: a passkey (`/passkey/options` and `/passkey/verify`, the onboarding ceremony with the same checks),
or a password (`/password`, one step; two-step verification can be added afterwards in Settings). Both end in
`_finish`: it claims the invitation (deleting it, so it is used once), then creates the person, or for a reset removes what they
could sign in with before and bumps their session epoch. Until that moment nothing has changed: someone who opens the link and walks
away has cost the person it was made for nothing.
"""
import uuid

from flask import Blueprint, jsonify, make_response, request

from . import passwords
from .db import UniqueViolation
from .auth import _create_recovery_codes, _credential_payload, _registration_options, _save_credential, _store_challenge, _verify_registration, issue_session, store_password
from .http import ApiError, RateLimiter, json_body, pool
from .users import clean_name, name_taken, token_hash

bp = Blueprint("invites", __name__, url_prefix="/api/invites")

limiter = RateLimiter(limit=30, window_seconds=900)
INVALID = "invite.invalid"      # one message for unknown, expired and used: the guest can ask for a new link, an attacker learns nothing
# What a reset takes away: everything the person could sign in with, and the devices that were told about new orders and low stock.
SIGN_IN_TABLES = ("webauthn_credentials", "recovery_codes", "password_credentials", "mfa_backup_codes", "push_subscriptions")


def _invitation(conn):
    token = request.headers.get("X-Invite-Token", "").strip()
    row = None
    if 16 <= len(token) <= 200:
        row = conn.execute(
            "SELECT i.*, c.display_name AS invited_by FROM invitations i LEFT JOIN users c ON c.id = i.created_by "
            "WHERE i.token_hash = %s AND i.expires_at > now()", (token_hash(token),)).fetchone()
    if row is None:
        raise ApiError(404, INVALID)
    return row


def _chosen_name(conn, inv, body) -> str:
    """A new person picks their name (the suggestion is only a suggestion); a reset keeps the one they have, whatever the request says."""
    if inv["kind"] == "reset":
        return inv["display_name"]
    name = clean_name(body.get("name"))
    if name_taken(conn, name, except_invite=inv["id"]):
        raise ApiError(409, "users.name_taken")
    return name


def _finish(conn, inv, name: str, user_id) -> uuid.UUID:
    """Claim the invitation, then make the person (new) or clear their old sign-in (reset). The caller stores the new credential."""
    if conn.execute("DELETE FROM invitations WHERE id = %s RETURNING id", (inv["id"],)).fetchone() is None:
        raise ApiError(404, INVALID)                                    # used by someone else a moment ago
    if inv["kind"] == "new":
        if name_taken(conn, name):                                      # its own reservation went with the delete above
            raise ApiError(409, "users.name_taken")
        try:
            conn.execute("INSERT INTO users (id, display_name) VALUES (%s, %s)", (user_id, name))
        except UniqueViolation:                          # two invitations for one name finishing together
            raise ApiError(409, "users.name_taken") from None
        return user_id
    user_id = inv["user_id"]
    for table in SIGN_IN_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE user_id = %s", (user_id,))
    conn.execute("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = %s", (user_id,))      # every old session, on every device, ends
    return user_id


@bp.get("/info")
def info():
    with pool().connection() as conn:
        inv = _invitation(conn)
    return jsonify({"kind": inv["kind"], "name": inv["display_name"], "invited_by": inv["invited_by"],
                    "expires_at": inv["expires_at"].isoformat()})


@bp.post("/passkey/options")
def passkey_options():
    limiter.check(request.remote_addr or "?")
    body = json_body()
    with pool().connection() as conn:
        inv = _invitation(conn)
        name = _chosen_name(conn, inv, body)                            # a taken name is refused before a passkey is made
        user_id = inv["user_id"] or uuid.uuid4()
        # Bound to this invitation, so a challenge made for one link cannot finish another.
        challenge = _store_challenge(conn, "invite", purpose=str(inv["id"]), data={"name": name, "user_id": str(user_id)})
    return jsonify(_registration_options(user_id, name, name, challenge, []))


@bp.post("/passkey/verify")
def passkey_verify():
    limiter.check(request.remote_addr or "?")
    body = json_body()
    with pool().connection() as conn:
        inv = _invitation(conn)                              # first: a bad link gets its one answer whatever else is wrong
        cred = _credential_payload(body)
        result, row = _verify_registration(conn, cred, "invite", purpose=str(inv["id"]))
        user_id = _finish(conn, inv, row["data"]["name"], uuid.UUID(row["data"]["user_id"]))
        _save_credential(conn, user_id, result, cred, str(body.get("label") or "Passkey"))
        codes = _create_recovery_codes(conn, user_id)
    response = make_response(jsonify({"ok": True, "recovery_codes": codes}))
    issue_session(response, user_id)                                    # after the commit: the session carries the new epoch
    return response


@bp.post("/password")
def choose_password():
    """A name and a password, in one step: the person is made (or, for a reset, their old sign-in cleared) and signed in."""
    limiter.check(request.remote_addr or "?")
    body = json_body()
    password = str(body.get("password", ""))
    with pool().connection() as conn:
        inv = _invitation(conn)
        name = _chosen_name(conn, inv, body)
        try:
            passwords.check_policy(password, name)                          # before the invitation is claimed: a weak password costs the guest nothing
        except ValueError as exc:
            raise ApiError(400, exc) from None
        user_id = _finish(conn, inv, name, inv["user_id"] or uuid.uuid4())
        store_password(conn, user_id, password)
        codes = _create_recovery_codes(conn, user_id)
    response = make_response(jsonify({"ok": True, "recovery_codes": codes}))
    issue_session(response, user_id)
    return response
