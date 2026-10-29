"""SQLite access and the forward-only, checksum-guarded migration runner.

The whole database is one file under `DATA_PATH` (WAL mode). SQL is written once, for SQLite, with two
conveniences that keep the modules readable:

* `%s` placeholders and `now()` work as before (see `translate`), and a few Postgres spellings that SQLite
  lacks are rewritten on the way in (`ILIKE`, `lower(` for a Unicode-aware lower, `::jsonb`).
* Column types are declared as `UUID TEXT`, `TIMESTAMP TEXT`, `JSON TEXT`, `DATE TEXT`, `BOOLEAN`, `NUM1`..`NUM4`
  (a decimal with that many digits behind the point), and rows come back as dicts with the matching Python
  type (`uuid.UUID`, aware `datetime`, parsed JSON, `date`, `bool`, `Decimal`). Only bare columns are converted:
  an expression such as `SUM(price)` comes back as SQLite computed it.

Every transaction is `BEGIN IMMEDIATE`: it holds the single write lock from its first statement on, so a
read-then-write sequence cannot lose a race, and nothing in the app needs `SELECT ... FOR UPDATE` or an
advisory lock. Keep transactions short; never hold one across a call to another service.
"""
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations_sqlite"
BUSY_MS = int(os.environ.get("PRINTPRICING_DB_BUSY_MS", "15000"))


class SchemaDrift(RuntimeError):
    pass


class UniqueViolation(sqlite3.IntegrityError):
    pass


class ForeignKeyViolation(sqlite3.IntegrityError):
    pass


# ---- Types -----------------------------------------------------------------------------------------------------------

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def _utc_text(value: datetime) -> str:
    """Fixed width and always UTC, so that comparing and sorting the text is comparing and sorting the time."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.strftime(_TIME_FORMAT)[:-3]               # milliseconds


def _now() -> str:
    return _utc_text(datetime.now(timezone.utc))


def _parse_time(raw: bytes) -> datetime:
    text = raw.decode()
    try:
        return datetime.strptime(text, _TIME_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.fromisoformat(text).astimezone(timezone.utc) if "+" in text[10:] else \
            datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def _decimal(places: int):
    quantum = Decimal(1).scaleb(-places)

    def convert(raw: bytes) -> Decimal:
        return Decimal(raw.decode()).quantize(quantum)
    return convert


sqlite3.register_adapter(Decimal, str)
sqlite3.register_adapter(datetime, _utc_text)
sqlite3.register_adapter(date, lambda value: value.isoformat())
sqlite3.register_adapter(uuid.UUID, str)
sqlite3.register_converter("UUID", lambda raw: uuid.UUID(raw.decode()))
sqlite3.register_converter("TIMESTAMP", _parse_time)
sqlite3.register_converter("DATE", lambda raw: date.fromisoformat(raw.decode()))
sqlite3.register_converter("JSON", lambda raw: json.loads(raw))
sqlite3.register_converter("BOOLEAN", lambda raw: raw not in (b"0", b""))
for _places in (1, 2, 3, 4):
    sqlite3.register_converter(f"NUM{_places}", _decimal(_places))


def _dict_row(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {column[0]: value for column, value in zip(cursor.description, row)}


# ---- SQL -------------------------------------------------------------------------------------------------------------

_REWRITES = (
    (re.compile(r"::jsonb\b"), ""),                                              # JSON is stored as text
    (re.compile(r"\bILIKE\b", re.I), "LIKE"),
    (re.compile(r"\blower\("), "lower_u("),
)


@lru_cache(maxsize=1024)
def translate(sql: str) -> str:
    for pattern, replacement in _REWRITES:
        sql = pattern.sub(replacement, sql)
    return sql.replace("%%", "\0").replace("%s", "?").replace("\0", "%")


def id_list(values) -> str:
    """For `id IN (SELECT value FROM json_each(%s))`: SQLite has no array parameter, so a list travels as JSON text."""
    return json.dumps([str(value) for value in values])


def next_number(conn, name: str) -> int:
    """The next project or order number. Numbers are never reused, also not after a delete (they were a sequence in PostgreSQL)."""
    return conn.execute("INSERT INTO counters (name, last) VALUES (%s, 1) ON CONFLICT (name) DO UPDATE SET last = last + 1 RETURNING last",
                        (name,)).fetchone()["last"]


def _lower_u(value):
    return None if value is None else str(value).lower()


def _like(pattern, value, escape=None):
    """Unicode, case-insensitive LIKE (SQLite's own only folds ASCII): `%` any run, `_` any one character."""
    if pattern is None or value is None:
        return None
    out, chars = [], iter(str(pattern).casefold())
    for ch in chars:
        if escape and ch == str(escape).casefold():
            out.append(re.escape(next(chars, "")))
        elif ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return 1 if re.fullmatch("".join(out), str(value).casefold(), re.S) else 0


def _classify(exc: sqlite3.IntegrityError) -> sqlite3.IntegrityError:
    name = getattr(exc, "sqlite_errorname", "")
    if name in ("SQLITE_CONSTRAINT_UNIQUE", "SQLITE_CONSTRAINT_PRIMARYKEY"):
        return UniqueViolation(*exc.args)
    if name == "SQLITE_CONSTRAINT_FOREIGNKEY":
        return ForeignKeyViolation(*exc.args)
    return exc


# ---- Connections -----------------------------------------------------------------------------------------------------

class Connection:
    """One transaction's connection: `execute(sql, params)` returns a cursor whose rows are dicts."""

    def __init__(self, raw: sqlite3.Connection):
        self.raw = raw

    def execute(self, sql: str, params=()):
        try:
            return self.raw.execute(translate(sql), params)
        except sqlite3.IntegrityError as exc:
            raise _classify(exc) from None

    def begin(self) -> None:
        self.raw.execute("BEGIN IMMEDIATE")

    def commit(self) -> None:
        if self.raw.in_transaction:
            self.raw.execute("COMMIT")

    def rollback(self) -> None:
        """Undo this transaction and start the next one, so the block can carry on."""
        if self.raw.in_transaction:
            self.raw.execute("ROLLBACK")
        self.begin()


def _open(path: str) -> sqlite3.Connection:
    raw = sqlite3.connect(path, timeout=BUSY_MS / 1000, isolation_level=None, detect_types=sqlite3.PARSE_DECLTYPES)
    raw.row_factory = _dict_row
    raw.execute(f"PRAGMA busy_timeout = {BUSY_MS}")
    raw.execute("PRAGMA foreign_keys = ON")
    raw.execute("PRAGMA synchronous = FULL")
    raw.create_function("now", 0, _now)
    raw.create_function("lower_u", 1, _lower_u, deterministic=True)
    raw.create_function("like", 2, _like, deterministic=True)
    raw.create_function("like", 3, _like, deterministic=True)
    return raw


class Database:
    """What `app.extensions["pool"]` holds: hands out one connection per `with` block."""

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        probe = _open(path)
        mode = probe.execute("PRAGMA journal_mode = WAL").fetchone()["journal_mode"]
        probe.close()
        if mode != "wal":
            log.warning("SQLite could not switch %s to WAL (journal mode is %r). Keep DATA_PATH on a local disk, not on a network share.", path, mode)

    @contextmanager
    def connection(self):
        """A transaction: commits on success, rolls back on any exception."""
        conn = Connection(_open(self.path))
        try:
            conn.begin()
            yield conn
            conn.commit()
        except BaseException:
            if conn.raw.in_transaction:
                conn.raw.execute("ROLLBACK")
            raise
        finally:
            conn.raw.close()

    def close(self) -> None:
        """Nothing to release: connections live only inside `connection()`."""

    def compact(self) -> None:
        """Rewrite the file so deleted rows are really gone (a factory reset must not leave passkeys and invoices in free pages)."""
        raw = _open(self.path)
        try:
            raw.execute("VACUUM")
            raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            raw.close()


@contextmanager
def named_lock(pool: Database, name: str, *, hold_seconds: int = 300):
    """A lock between workers for work that must not keep a transaction open, such as a series of calls to another service. Waits its turn;
    a worker that dies while holding it loses it after `hold_seconds`, so waiting always ends."""
    key = f"lock:{name}"
    while True:
        now = datetime.now(timezone.utc)
        with pool.connection() as conn:
            conn.execute("DELETE FROM app_state WHERE key = %s AND value < %s", (key, _utc_text(now)))
            got = conn.execute("INSERT INTO app_state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING RETURNING key",
                               (key, _utc_text(now + timedelta(seconds=hold_seconds)))).fetchone()
        if got:
            break
        time.sleep(0.2)
    try:
        yield
    finally:
        with pool.connection() as conn:
            conn.execute("DELETE FROM app_state WHERE key = %s", (key,))


def make_pool(database_path: str) -> Database:
    return Database(database_path)


@contextmanager
def connection(pool: Database):
    with pool.connection() as conn:
        yield conn


# ---- Migrations ------------------------------------------------------------------------------------------------------

def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _statements(script: str):
    """Split a script into statements (a trigger body keeps its inner semicolons)."""
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                yield buffer
            buffer = ""
    if any(line.strip() and not line.lstrip().startswith("--") for line in buffer.splitlines()):
        yield buffer


def run_migrations(database_path: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply unapplied `NNNN_name.sql` files in order, each in its own transaction.

    Refuses to continue when a previously applied file has changed: editing an
    applied migration would make fresh installs and upgraded installs diverge
    silently, which is the one failure nobody notices until it is too late.
    """
    Database(database_path)                                  # creates the folder and switches to WAL
    conn = _open(database_path)
    applied_now = []
    try:
        conn.execute("BEGIN IMMEDIATE")                      # one runner at a time, even if two containers start together
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                     " filename TEXT PRIMARY KEY, checksum TEXT NOT NULL,"
                     " applied_at TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')))")
        conn.execute("COMMIT")
        for path in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            checksum = _checksum(path)
            conn.execute("BEGIN IMMEDIATE")
            try:
                known = {row["filename"]: row["checksum"] for row in conn.execute("SELECT filename, checksum FROM schema_migrations")}
                if path.name in known:
                    if known[path.name] != checksum:
                        raise SchemaDrift(
                            f"Migration {path.name} was changed after it was applied. "
                            "Never edit an applied migration; add a new NNNN_*.sql instead."
                        )
                else:
                    for statement in _statements(path.read_text(encoding="utf-8")):
                        conn.execute(statement)
                    conn.execute("INSERT INTO schema_migrations (filename, checksum) VALUES (?, ?)", (path.name, checksum))
                    applied_now.append(path.name)
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
    finally:
        conn.close()
    return applied_now

