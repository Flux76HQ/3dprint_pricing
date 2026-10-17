"""PostgreSQL access and the forward-only, checksum-guarded migration runner."""
import hashlib
import time
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class SchemaDrift(RuntimeError):
    pass


def make_pool(database_url: str) -> ConnectionPool:
    pool = ConnectionPool(
        database_url, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=False
    )
    pool.open(wait=True, timeout=30)
    return pool


@contextmanager
def connection(pool: ConnectionPool):
    """A transaction: commits on success, rolls back on any exception."""
    with pool.connection() as conn:
        yield conn


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_migrations(database_url: str, directory: Path = MIGRATIONS_DIR, wait_seconds: int = 30) -> list[str]:
    """Apply unapplied `NNNN_name.sql` files in order, each in its own transaction.

    Refuses to continue when a previously applied file has changed: editing an
    applied migration would make fresh installs and upgraded installs diverge
    silently, which is the one failure nobody notices until it is too late.
    """
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            conn = psycopg.connect(database_url, autocommit=True)
            break
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)

    applied_now = []
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " filename text PRIMARY KEY, checksum text NOT NULL,"
            " applied_at timestamptz NOT NULL DEFAULT now())"
        )
        # One runner at a time, even if two containers start together.
        conn.execute("SELECT pg_advisory_lock(7603001)")
        try:
            known = dict(conn.execute("SELECT filename, checksum FROM schema_migrations").fetchall())
            for path in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
                checksum = _checksum(path)
                if path.name in known:
                    if known[path.name] != checksum:
                        raise SchemaDrift(
                            f"Migration {path.name} was changed after it was applied. "
                            "Never edit an applied migration; add a new NNNN_*.sql instead."
                        )
                    continue
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute(
                        "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                        (path.name, checksum),
                    )
                applied_now.append(path.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(7603001)")
    return applied_now

