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


def _renumber(work, name, number):
    path = next(work.glob(f"[0-9][0-9][0-9][0-9]_{name}.sql"))
    return path.rename(work / f"{number:04d}_{name}.sql")


def test_a_renumbered_migration_is_not_applied_again(fresh_db, tmp_path):
    """Three merges once gave three files the number 0006. Two of them got the next numbers afterwards; a database that had applied
    them as 0006 has to start with the new names, without running `ALTER TABLE ... ADD COLUMN` on a column that is already there."""
    work = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, work, ignore=shutil.ignore_patterns("__pycache__"))
    new = {name: next(work.glob(f"[0-9][0-9][0-9][0-9]_{name}.sql")).name for name in ("integrations", "project_models")}
    for name in new:
        _renumber(work, name, 6)                                # as that database met them
    run_migrations(fresh_db, work)
    with connect(fresh_db) as conn:
        assert {"0006_integrations.sql", "0006_project_models.sql"} <= {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
    for name, filename in new.items():
        (work / f"0006_{name}.sql").rename(work / filename)     # as the release has them now
    assert run_migrations(fresh_db, work) == []
    with connect(fresh_db) as conn:
        assert [r[0] for r in conn.execute("SELECT filename FROM schema_migrations ORDER BY filename")] == sorted(p.name for p in work.glob("*.sql"))
    assert run_migrations(fresh_db, work) == []


def test_a_renumbered_migration_that_also_changed_is_not_taken_for_applied(fresh_db, tmp_path):
    """The other name alone is not enough: with other content it is another migration, and it runs (here it fails, on the table that is there)."""
    work = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, work, ignore=shutil.ignore_patterns("__pycache__"))
    run_migrations(fresh_db, work)
    moved = _renumber(work, "integrations", 9990)
    moved.write_text(moved.read_text() + "\n-- edited later\n")
    with pytest.raises(sqlite3.Error, match="already exists"):
        run_migrations(fresh_db, work)


def test_a_copy_under_another_number_is_a_migration_of_its_own(fresh_db, tmp_path):
    """While the file under the old number is still there, the same content under a new number is a second migration, not a renumbered one."""
    work = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, work, ignore=shutil.ignore_patterns("__pycache__"))
    run_migrations(fresh_db, work)
    first = next(work.glob("[0-9][0-9][0-9][0-9]_integrations.sql"))
    shutil.copy(first, work / "9990_integrations.sql")
    with pytest.raises(sqlite3.Error, match="already exists"):
        run_migrations(fresh_db, work)
    with connect(fresh_db) as conn:
        assert first.name in {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}


def test_migration_numbers_are_unique_and_without_gaps():
    """Two pull requests that each add "the next" migration both pass on their own; merged, they would share a number, the runner would
    apply both in file-name order and nobody would notice. `python scripts/update_branch.py` renumbers the branch's migration."""
    numbers = [int(p.name[:4]) for p in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))]
    assert numbers == list(range(1, len(numbers) + 1)), f"migration numbers must be unique and consecutive, got {numbers}"
