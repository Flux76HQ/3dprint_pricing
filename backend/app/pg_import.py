"""The one-off move of an installation from PostgreSQL (releases before the SQLite one) into the SQLite file.

Run by `migrate.py` at start-up when `LEGACY_DATABASE_URL` is set and there is no SQLite file yet. Everything is copied table by table, straight
from the old database, so the people, their passkeys and passwords, the invoices and the numbering come across exactly as they were (the in-app
backup leaves credentials out on purpose, so it could not do this). The new file is built under a temporary name, checked, and only then renamed
into place: a failure leaves no half-made database, the old PostgreSQL data is never touched, and the next start tries again.

Needs `psycopg`, which the next release drops together with this module.
"""
import hashlib
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

from . import db

log = logging.getLogger(__name__)

LEGACY_MIGRATIONS_DIR = Path(__file__).parent / "migrations_legacy"
# Not copied: what only lives for minutes (login challenges), what a restart abandons anyway (a restore or picture batch in progress), the
# record of which migrations ran (the new file has its own), and the numbering, which is rebuilt from the sequences.
SKIP = ("schema_migrations", "webauthn_challenges", "backup_jobs", "ai_image_jobs", "counters", "sqlite_sequence")
BATCH = 200
MAX_WAIT_SECONDS = 90


class ImportFailed(RuntimeError):
    """The import did not finish; nothing was changed in the SQLite file's place."""


def _connect(url: str, wait_seconds: int, *, autocommit: bool = True):
    import psycopg
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            return psycopg.connect(url, autocommit=autocommit)
        except psycopg.OperationalError as exc:
            if time.monotonic() > deadline:
                raise ImportFailed(f"The old PostgreSQL database cannot be reached ({exc}). Nothing was imported; start the database and restart the app.") from None
            time.sleep(1)


def has_data(url: str) -> bool:
    """Whether the old database is an installation worth importing (it has run the migrations), as opposed to a database that is brand new."""
    with _connect(url, MAX_WAIT_SECONDS) as conn:
        return conn.execute("SELECT to_regclass('public.schema_migrations') IS NOT NULL").fetchone()[0]


def bring_up_to_date(url: str) -> list[str]:
    """Apply the PostgreSQL migrations an old installation had not run yet, so the copy below meets the schema it expects (an installation that
    skipped several releases arrives here). The same forward-only, checksum-guarded runner the earlier releases had."""
    with _connect(url, MAX_WAIT_SECONDS) as conn:
        conn.execute("SELECT pg_advisory_lock(7603001)")
        applied = []
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (filename text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
            known = dict(conn.execute("SELECT filename, checksum FROM schema_migrations").fetchall())
            for path in sorted(LEGACY_MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
                checksum = hashlib.sha256(path.read_bytes()).hexdigest()
                if path.name in known:
                    if known[path.name] != checksum:
                        raise db.SchemaDrift(f"Migration {path.name} was changed after it was applied; the old database cannot be imported safely.")
                    continue
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)", (path.name, checksum))
                applied.append(path.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(7603001)")
    return applied


def _tables_in_order(lite: sqlite3.Connection) -> list[str]:
    """Every table to copy, the ones others point at first."""
    names = [r[0] for r in lite.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    names = [n for n in names if n not in SKIP]
    needs = {n: {r[2] for r in lite.execute(f"PRAGMA foreign_key_list('{n}')") if r[2] in names and r[2] != n} for n in names}
    ordered = []
    while names:
        ready = sorted(n for n in names if needs[n] <= set(ordered))
        if not ready:
            raise ImportFailed(f"Tables point at each other in a circle: {', '.join(names)}")
        ordered += ready
        names = [n for n in names if n not in ready]
    return ordered


def _column_plan(lite: sqlite3.Connection, table: str, pg_columns: set):
    """(name, kind, not_null) for the columns both databases have, in the new file's order."""
    plan = []
    for _cid, name, declared, notnull, _default, _pk in lite.execute(f"PRAGMA table_info('{table}')"):
        if name in pg_columns:
            plan.append((name, (declared.split() or [""])[0].upper(), bool(notnull)))
    return plan


def _value(value, kind: str, not_null: bool):
    if kind == "JSON":
        return json.dumps(value) if value is not None or not_null else None
    if isinstance(value, memoryview):
        return bytes(value)
    return value                                                  # Decimal, datetime, date, UUID, bool, int, float, str, bytes: adapters (db.py) take it


def _copy_table(pg, lite: sqlite3.Connection, table: str) -> int:
    pg_columns = {r[0] for r in pg.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s", (table,)).fetchall()}
    if not pg_columns:
        return 0                                                  # a table the old database never had
    plan = _column_plan(lite, table, pg_columns)
    names = [p[0] for p in plan]
    insert = f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})"
    count = 0
    with pg.cursor(name=f"import_{table}") as cursor:             # server side: invoice PDFs and pictures can be large
        cursor.itersize = BATCH
        cursor.execute(f"SELECT {', '.join(names)} FROM {table}")
        batch = []
        for row in cursor:
            batch.append(tuple(_value(v, kind, nn) for v, (_n, kind, nn) in zip(row, plan)))
            if len(batch) >= BATCH:
                lite.executemany(insert, batch)
                count += len(batch)
                batch = []
        if batch:
            lite.executemany(insert, batch)
            count += len(batch)
    return count


def _numbers(pg, lite: sqlite3.Connection) -> None:
    """The next project and order number carry on where the sequences were (and never below what the rows already use)."""
    for name, sequence, table in (("project", "project_number_seq", "projects"), ("order", "order_number_seq", "orders")):
        last_value, is_called = pg.execute(f"SELECT last_value, is_called FROM {sequence}").fetchone()
        issued = last_value if is_called else last_value - 1
        highest = lite.execute(f"SELECT COALESCE(MAX(number), 0) FROM {table}").fetchone()[0]
        lite.execute("INSERT INTO counters (name, last) VALUES (?, ?)", (name, max(issued, highest)))


def _check(pg, lite: sqlite3.Connection, tables: list[str], counts: dict) -> None:
    """The copy must be the original: same rows, same bytes in every blob, no broken reference, a sound file."""
    for table in tables:
        if not pg.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s", (table,)).fetchone():
            continue
        wanted = pg.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        got = lite.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if wanted != got or got != counts[table]:
            raise ImportFailed(f"{table}: {wanted} rows in PostgreSQL, {got} copied.")
        for _cid, name, declared, *_rest in lite.execute(f"PRAGMA table_info('{table}')").fetchall():
            if declared.upper() == "BLOB":
                if not pg.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s AND column_name = %s", (table, name)).fetchone():
                    continue
                if _digests(pg.execute(f"SELECT {name} FROM {table}")) != _digests(lite.execute(f"SELECT {name} FROM {table}")):
                    raise ImportFailed(f"{table}.{name}: a stored file differs after the copy.")
    broken = lite.execute("PRAGMA foreign_key_check").fetchall()
    if broken:
        raise ImportFailed(f"Rows that point at nothing after the copy: {broken[:5]}")
    verdict = lite.execute("PRAGMA integrity_check").fetchone()[0]
    if verdict != "ok":
        raise ImportFailed(f"The new database is not sound: {verdict}")


def _digests(rows) -> list:
    """SHA-256 of every value of a blob column, sorted: the order the two databases return rows in is not the same, the contents must be."""
    return sorted("" if value is None else hashlib.sha256(bytes(value)).hexdigest() for (value,) in rows)


def import_from_postgres(url: str, sqlite_path: str) -> dict:
    """Copy the old database into `sqlite_path` (which must not exist yet). Returns the number of rows per table."""
    target = Path(sqlite_path)
    building = target.with_name(target.name + ".importing")
    for leftover in (building, Path(str(building) + "-wal"), Path(str(building) + "-shm")):
        leftover.unlink(missing_ok=True)                           # a failed attempt before
    target.parent.mkdir(parents=True, exist_ok=True)
    log.warning("Importing the PostgreSQL database into %s (once).", target)
    began = time.monotonic()
    bring_up_to_date(url)
    db.run_migrations(str(building))
    counts = {}
    with _connect(url, MAX_WAIT_SECONDS, autocommit=False) as pg:
        pg.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")      # one consistent picture of the old database
        lite = db._open(str(building))
        lite.row_factory = None
        try:
            lite.execute("BEGIN IMMEDIATE")
            lite.execute("PRAGMA defer_foreign_keys = ON")         # one transaction; the references are checked at its end, and again below
            tables = _tables_in_order(lite)
            for table in tables:
                counts[table] = _copy_table(pg, lite, table)
                log.info("  %s: %d rows", table, counts[table])
            _numbers(pg, lite)
            _check(pg, lite, tables, counts)
            lite.execute("INSERT INTO app_state (key, value) VALUES ('imported_from_postgres', ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                         (json.dumps({"at": db._now(), "rows": counts}),))
            lite.execute("COMMIT")
        except BaseException:
            if lite.in_transaction:
                lite.execute("ROLLBACK")
            raise
        finally:
            lite.close()
    probe = db._open(str(building))                                # fold the log file into the database before it is renamed
    probe.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    probe.execute("PRAGMA journal_mode = DELETE")
    probe.close()
    os.replace(building, target)
    log.warning("Import finished in %.1f s: %s", time.monotonic() - began, ", ".join(f"{t} {n}" for t, n in counts.items() if n))
    return counts


def maybe_import(legacy_url: str, sqlite_path: str) -> dict | None:
    """The start-up step: import once, when there is an old database and no new one. None when there was nothing to do."""
    if not legacy_url or Path(sqlite_path).exists():
        return None
    if not has_data(legacy_url):
        return None                                                # a brand new installation
    try:
        return import_from_postgres(legacy_url, sqlite_path)
    except BaseException:
        log.exception("Importing the PostgreSQL database failed; it is untouched and the next start tries again.")
        raise
