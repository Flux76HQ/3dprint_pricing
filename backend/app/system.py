"""System: put the app back to how it was before it was set up (factory settings).

Everything goes: the data, the settings, the passkeys, recovery codes, password login, notification subscriptions, the
OpenAI key, the uploaded files. Only the record of which migrations have run stays, or the next start would try to
create the tables again. Afterwards the app reports `onboarded: false` and the owner sets it up from the start, with the
setup code. This is the one thing in the app that cannot be undone, so it asks for the same proof as turning off the
password does: a fresh passkey confirmation, or the password plus a code (`password_api._confirm`).
"""
import json
from pathlib import Path

from flask import Blueprint, current_app, jsonify, make_response

from . import auth
from .db import ForeignKeyViolation
from .http import ApiError, config, json_body, login_required, pool
from .password_api import _confirm

bp = Blueprint("system", __name__, url_prefix="/api/system")

KEEP = ("schema_migrations",)           # SQLite's own sqlite_* tables are never listed
CONFIRM_WORD = "RESET"                  # typed by the owner; the screen (`RESET_WORD` in settings.js) shows the same word
LOGGED_NAMES = 50                       # the process log is the only trace the reset leaves: counts and file names, never contents


@bp.post("/reset")
@login_required
def reset():
    body = json_body()
    if body.get("confirm") != CONFIRM_WORD:                  # first, so a missing word spends neither a passkey confirmation nor an attempt
        raise ApiError(400, "system.word", word=CONFIRM_WORD)
    _confirm(body, "factory-reset")                          # before the work, so a refused attempt is still counted
    upload_dir = Path(config().upload_dir)
    with pool().connection() as conn:
        files = [r["stored_name"] for r in conn.execute("SELECT stored_name FROM print_files").fetchall()]
        for table in ("invoice_template", "invoice_logo"):
            files += [r["stored_name"] for r in conn.execute(f"SELECT stored_name FROM {table}").fetchall() if r["stored_name"]]
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%%' "
            "AND name NOT IN (SELECT value FROM json_each(%s)) ORDER BY name", (json.dumps(KEEP),)).fetchall()]
        pending = list(tables)                                  # every table, so a table added later is covered too
        while pending:                                          # a table another one still points at (RESTRICT) waits for its turn
            waiting = []
            for table in pending:
                try:
                    conn.execute(f"DELETE FROM {table}")
                except ForeignKeyViolation:
                    waiting.append(table)
            if len(waiting) == len(pending):
                raise RuntimeError(f"Factory reset could not empty {', '.join(waiting)}.")
            pending = waiting
        conn.execute("DELETE FROM sqlite_sequence")             # the counters of the AUTOINCREMENT tables start again, as the sequences did
    pool().compact()
    removed = []
    for name in files:
        path = upload_dir / name
        if path.is_file():
            path.unlink(missing_ok=True)
            removed.append(name)
    if upload_dir.is_dir():                                    # whatever else a failed upload or an older release left behind
        for path in upload_dir.iterdir():
            if path.is_file():
                path.unlink(missing_ok=True)
                removed.append(path.name)
    current_app.logger.warning("Factory reset: %d tables emptied, %d files removed%s", len(tables), len(removed),
                               f" ({', '.join(removed[:LOGGED_NAMES])}{', ...' if len(removed) > LOGGED_NAMES else ''})" if removed else "")
    response = make_response(jsonify({"ok": True}))
    response.delete_cookie(auth.COOKIE, path="/")             # the owner it names no longer exists
    return response
