"""Database fixtures.

CI provides a PostgreSQL service and sets TEST_DATABASE_URL. Locally, when it is
unset, a throwaway cluster is started with the system's PostgreSQL binaries.
Database-backed tests are skipped when neither is available.
"""
import glob
import os
import shutil
import subprocess
import tempfile

import psycopg
import pytest

SECRET = "x" * 40
RP_ID = "localhost"
ORIGIN = "https://localhost:6080"
SETUP_CODE = "setup-123"


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
    url, stop = os.environ.get("TEST_DATABASE_URL"), None
    if not url:
        url, stop = _local_cluster()
    if not url:
        pytest.skip("No PostgreSQL available (set TEST_DATABASE_URL).")
    yield url
    if stop:
        stop()


@pytest.fixture
def fresh_db(database_url):
    """An empty schema per test: drop and recreate `public`."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    return database_url


@pytest.fixture
def app(fresh_db, tmp_path):
    from app import create_app
    from app.config import Config
    from app.db import run_migrations

    run_migrations(fresh_db)
    cfg = Config(database_url=fresh_db, session_secret=SECRET, setup_code=SETUP_CODE, rp_id=RP_ID,
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
