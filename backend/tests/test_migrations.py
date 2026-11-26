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


# --- the table of orders is built again for a new status ---------------------------------------------------------------------------

def _raw(path):
    """The app's own kind of connection (foreign keys on, its SQL functions), with plain tuples for rows."""
    from app.db import _open
    conn = _open(str(path))
    conn.row_factory = None
    return conn


def _before_in_progress(tmp_path):
    """A folder with every migration before the one that adds the status "in_behandeling" (0022), which rebuilds `orders`, and what came after it."""
    work = tmp_path / "migrations-before"
    shutil.copytree(MIGRATIONS_DIR, work, ignore=shutil.ignore_patterns("__pycache__"))
    for later in work.glob("00[2-9][2-9]_*.sql"):
        later.unlink()
    return work


def _orders_with_everything(path):
    """Two orders as an installation has them, one of them invoiced, with lines and the invoice PDF."""
    raw = _raw(path)
    raw.execute("INSERT INTO customers (id, number, name) VALUES ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', 'K1', 'Anna')")
    for oid, number, status, invoice in (('11111111-1111-4111-8111-111111111111', 1, "verwerkt", "2026-0001"), ('22222222-2222-4222-8222-222222222222', 2, "nieuw", None)):
        raw.execute("INSERT INTO orders (id, number, status, customer_name, invoice_number, invoice_date, subject, customer_id, price_rounding) "
                    "VALUES (?, ?, ?, 'Anna', ?, ?, ?, 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', 'x.95')", (oid, number, status, invoice, "2026-11-01" if invoice else None, f"Bestelling {number}"))
        for position in range(2):
            raw.execute("INSERT INTO order_lines (order_id, position, description, quantity, unit_price, vat_pct, cost_price, margin_pct, optional, packaging) "
                        "VALUES (?, ?, ?, 3, 12.10, 21, 5, 40, 0, ?)", (oid, position, f"Regel {position}", position))
    raw.execute("INSERT INTO invoice_pdfs (order_id, invoice_number, content, size_bytes) VALUES ('11111111-1111-4111-8111-111111111111', '2026-0001', ?, 4)", (b"%PDF",))
    raw.commit()
    raw.close()


def test_the_orders_table_is_rebuilt_without_losing_an_order_a_line_or_an_invoice(fresh_db, tmp_path):
    run_migrations(fresh_db, _before_in_progress(tmp_path))
    _orders_with_everything(fresh_db)
    raw = _raw(fresh_db)
    # what a line was before 0023 added its two columns
    columns = {"order_lines": "id, order_id, position, project_id, project_number, description, quantity, unit_price, vat_pct, cost_price, margin_pct, optional, packaging"}
    select = lambda table: f"SELECT {columns.get(table, '*')} FROM {table} ORDER BY 1, 2"
    want = {table: raw.execute(select(table)).fetchall() for table in ("orders", "order_lines", "invoice_pdfs", "customers")}
    raw.close()

    assert run_migrations(fresh_db) == ["0022_order_status_in_progress.sql", "0023_order_line_model_price.sql"]

    raw = _raw(fresh_db)
    for table, rows in want.items():
        assert raw.execute(select(table)).fetchall() == rows, table                                    # every column of every row, as it was
    assert len(want["order_lines"]) == 4 and len(want["invoice_pdfs"]) == 1                            # the children were not cascaded away
    assert raw.execute("SELECT count(*) FROM order_lines WHERE base_price IS NULL AND price_rounding IS NULL").fetchone() == (4,)      # no line has a model's price: all are priced as before
    assert raw.execute("PRAGMA foreign_key_check").fetchall() == []
    assert raw.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert {r[1] for r in raw.execute("PRAGMA index_list(orders)")} >= {"orders_order_date_idx", "orders_customer_idx"}
    assert raw.execute("SELECT name FROM sqlite_master WHERE name = 'orders_new'").fetchone() is None
    raw.close()


def test_the_rebuilt_orders_table_takes_the_new_status_and_still_refuses_others(fresh_db, tmp_path):
    run_migrations(fresh_db, _before_in_progress(tmp_path))
    _orders_with_everything(fresh_db)
    run_migrations(fresh_db)
    raw = _raw(fresh_db)
    for status in ("nieuw", "in_behandeling", "verwerkt", "verstuurd", "afgehandeld"):
        assert raw.execute("UPDATE orders SET status = ? WHERE id = '22222222-2222-4222-8222-222222222222'", (status,)).rowcount == 1
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute("UPDATE orders SET status = 'onbekend' WHERE id = '22222222-2222-4222-8222-222222222222'")
    with pytest.raises(sqlite3.IntegrityError):                                                        # the other rules of the table came along
        raw.execute("UPDATE orders SET price_rounding = '0.07' WHERE id = '22222222-2222-4222-8222-222222222222'")
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute("UPDATE orders SET number = 1 WHERE id = '22222222-2222-4222-8222-222222222222'")
    raw.execute("DELETE FROM orders WHERE id = '11111111-1111-4111-8111-111111111111'")                                                  # and the children still follow their order
    assert raw.execute("SELECT count(*) FROM order_lines WHERE order_id = '11111111-1111-4111-8111-111111111111'").fetchone() == (0,)
    assert raw.execute("SELECT count(*) FROM invoice_pdfs").fetchone() == (0,)
    assert raw.execute("SELECT count(*) FROM order_lines WHERE order_id = '22222222-2222-4222-8222-222222222222'").fetchone() == (2,)
    raw.close()


def test_foreign_keys_are_on_again_after_a_migration_that_switched_them_off(fresh_db, tmp_path):
    """The runner's own connection: a migration that needs them off must not leave them off for the ones after it."""
    work = _before_in_progress(tmp_path)
    run_migrations(fresh_db, work)
    shutil.copy(MIGRATIONS_DIR / "0022_order_status_in_progress.sql", work)
    (work / "0023_probe.sql").write_text("CREATE TABLE probe_parent (id INTEGER PRIMARY KEY);\n"
                                         "CREATE TABLE probe_child (parent INTEGER REFERENCES probe_parent (id));\n"
                                         "INSERT INTO probe_child VALUES (42);\n")             # a broken key: refused only while foreign keys are on
    with pytest.raises(sqlite3.IntegrityError):
        run_migrations(fresh_db, work)


def test_a_rebuilding_migration_that_breaks_a_foreign_key_is_rolled_back_whole(fresh_db, tmp_path):
    work = _before_in_progress(tmp_path)
    run_migrations(fresh_db, work)
    (work / "0023_orphan.sql").write_text("-- foreign_keys: off\nCREATE TABLE kid (parent INTEGER REFERENCES orders (id));\nINSERT INTO kid VALUES (42);\n")
    with pytest.raises(RuntimeError, match="foreign key"):
        run_migrations(fresh_db, work)
    raw = _raw(fresh_db)
    assert raw.execute("SELECT name FROM sqlite_master WHERE name = 'kid'").fetchone() is None
    assert raw.execute("SELECT 1 FROM schema_migrations WHERE filename = '0023_orphan.sql'").fetchone() is None
    raw.close()
