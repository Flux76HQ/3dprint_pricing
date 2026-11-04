"""Automatic backups: by default every 12 hours the server makes the backup that *Back-up downloaden* makes with the print files, and keeps the
newest 14 (a week) in `Config.backup_dir` (DATA_PATH/backups/auto). A new one replaces the oldest. An administrator can switch them off, choose
how often (every 0.5, 1, 2, 7 or 14 days) and how many to keep (0-60; 0 keeps none: none is made and the ones there are removed): `settings()`.

The file is the ZIP of a download (`backup.document` + `backup.write_zip`): backup.json with everything the owner entered (invoices with
their numbers and kept PDFs, the template and the logo, customers, calculations, rolls, settings, ...) and every STL/3MF loose under
files/. So the same rules hold: no credentials, users or invitations, and a restore goes through the same check and the same job as an
uploaded backup (`backup.stage_copy`, then `POST /api/backup/jobs`). Settings -> Systeem lists them (`GET /api/backup/auto`); one is
downloaded as it is (`GET /api/backup/auto/<name>`). Administrators only (`access.py`, the /api/backup prefix).

Every web worker runs a small loop (`start_worker`) that looks every few minutes whether a backup is due. Making one takes a lock in
`app_state` (`db.try_named_lock`), so two workers never make two; the lock expires, so a worker that dies halfway does not stop the next.
When the last one was made is read from the file names (UTC), not from the database: a factory reset or a restore does not restart the
clock, and the backups themselves stay where they are. An installation without an owner (not set up yet, or just reset) makes none, so an
empty database never pushes a real backup out. A backup is written under a temporary name and renamed when complete; the oldest are only
removed after that. A failure is kept in `app_state`, shown on the screen, and tried again after an hour.
"""
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, jsonify, send_file

from . import backup, db
from .api import boolean
from .http import ApiError, config, json_body, login_required, pool
from .i18n import L, render, request_language

bp = Blueprint("auto_backup", __name__, url_prefix="/api/backup/auto")
log = logging.getLogger(__name__)

INTERVAL = timedelta(hours=12)
KEEP = 14                                    # 14 backups 12 hours apart: a week
RETRY = timedelta(hours=1)                   # after a failure: not every few minutes against a full disk
LOCK_SECONDS = 2 * 3600                      # a worker that died while making one lets go after this; a backup of many models takes minutes, not hours
FIRST_CHECK_SECONDS = 60                     # after the start, so the first one does not slow the start down
CHECK_SECONDS = 300
NAME = re.compile(r"printpricing-auto-(\d{4}-\d{2}-\d{2}-\d{6})Z\.zip")      # the moment it was made, UTC: sorting the names sorts the backups
STAMP = "%Y-%m-%d-%H%M%S"
TMP_PREFIX = ".tmp-"                         # being written; renamed when complete, removed when a crash left it behind
ERROR_KEY = "auto_backup:error"              # app_state: the last failure, until a backup succeeds
SETTINGS_KEY = "auto_backup:settings"        # app_state: what the administrator chose; a factory reset puts the defaults back (the backups stay)
DEFAULTS = {"enabled": True, "keep": KEEP, "every_days": INTERVAL.total_seconds() / 86400}
EVERY_DAYS = (0.5, 1, 2, 7, 14)
MAX_KEEP = 60


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session (and access.py an administrator)."""


def _folder() -> Path:
    return Path(config().backup_dir)


def _moment(name: str) -> datetime:
    return datetime.strptime(NAME.fullmatch(name).group(1), STAMP).replace(tzinfo=timezone.utc)


def _names() -> list[str]:
    """The automatic backups in the folder, newest first. Anything else in it is left alone."""
    try:
        names = [p.name for p in _folder().iterdir() if NAME.fullmatch(p.name) and p.is_file()]
    except FileNotFoundError:
        return []
    return sorted(names, reverse=True)


def settings(conn) -> dict:
    """What the administrator chose: on or off, how many to keep (0 keeps none: none is made and the ones there are go), how often."""
    row = conn.execute("SELECT value FROM app_state WHERE key = %s", (SETTINGS_KEY,)).fetchone()
    try:
        stored = json.loads(row["value"]) if row else {}
    except ValueError:
        stored = {}
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


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


def _interval(chosen: dict) -> timedelta:
    return timedelta(days=chosen["every_days"])


def _active(chosen: dict) -> bool:
    return chosen["enabled"] and chosen["keep"] > 0


def _last_error(conn) -> dict | None:
    row = conn.execute("SELECT value FROM app_state WHERE key = %s", (ERROR_KEY,)).fetchone()
    if not row:
        return None
    try:
        error = json.loads(row["value"])
        return {"at": datetime.fromisoformat(error["at"]), "reason": error.get("reason")}
    except (ValueError, KeyError, TypeError):
        return None


def _owner(conn):
    row = conn.execute("SELECT id FROM users WHERE is_owner").fetchone()
    return row["id"] if row else None


def next_at(now: datetime, newest: datetime | None, error: dict | None, interval: timedelta = INTERVAL) -> datetime:
    """When the next one is due: one interval after the newest (at once without one), and not within an hour of a failure."""
    due = newest + interval if newest else now
    if error:
        due = max(due, error["at"] + RETRY)
    return due


def _due(now: datetime) -> bool:
    with pool().connection() as conn:
        if _owner(conn) is None:
            return False                     # not set up: there is nothing of the owner's to keep yet
        if conn.execute("SELECT 1 FROM backup_jobs WHERE status = 'running'").fetchone():
            return False                     # a restore is replacing the data: back up what it leaves, at the next look
        error, chosen = _last_error(conn), settings(conn)
    if not _active(chosen):
        return False                         # switched off, or told to keep none
    names = _names()
    return now >= next_at(now, _moment(names[0]) if names else None, error, _interval(chosen))


def run_once(app, now: datetime | None = None) -> Path | None:
    """Makes a backup when one is due. Returns its path, or None: none was due, another worker is making it, or it failed (then the
    failure is kept for the screen)."""
    with app.app_context():
        now = now or datetime.now(timezone.utc)
        with pool().connection() as conn:
            keep = settings(conn)["keep"]
        if keep == 0:
            _prune(_folder(), 0)             # keeping none: the ones there are go too (also when the switch is off)
            return None
        if not _due(now):
            return None
        with db.try_named_lock(pool(), "auto-backup", hold_seconds=LOCK_SECONDS) as got:
            if not got or not _due(now):     # looked again with the lock held: another worker may just have made one
                return None
            return make(now)


def make(now: datetime) -> Path | None:
    """Writes one backup with everything, then removes the oldest beyond the number to keep."""
    folder = _folder()
    began = time.monotonic()
    tmp = None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        _clear_leftovers(folder)
        with pool().connection() as conn:
            owner, keep = _owner(conn), settings(conn)["keep"]
            if owner is None:
                return None
            doc, attachments = backup.document(conn, owner, include_files=True)      # the owner's own preferences go along, as in their own download
        target = folder / f"printpricing-auto-{now.astimezone(timezone.utc).strftime(STAMP)}Z.zip"
        tmp = folder / f"{TMP_PREFIX}{uuid.uuid4().hex}"
        with tmp.open("wb") as handle:
            backup.write_zip(doc, attachments, handle)
            handle.flush()
            os.fsync(handle.fileno())                                 # on the disk before it counts as a backup and an old one goes
        os.replace(tmp, target)
        tmp = None
    except Exception as exc:
        if tmp:
            tmp.unlink(missing_ok=True)
        _failed(now, exc)
        return None
    removed = _prune(folder, keep)
    with pool().connection() as conn:
        conn.execute("DELETE FROM app_state WHERE key = %s", (ERROR_KEY,))
    log.info("automatic backup %s: %.1f MB in %.1fs, %d print files; %d old one(s) removed", target.name, target.stat().st_size / 1048576,
             time.monotonic() - began, len(attachments), len(removed))
    return target


def _failed(now: datetime, exc: Exception) -> None:
    """Kept for the screen. A file system error says what went wrong in the operating system's words (a full disk, a folder the app
    may not write in); anything else is in the log, and the screen says so."""
    if isinstance(exc, OSError):
        log.warning("automatic backup failed: %s", exc)
        reason = str(exc)[:300]
    else:
        log.exception("automatic backup failed")
        reason = None
    try:
        with pool().connection() as conn:
            conn.execute("INSERT INTO app_state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                         (ERROR_KEY, json.dumps({"at": now.isoformat(), "reason": reason})))
    except Exception:
        log.exception("could not keep the failure of the automatic backup")


def _prune(folder: Path, keep: int) -> list[str]:
    """Only the newest `keep` stay. Called after a new one was written in full, so a failure never leaves fewer."""
    removed = []
    for name in _names()[keep:]:
        try:
            (folder / name).unlink()
            removed.append(name)
        except FileNotFoundError:
            pass
    return removed


def _clear_leftovers(folder: Path) -> None:
    """A backup that was being written when the container stopped. Older than the lock, so it is not one that is being written now."""
    for path in folder.glob(f"{TMP_PREFIX}*"):
        try:
            if time.time() - path.stat().st_mtime > LOCK_SECONDS:
                path.unlink(missing_ok=True)
        except OSError:
            pass


def start_worker(app, first_seconds: float = FIRST_CHECK_SECONDS, every_seconds: float = CHECK_SECONDS,
                 stop: threading.Event | None = None) -> threading.Thread:
    """A small loop per web worker; the lock in `run_once` keeps them from making two. It runs as long as the process does (`stop` ends
    it sooner, for a test)."""
    stop = stop or threading.Event()

    def loop():
        if stop.wait(first_seconds):
            return
        while True:
            try:
                run_once(app)
            except Exception:
                log.exception("automatic backup check failed; will look again")
            if stop.wait(every_seconds):
                return

    thread = threading.Thread(target=loop, name="auto-backup", daemon=True)
    thread.start()
    return thread


def summary() -> dict:
    """How many there are and the newest, for Settings -> Over (`about.py`): names, times and sizes, nothing of what is in them."""
    names = _names()
    latest = None
    if names:
        try:
            latest = {"name": names[0], "size_bytes": (_folder() / names[0]).stat().st_size, "at": _moment(names[0]).isoformat()}
        except FileNotFoundError:
            pass                                                      # removed while we looked
    return {"count": len(names), "latest": latest}


# --- the screen ------------------------------------------------------------------------------------------------------

def _path(name: str) -> Path:
    """A name from the address, checked by pattern before it is joined to a path."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ApiError(404, "backup.auto_not_found")
    path = _folder() / name
    if not path.is_file():
        raise ApiError(404, "backup.auto_not_found")
    return path


@bp.get("")
def listing():
    now = datetime.now(timezone.utc)
    names = _names()
    with pool().connection() as conn:
        error, chosen = _last_error(conn), settings(conn)
    backups = []
    for name in names:
        try:
            size = (_folder() / name).stat().st_size
        except FileNotFoundError:
            continue                                                  # removed while we looked
        backups.append({"name": name, "created_at": _moment(name).isoformat(), "size": size})
    failure = None
    if error:
        lang = request_language()
        reason = error["reason"] or render(L("backup.auto_err_unexpected"), lang)
        failure = {"at": error["at"].isoformat(), "message": render(L("backup.auto_failed", reason=reason), lang)}
    due = next_at(now, _moment(names[0]) if names else None, error, _interval(chosen)).isoformat() if _active(chosen) else None
    return jsonify({"backups": backups, "settings": chosen, "options": {"every_days": list(EVERY_DAYS), "max_keep": MAX_KEEP},
                    "interval_hours": int(_interval(chosen).total_seconds() // 3600), "keep": chosen["keep"], "next_at": due, "error": failure})


@bp.put("")
def save():
    """Switch it on or off, how many to keep (0-60), how often. Fewer to keep (or none) takes effect at once, not at the next one."""
    changes = validated(json_body())
    with pool().connection() as conn:
        merged = {**settings(conn), **changes}
        conn.execute("INSERT INTO app_state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (SETTINGS_KEY, json.dumps(merged)))
    _prune(_folder(), merged["keep"])
    return listing()


@bp.get("/<name>")
def download(name):
    """The ZIP as it is on the server, with its size, so the screen can show how far the download is."""
    return send_file(_path(name), mimetype="application/zip", as_attachment=True, download_name=name, conditional=False)


@bp.post("/<name>/stage")
def stage(name):
    """Stage a kept backup for a restore, as if it had been uploaded: checked in full, and answered with what would come back and the
    token for `POST /api/backup/jobs`. Nothing changes yet, and the kept backup itself stays."""
    return jsonify(backup.stage_copy(_path(name)))
