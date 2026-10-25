"""System: put the app back to how it was before it was set up (factory settings).

Everything goes: the data, the settings, the passkeys, recovery codes, password login, notification subscriptions, the
OpenAI key, the uploaded files. Only the record of which migrations have run stays, or the next start would try to
create the tables again. Afterwards the app reports `onboarded: false` and the owner sets it up from the start, with the
setup code. This is the one thing in the app that cannot be undone, so it asks for the same proof as turning off the
password does: a fresh passkey confirmation, or the password plus a code (`password_api._confirm`).
"""
from pathlib import Path

from flask import Blueprint, current_app, jsonify, make_response

from . import auth
from .http import ApiError, config, json_body, login_required, pool
from .password_api import _confirm

bp = Blueprint("system", __name__, url_prefix="/api/system")

KEEP = ("schema_migrations",)
CONFIRM_WORD = "RESET"                  # typed by the owner; the screen (`RESET_WORD` in settings.js) shows the same word
LOGGED_NAMES = 50                       # the process log is the only trace the reset leaves: counts and file names, never contents
ONBOARDING_LOCK = 7603002            # the one onboarding takes (auth.onboarding_verify): a reset and a new owner never overlap


@bp.post("/reset")
@login_required
def reset():
    body = json_body()
    if body.get("confirm") != CONFIRM_WORD:                  # first, so a missing word spends neither a passkey confirmation nor an attempt
        raise ApiError(400, "system.word", word=CONFIRM_WORD)
    _confirm(body, "factory-reset")                          # before the work, so a refused attempt is still counted
    upload_dir = Path(config().upload_dir)
    with pool().connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (ONBOARDING_LOCK,))
        files = [r["stored_name"] for r in conn.execute("SELECT stored_name FROM print_files").fetchall()]
        for table in ("invoice_template", "invoice_logo"):
            files += [r["stored_name"] for r in conn.execute(f"SELECT stored_name FROM {table}").fetchall() if r["stored_name"]]
        tables = [r["tablename"] for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() AND tablename <> ALL(%s) ORDER BY tablename", (list(KEEP),)).fetchall()]
        conn.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")      # every table, so a table added later is covered too
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
