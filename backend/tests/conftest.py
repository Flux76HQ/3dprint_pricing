"""Database fixtures: a fresh SQLite file per test (and, for the one-off Postgres import, a PostgreSQL to read from).

`database_url` is only used by `test_pg_import.py`: CI provides a PostgreSQL service and sets TEST_DATABASE_URL; locally,
when it is unset and the system has PostgreSQL binaries, a throwaway cluster is started. Every other test needs no server.
"""
import glob
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager

import pytest

os.environ.setdefault("PUSH_WORKER", "off")      # no background threads in tests; the outbox is run explicitly
os.environ.setdefault("PRINTPRICING_DB_BUSY_MS", "3000")
SECRET = "x" * 40
RP_ID = "localhost"
ORIGIN = "https://localhost:6080"
SETUP_CODE = "setup-123"


@contextmanager
def connect(path, autocommit=False):
    """A plain connection to the test database for arranging and checking data: tuple rows, `%s` placeholders, commits on leaving the block."""
    from app import db
    conn = db.Connection(db._open(str(path)))
    conn.raw.row_factory = None
    if not autocommit:
        conn.begin()
    try:
        yield conn
        conn.commit()
    except BaseException:
        if conn.raw.in_transaction:
            conn.raw.execute("ROLLBACK")
        raise
    finally:
        conn.raw.close()


def _local_cluster():
    bins = sorted(glob.glob("/usr/lib/postgresql/*/bin"))
    if not bins or shutil.which("runuser") is None or os.geteuid() != 0:
        return None, None
    bindir = bins[-1]
    root = tempfile.mkdtemp(prefix="pp-pg-")
    shutil.chown(root, "postgres", "postgres")
    data, sock = os.path.join(root, "data"), os.path.join(root, "sock")
    os.makedirs(sock)
    shutil.chown(sock, "postgres", "postgres")

    def pg(*cmd):
        # The server inherits pipes; DEVNULL keeps subprocess.run from waiting on them forever.
        subprocess.run(["runuser", "-u", "postgres", "--", *cmd], check=True,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    pg(f"{bindir}/initdb", "-D", data, "-A", "trust")
    pg(f"{bindir}/pg_ctl", "-D", data, "-l", os.path.join(root, "log"),
       "-o", f"-k {sock} -c listen_addresses=''", "-w", "start")

    def stop():
        pg(f"{bindir}/pg_ctl", "-D", data, "-m", "immediate", "stop")
        shutil.rmtree(root, ignore_errors=True)

    return f"postgresql://postgres@/postgres?host={sock}", stop


@pytest.fixture(scope="session")
def database_url():
    """A PostgreSQL to import from (test_pg_import.py only)."""
    url, stop = os.environ.get("TEST_DATABASE_URL"), None
    if not url:
        url, stop = _local_cluster()
    if not url:
        pytest.skip("No PostgreSQL available (set TEST_DATABASE_URL).")
    yield url
    if stop:
        stop()


@pytest.fixture
def fresh_db(tmp_path):
    """The path of an empty SQLite file (not created yet)."""
    return str(tmp_path / "db" / "printpricing.sqlite3")


@pytest.fixture
def app(fresh_db, tmp_path):
    from app import create_app
    from app.config import Config
    from app.db import run_migrations

    run_migrations(fresh_db)
    cfg = Config(database_path=fresh_db, session_secret=SECRET, setup_code=SETUP_CODE, rp_id=RP_ID,
                 rp_name="Test", rp_origins=(ORIGIN,), session_hours=24, cookie_secure=True, upload_dir=str(tmp_path / 'uploads'), max_upload_mb=2,
                 static_dir=os.path.join(os.path.dirname(__file__), "static"))
    app = create_app(cfg)
    yield app
    app.extensions["pool"].close()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from app import auth
    auth.setup_limiter.hits.clear()
