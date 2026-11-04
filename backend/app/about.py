"""About: what is running, how healthy the database is and how the app is connected to it. For administrators only (`access.py`).

The answers carry facts and keys, never sentences (the screens have the words, section 6b of AGENTS.md). Nothing here is a secret: the address of
the old PostgreSQL is shown without its login, and the path of the database is only for the people who can reach the server anyway.
`GET /api/about` is cheap enough for every page view; the thorough check (`POST /api/about/check`) is a button.
"""
import json
import os
import platform
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from importlib.metadata import version as installed_version
from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint, jsonify

from . import db
from .config import build_channel
from .http import config, pool

bp = Blueprint("about", __name__, url_prefix="/api/about")

STARTED = time.time()                                     # of this worker: gunicorn starts each of them on its own
REPO = "https://github.com/Flux76HQ/3dprint_pricing"
NETWORK_FILESYSTEMS = ("nfs", "cifs", "smb", "fuse", "9p", "ceph", "afs")      # where SQLite's locks and shared memory cannot be trusted
SLOW_LOCK_SECONDS = 0.5                                   # waiting longer than this for the write lock says something else holds it for long
BIG_WAL_BYTES = 64 * 1024 ** 2                            # a log file this large means checkpoints are not happening
LOW_DISK_BYTES = 200 * 1024 ** 2
STATES = ("ok", "warn", "error")                          # worst last


def _worst(states) -> str:
    return max(states, key=STATES.index, default="ok")


def filesystem_of(path: str) -> str | None:
    """The type of the file system the path is on (`ext4`, `fuse.shfs`, `nfs4`...), from the mount table; None where there is none (not Linux)."""
    try:
        target, best = os.path.realpath(path), ("", None)
        with open("/proc/self/mounts", encoding="utf-8") as mounts:
            for line in mounts:
                parts = line.split()
                if len(parts) < 3:
                    continue
                point = parts[1].replace("\\040", " ")
                if (target == point or target.startswith(point.rstrip("/") + "/")) and len(point) >= len(best[0]):
                    best = (point, parts[2])
        return best[1]
    except OSError:
        return None


def _pragma(conn, name: str):
    return next(iter(conn.execute(f"PRAGMA {name}").fetchone().values()))


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _legacy(cfg, conn) -> dict:
    """The link to the PostgreSQL of the releases before SQLite: only there for the one-off import. The address is shown without its login."""
    marker = conn.execute("SELECT value FROM app_state WHERE key = 'imported_from_postgres'").fetchone()
    imported = None
    if marker:
        try:
            imported = json.loads(marker["value"]).get("at")
        except (ValueError, AttributeError):
            imported = ""
    address = None
    if cfg.legacy_database_url:
        parts = urlsplit(cfg.legacy_database_url)
        address = f"{parts.hostname or ''}{':' + str(parts.port) if parts.port else ''}{parts.path}"
    return {"configured": bool(cfg.legacy_database_url), "address": address, "imported_at": imported,
            "old_data_folder": Path("/data/postgres").is_dir(),
            "state": "imported" if marker else ("unused" if cfg.legacy_database_url else "none")}


def _migrations(conn) -> dict:
    applied = {row["filename"]: row for row in conn.execute("SELECT filename, checksum, applied_at FROM schema_migrations ORDER BY filename").fetchall()}
    files = {path.name: db._checksum(path) for path in sorted(db.MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))}
    return {
        "applied": [{"filename": name, "applied_at": row["applied_at"].isoformat()} for name, row in applied.items()],
        "pending": [name for name in files if name not in applied],
        "changed": [name for name in files if name in applied and applied[name]["checksum"] != files[name]],
        "unknown": [name for name in applied if name not in files],           # applied by a newer release than this one
    }


@bp.get("")
def about():
    from . import VERSION, _commit                          # imported here: this module is imported by the package
    cfg, database = config(), pool()
    path = Path(database.path)
    began = time.monotonic()
    try:
        with database.connection() as conn:                  # starts with BEGIN IMMEDIATE: the time it takes is the time the write lock took
            waited = time.monotonic() - began
            probe = time.monotonic()
            conn.execute("SELECT 1").fetchone()
            roundtrip = time.monotonic() - probe
            journal, foreign_keys = str(_pragma(conn, "journal_mode")).lower(), int(_pragma(conn, "foreign_keys"))
            facts = {"synchronous": int(_pragma(conn, "synchronous")), "busy_timeout_ms": int(_pragma(conn, "busy_timeout")),
                     "page_size": int(_pragma(conn, "page_size")), "page_count": int(_pragma(conn, "page_count")),
                     "free_pages": int(_pragma(conn, "freelist_count"))}
            tables = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
            rows = {name: conn.execute(f'SELECT count(*) AS n FROM "{name}"').fetchone()["n"] for name in tables}
            migrations, legacy = _migrations(conn), _legacy(cfg, conn)
    except Exception as exc:                                 # the page must still say that the database does not answer
        return jsonify({"app": _app(cfg, VERSION, _commit()), "database": {"engine": "SQLite", "path": str(path)}, "link": None,
                        "health": {"state": "error", "checks": [{"key": "reachable", "state": "error", "detail": type(exc).__name__}]}})

    wal, size = _size(Path(f"{path}-wal")), _size(path)
    filesystem = filesystem_of(str(path))
    free = shutil.disk_usage(path.parent).free
    network = bool(filesystem) and filesystem.startswith(NETWORK_FILESYSTEMS)
    migration_state = "error" if (migrations["pending"] or migrations["changed"]) else ("warn" if migrations["unknown"] else "ok")
    checks = [
        {"key": "reachable", "state": "ok", "value": round(roundtrip * 1000, 1)},
        {"key": "write_lock", "state": "ok" if waited < SLOW_LOCK_SECONDS else "warn", "value": round(waited * 1000, 1)},
        {"key": "journal", "state": "ok" if journal == "wal" else "warn", "value": journal},
        {"key": "foreign_keys", "state": "ok" if foreign_keys else "error"},
        {"key": "schema", "state": migration_state},
        {"key": "filesystem", "state": "warn" if network else "ok", "value": filesystem},
        {"key": "disk_space", "state": "ok" if free >= LOW_DISK_BYTES else "warn", "value": free},
        {"key": "wal_size", "state": "ok" if wal < BIG_WAL_BYTES else "warn", "value": wal},
    ]
    return jsonify({
        "app": _app(cfg, VERSION, _commit()),
        "health": {"state": _worst(c["state"] for c in checks), "checks": checks},
        "link": {"kind": "sqlite", "path": str(path), "driver": "sqlite3", "journal_mode": journal, "foreign_keys": bool(foreign_keys),
                 "synchronous": facts["synchronous"], "busy_timeout_ms": facts["busy_timeout_ms"], "filesystem": filesystem, "network_filesystem": network,
                 "worker_pid": os.getpid(), "workers": int(os.environ.get("WEB_CONCURRENCY") or 0) or None, "legacy": legacy},
        "database": {"engine": "SQLite", "version": sqlite3.sqlite_version, "size_bytes": size, "wal_bytes": wal, "free_bytes": free,
                     "page_size": facts["page_size"], "page_count": facts["page_count"], "free_pages": facts["free_pages"],
                     "tables": len(tables), "rows": rows, "migrations": migrations},
    })


def _app(cfg, version: str, commit: str) -> dict:
    return {"name": "3D Print Pricing", "version": version, "commit": commit, "channel": build_channel(), "repository": REPO,
            "python": platform.python_version(), "flask": installed_version("flask"), "started_at": datetime.fromtimestamp(STARTED, timezone.utc).isoformat(),
            "uptime_seconds": int(time.time() - STARTED),
            "features": {"push": cfg.push_configured, "ai_images": cfg.ai_images_enabled, "spoolman": bool(cfg.spoolman_url), "update_check": cfg.update_check}}


@bp.post("/check")
def check():
    """The thorough check, on request: `quick_check` and a look for rows that point at nothing."""
    return jsonify(pool().check())
