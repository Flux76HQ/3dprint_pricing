"""Automatic backups: a compressed copy of the database file in DATA_PATH/backups, made on a schedule, the oldest ones removed.

The copy is SQLite's online backup of the whole file (everything the database holds, users, passkeys, invoices and pictures included; not the STL/3MF files,
which are in DATA_PATH/uploads), gzipped, named `auto-YYYY-MM-DD-HHMMSS.sqlite3.gz` (UTC). Restoring is putting the file back (docs/handleiding.md). Only these
files are ever removed here: the copies `scripts/update.sh` makes and anything put there by hand are left alone.

The settings are the installation's own (`app_state`, not part of the business backup): on or off (on by default), how often (0.5, 1, 2, 7 or 14 days, 0.5 by
default) and how many to keep (0 to 60, 14 by default; 0 keeps none: nothing is made and the ones there are removed).
One thread per web worker looks every minute whether a backup is due; `db.named_lock` lets only one worker make it.
"""
import gzip
import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, jsonify

from . import db
from .api import boolean
from .http import ApiError, json_body, pool

log = logging.getLogger(__name__)
bp = Blueprint("autobackup", __name__, url_prefix="/api/backup/auto")       # under /api/backup: administrators only (access.py)

SETTINGS_KEY, LAST_KEY = "auto_backup", "last_auto_backup"
DEFAULTS = {"enabled": True, "keep": 14, "every_days": 0.5}
EVERY_DAYS = (0.5, 1, 2, 7, 14)
MAX_KEEP = 60
PREFIX, SUFFIX = "auto-", ".sqlite3.gz"
RETRY_AFTER = timedelta(hours=1)               # after a failed attempt: not every minute, not after days
FIRST_LOOK_SECONDS = 30                        # after the app has started, so the start itself is not slowed down


def folder() -> Path:
    """DATA_PATH/backups: next to the database's own folder (`/data/db` and `/data/backups` in the container)."""
    return Path(pool().path).parent.parent / "backups"


def load_settings(conn) -> dict:
    row = conn.execute("SELECT value FROM app_state WHERE key = %s", (SETTINGS_KEY,)).fetchone()
    try:
        stored = json.loads(row["value"]) if row else {}
    except ValueError:
        stored = {}
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


def load_last(conn) -> dict | None:
    row = conn.execute("SELECT value FROM app_state WHERE key = %s", (LAST_KEY,)).fetchone()
    try:
        return json.loads(row["value"]) if row else None
    except ValueError:
        return None


def validated(body: dict) -> dict:
    """The settings in `body` that are valid (any of the three); raises ApiError for a bad value."""
    out = {}
    if "enabled" in body:
        out["enabled"] = boolean("f.auto_backup")(body["enabled"])
    if "keep" in body:
        value = body["keep"]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_KEEP:
            raise ApiError(400, "err.auto_backup_keep", max=MAX_KEEP)
        out["keep"] = value
    if "every_days" in body:
        value = body["every_days"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) not in EVERY_DAYS:
            raise ApiError(400, "err.auto_backup_every")
        out["every_days"] = float(value)
    return out


def files(where: Path | None = None) -> list[Path]:
    """The automatic copies, newest first (the name carries the time, so the name order is the time order)."""
    where = where or folder()
    try:
        return sorted((p for p in where.iterdir() if p.is_file() and p.name.startswith(PREFIX) and p.name.endswith(SUFFIX)), key=lambda p: p.name, reverse=True)
    except OSError:
        return []


def prune(keep: int, where: Path | None = None) -> list[str]:
    """Remove all but the newest `keep` automatic copies; returns the names that went."""
    gone = []
    for path in files(where)[keep:]:
        try:
            path.unlink()
            gone.append(path.name)
        except OSError:
            log.warning("could not remove the old automatic backup %s", path.name)
    return gone


def is_due(settings: dict, last: dict | None, now: datetime) -> bool:
    if not settings["enabled"] or settings["keep"] == 0:
        return False
    if not last or not last.get("at"):
        return True                                                        # never made one: the first look makes it
    since = now - datetime.fromisoformat(last["at"])
    return since >= (timedelta(days=settings["every_days"]) if last.get("ok") else min(RETRY_AFTER, timedelta(days=settings["every_days"])))


def _make(target_dir: Path, now: datetime) -> dict:
    """One copy, compressed and moved into place under its final name only when it is whole."""
    began = time.monotonic()
    database = pool()
    size = os.path.getsize(database.path)
    target_dir.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(target_dir).free < 2 * size + (16 << 20):
        raise OSError("not enough free disk space")
    stamp = now.strftime("%Y-%m-%d-%H%M%S")
    plain, packed, final = target_dir / f".{stamp}.sqlite3", target_dir / f".{stamp}.gz", target_dir / f"{PREFIX}{stamp}{SUFFIX}"
    try:
        database.backup_to(str(plain))
        with open(plain, "rb") as source, gzip.open(packed, "wb", compresslevel=6) as out:
            shutil.copyfileobj(source, out)
        os.replace(packed, final)
    finally:
        plain.unlink(missing_ok=True)
        packed.unlink(missing_ok=True)
    return {"name": final.name, "size_bytes": final.stat().st_size, "seconds": round(time.monotonic() - began, 2)}


def run_once(now: datetime | None = None, *, force: bool = False) -> dict | None:
    """Make a backup when one is due (or now, with `force`), then remove the oldest. Returns what was recorded, or None when nothing was due."""
    now = now or datetime.now(timezone.utc)
    with pool().connection() as conn:
        settings = load_settings(conn)
    if settings["keep"] == 0:
        prune(0)                                                           # keeping none: what is there goes too, and nothing new is made
        return None
    if not force and not is_due(settings, _last(), now):
        return None
    with db.named_lock(pool(), "auto-backup", hold_seconds=900):
        with pool().connection() as conn:                                  # another worker may have made it while this one waited
            settings, last = load_settings(conn), load_last(conn)
        if not force and not is_due(settings, last, now):
            return None
        try:
            made = {"at": now.isoformat(), "ok": True, **_make(folder(), now)}
        except Exception as exc:                                          # a failed attempt is a fact to show, not a crash
            log.exception("automatic backup failed")
            made = {"at": now.isoformat(), "ok": False, "error": type(exc).__name__ if not isinstance(exc, OSError) else str(exc)[:120]}
        with pool().connection() as conn:
            conn.execute("INSERT INTO app_state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (LAST_KEY, json.dumps(made)))
        if made["ok"]:
            prune(settings["keep"])
        return made


def _last() -> dict | None:
    with pool().connection() as conn:
        return load_last(conn)


def start_worker(app, interval_seconds: int = 60) -> None:
    """A thread per web worker, like the push outbox: look every minute (the first time after a short wait), make a backup when one is due."""
    def loop():
        time.sleep(FIRST_LOOK_SECONDS)
        while True:
            try:
                with app.app_context():
                    run_once()
            except Exception:
                log.exception("automatic backup run failed; will look again")
            time.sleep(interval_seconds)

    threading.Thread(target=loop, name="auto-backup", daemon=True).start()


# --- the screen ------------------------------------------------------------------------------------------------

def _answer(conn) -> dict:
    present = files()
    return {"settings": load_settings(conn), "last": load_last(conn), "files": {"count": len(present), "newest": present[0].name if present else None},
            "options": {"every_days": list(EVERY_DAYS), "max_keep": MAX_KEEP}}


@bp.get("")
def show():
    with pool().connection() as conn:
        return jsonify(_answer(conn))


@bp.put("")
def save():
    changes = validated(json_body())
    with pool().connection() as conn:
        merged = {**load_settings(conn), **changes}
        conn.execute("INSERT INTO app_state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (SETTINGS_KEY, json.dumps(merged)))
    if merged["enabled"] or merged["keep"] == 0:
        prune(merged["keep"])                                              # a lower number (or none) takes effect now, not at the next look
    with pool().connection() as conn:
        return jsonify(_answer(conn))


@bp.post("/run")
def run_now():
    """A backup right now, whatever the schedule says (it still honours "keep 0")."""
    with pool().connection() as conn:
        if load_settings(conn)["keep"] == 0:
            raise ApiError(409, "err.auto_backup_keep_none")
    made = run_once(force=True)
    with pool().connection() as conn:
        return jsonify({**_answer(conn), "made": made})
