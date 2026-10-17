import shutil
from pathlib import Path

import psycopg
import pytest

from app.db import MIGRATIONS_DIR, SchemaDrift, run_migrations


def test_fresh_install_applies_everything_and_is_idempotent(fresh_db):
    first = run_migrations(fresh_db)
    assert first and first[0] == "0001_init.sql"
    assert run_migrations(fresh_db) == []


def test_refuses_to_start_when_an_applied_migration_changed(fresh_db, tmp_path):
    work = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, work, ignore=shutil.ignore_patterns("__pycache__"))
    run_migrations(fresh_db, work)
    first = sorted(work.glob("0001_*.sql"))[0]
    first.write_text(first.read_text() + "\n-- edited later\n")
    with pytest.raises(SchemaDrift, match="0001_init.sql"):
        run_migrations(fresh_db, work)


def test_a_failing_migration_leaves_nothing_half_applied(fresh_db, tmp_path):
    work = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, work, ignore=shutil.ignore_patterns("__pycache__"))
    run_migrations(fresh_db, work)
    (work / "0002_broken.sql").write_text("CREATE TABLE half (id int); SELECT 1/0;")
    with pytest.raises(psycopg.Error):
        run_migrations(fresh_db, work)
    with psycopg.connect(fresh_db) as conn:
        assert conn.execute("SELECT to_regclass('half')").fetchone()[0] is None
        applied = [r[0] for r in conn.execute("SELECT filename FROM schema_migrations")]
    assert applied == ["0001_init.sql"]
