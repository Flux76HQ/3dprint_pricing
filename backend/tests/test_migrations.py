import shutil
import sqlite3
from pathlib import Path

import pytest

from app.db import MIGRATIONS_DIR, SchemaDrift, run_migrations
from tests.conftest import connect


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
    (work / "9999_broken.sql").write_text("CREATE TABLE half (id int); INSERT INTO nowhere VALUES (1);")
    with pytest.raises(sqlite3.Error):
        run_migrations(fresh_db, work)
    with connect(fresh_db) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'half'").fetchone() is None
        applied = [r[0] for r in conn.execute("SELECT filename FROM schema_migrations")]
    assert applied == sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))   # everything real, nothing broken


def test_migration_numbers_are_unique_and_without_gaps():
    """Two pull requests that each add "the next" migration both pass on their own; merged, they would share a number, the runner would
    apply both in file-name order and nobody would notice. `python scripts/update_branch.py` renumbers the branch's migration."""
    numbers = [int(p.name[:4]) for p in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))]
    assert numbers == list(range(1, len(numbers) + 1)), f"migration numbers must be unique and consecutive, got {numbers}"


def test_a_migration_that_was_renumbered_is_not_run_a_second_time(tmp_path):
    """An installation that applied a migration under its old name keeps its record of it under the new one."""
    import sqlite3
    from app.db import RENAMED, run_migrations
    path = str(tmp_path / "db.sqlite3")
    run_migrations(path)
    conn = sqlite3.connect(path)
    for old, new in RENAMED.items():                                  # as it was before the files were renamed
        assert conn.execute("UPDATE schema_migrations SET filename = ? WHERE filename = ?", (old, new)).rowcount == 1
    conn.commit()
    assert run_migrations(path) == []                                 # nothing is applied again (it would fail: the columns are there)
    names = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}
    assert names == {p.name for p in MIGRATIONS_DIR.glob("[0-9]*.sql")} and not names & set(RENAMED)
    assert all((MIGRATIONS_DIR / new).is_file() and not (MIGRATIONS_DIR / old).exists() for old, new in RENAMED.items())
    conn.close()
