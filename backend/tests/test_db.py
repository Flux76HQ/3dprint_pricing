"""The SQLite layer: what comes back as which Python type, the rewrites of Postgres spellings, and the write lock that stands in for
advisory locks, `FOR UPDATE` and `SKIP LOCKED`."""
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app import db
from app.db import Database, ForeignKeyViolation, UniqueViolation, named_lock, next_number, run_migrations, translate


@pytest.fixture
def database(fresh_db):
    run_migrations(fresh_db)
    return Database(fresh_db)


def test_the_file_is_in_wal_mode_and_foreign_keys_are_enforced(database):
    with database.connection() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()["journal_mode"] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()["foreign_keys"] == 1


def test_values_come_back_as_the_types_the_columns_declare(database):
    moment = datetime(2026, 3, 1, 12, 30, 15, 250000, tzinfo=timezone(timedelta(hours=2)))
    with database.connection() as conn:
        user = conn.execute("INSERT INTO users (display_name, preferences) VALUES (%s, %s) RETURNING *", ("Anna", '{"a": [1, 2]}')).fetchone()
        assert isinstance(user["id"], uuid.UUID) and user["preferences"] == {"a": [1, 2]} and user["is_owner"] is False
        assert user["created_at"].tzinfo is not None
        printer = conn.execute("INSERT INTO printers (name, purchase_price, lifetime_hours, power_kw, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING *",
                               ("P1S", Decimal("1299.00"), Decimal("5000"), Decimal("0.35"), moment)).fetchone()
    assert printer["purchase_price"] == Decimal("1299.00") and str(printer["purchase_price"]) == "1299.00"          # the scale is the column's
    assert str(printer["lifetime_hours"]) == "5000.0" and str(printer["power_kw"]) == "0.350"
    assert printer["created_at"] == moment and printer["created_at"].utcoffset() == timedelta(0)                      # stored as UTC
    assert printer["archived"] is False


def test_money_survives_the_trip_exactly(database):
    prices = ["0.01", "0.07", "19.99", "1234567.89", "9999999999.99", "0.10"]
    with database.connection() as conn:
        for n, price in enumerate(prices):
            conn.execute("INSERT INTO packaging_items (name, price) VALUES (%s, %s)", (f"item {n}", Decimal(price)))
        stored = [r["price"] for r in conn.execute("SELECT price FROM packaging_items ORDER BY name").fetchall()]
    assert stored == [Decimal(p) for p in prices] and [str(p) for p in stored] == prices


def test_a_date_is_a_date_and_a_timestamp_compares_as_text(database):
    with database.connection() as conn:
        conn.execute("INSERT INTO customers (number, name) VALUES ('1', 'Anna')")
        customer = conn.execute("SELECT id FROM customers").fetchone()["id"]
        order = conn.execute("INSERT INTO orders (number, customer_name, customer_id, order_date) VALUES (1, 'Anna', %s, %s) RETURNING *",
                             (customer, date(2026, 5, 4))).fetchone()
        assert order["order_date"] == date(2026, 5, 4)
        conn.execute("INSERT INTO invitations (token_hash, kind, expires_at) VALUES (%s, 'new', %s)", (b"a" * 32, datetime.now(timezone.utc) + timedelta(hours=1)))
        conn.execute("INSERT INTO invitations (token_hash, kind, expires_at) VALUES (%s, 'new', %s)", (b"b" * 32, datetime.now(timezone.utc) - timedelta(hours=1)))
        assert conn.execute("SELECT count(*) AS n FROM invitations WHERE expires_at > now()").fetchone()["n"] == 1


def test_a_stored_moment_is_read_in_every_form_it_was_ever_written_and_without_strptime(monkeypatch):
    """`strptime` was the largest single cost of reading a list (docs/performance.md); what it read must still read the same."""
    import _strptime
    monkeypatch.setattr(_strptime, "_strptime_datetime", lambda *args, **kwargs: pytest.fail("strptime is seven times slower than fromisoformat"))
    utc = timezone.utc
    for text, moment in (("2026-11-11 22:53:48.123", datetime(2026, 11, 11, 22, 53, 48, 123000, tzinfo=utc)),          # what `now()` and db._utc_text write
                         ("2026-11-11 22:53:48", datetime(2026, 11, 11, 22, 53, 48, tzinfo=utc)),
                         ("2026-11-11 22:53:48.123456", datetime(2026, 11, 11, 22, 53, 48, 123456, tzinfo=utc)),
                         ("2026-11-11T22:53:48.123", datetime(2026, 11, 11, 22, 53, 48, 123000, tzinfo=utc)),
                         ("2026-11-12 00:53:48.123+02:00", datetime(2026, 11, 11, 22, 53, 48, 123000, tzinfo=utc)),     # an imported value with its own offset
                         ("2026-11-11 17:53:48-05:00", datetime(2026, 11, 11, 22, 53, 48, tzinfo=utc)),
                         ("2026-11-11", datetime(2026, 11, 11, tzinfo=utc))):
        read = db._parse_time(text.encode())
        assert read == moment and read.utcoffset() == timedelta(0), text
    now = datetime.now(timezone(timedelta(hours=2)))
    assert db._parse_time(db._utc_text(now).encode()) == now.replace(microsecond=now.microsecond // 1000 * 1000)       # what is written is what is read back


def test_the_rewrites_of_postgres_spellings():
    assert translate("SELECT %s, '100%%'") == "SELECT ?, '100%'"
    assert translate("WHERE name ILIKE %s") == "WHERE name LIKE ?"
    assert translate("ORDER BY lower(name), lower_u(x)") == "ORDER BY lower_u(name), lower_u(x)"
    assert translate("VALUES (%s::jsonb)") == "VALUES (?)"


def test_like_ignores_case_beyond_ascii(database):
    with database.connection() as conn:
        for name in ("Élodie", "ÉRIC", "bart"):
            conn.execute("INSERT INTO customers (number, name) VALUES (%s, %s)", (name, name))
        assert [r["name"] for r in conn.execute("SELECT name FROM customers WHERE name ILIKE %s ORDER BY name", ("%éL%",)).fetchall()] == ["Élodie"]
        assert [r["name"] for r in conn.execute("SELECT name FROM customers WHERE name ILIKE %s ORDER BY name", ("é%",)).fetchall()] == ["ÉRIC", "Élodie"]


def test_names_are_unique_whatever_the_case_also_with_accents(database):
    with database.connection() as conn:
        conn.execute("INSERT INTO users (display_name) VALUES ('Zoë')")
    with pytest.raises(UniqueViolation):
        with database.connection() as conn:
            conn.execute("INSERT INTO users (display_name) VALUES ('ZOË')")


def test_violations_say_which_kind_they_are(database):
    with pytest.raises(ForeignKeyViolation):
        with database.connection() as conn:
            conn.execute("INSERT INTO webauthn_credentials (user_id, credential_id, public_key) VALUES (%s, %s, %s)", (uuid.uuid4(), b"c", b"k"))
    with pytest.raises(sqlite3.IntegrityError) as caught:
        with database.connection() as conn:
            conn.execute("INSERT INTO printers (name, purchase_price, lifetime_hours) VALUES ('x', -1, 10)")
    assert not isinstance(caught.value, (UniqueViolation, ForeignKeyViolation))               # a failed CHECK is neither


def test_a_refused_delete_is_a_foreign_key_violation_too(database):
    """ON DELETE RESTRICT is a trigger inside SQLite, so it reports SQLITE_CONSTRAINT_TRIGGER and not ..._FOREIGNKEY."""
    with database.connection() as conn:
        customer = conn.execute("INSERT INTO customers (number, name) VALUES ('1', 'Jan') RETURNING id").fetchone()["id"]
        conn.execute("INSERT INTO orders (number, customer_name, customer_id) VALUES (1, 'Jan', %s)", (customer,))
    with pytest.raises(ForeignKeyViolation):
        with database.connection() as conn:
            conn.execute("DELETE FROM customers")
    with database.connection() as conn:
        conn.execute("CREATE TRIGGER no_tariffs BEFORE INSERT ON energy_tariffs BEGIN SELECT RAISE(ABORT, 'no tariffs today'); END")
    with pytest.raises(sqlite3.IntegrityError) as caught:
        with database.connection() as conn:
            conn.execute("INSERT INTO energy_tariffs (name, price_per_kwh) VALUES ('x', 1)")
    assert not isinstance(caught.value, ForeignKeyViolation)                                   # a trigger of our own that says no is not one


def test_a_failed_block_changes_nothing_and_a_successful_one_commits(database):
    with pytest.raises(RuntimeError):
        with database.connection() as conn:
            conn.execute("INSERT INTO users (display_name) VALUES ('Gone')")
            raise RuntimeError
    with database.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM users").fetchone()["n"] == 0
        conn.execute("INSERT INTO users (display_name) VALUES ('Kept')")
        conn.rollback()                                                  # undoes it and carries on in a new transaction
        conn.execute("INSERT INTO users (display_name) VALUES ('Second')")
    with database.connection() as conn:
        assert [r["display_name"] for r in conn.execute("SELECT display_name FROM users").fetchall()] == ["Second"]


def test_numbers_are_never_reused_also_after_a_delete(database):
    with database.connection() as conn:
        assert [next_number(conn, "order") for _ in range(3)] == [1, 2, 3]
        assert next_number(conn, "project") == 1
        conn.execute("DELETE FROM counters WHERE name = 'order' AND 0")
    with database.connection() as conn:
        assert next_number(conn, "order") == 4


def test_numbers_are_unique_when_threads_and_processes_ask_at_once(database, fresh_db):
    got, errors = [], []

    def ask():
        try:
            for _ in range(20):
                with database.connection() as conn:
                    got.append(next_number(conn, "order"))
        except Exception as exc:                                  # pragma: no cover - the assertion below shows it
            errors.append(exc)

    code = ("import sys; sys.path.insert(0, %r); from app.db import Database, next_number\n"
            "d = Database(%r)\n"
            "for _ in range(20):\n"
            "    with d.connection() as c: print(next_number(c, 'order'))\n") % (str(Path(db.__file__).parents[1]), fresh_db)
    other = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    threads = [threading.Thread(target=ask) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    out, _ = other.communicate(timeout=60)
    numbers = got + [int(n) for n in out.split()]
    assert not errors and other.returncode == 0
    assert sorted(numbers) == list(range(1, 101))                  # 4 x 20 + 20, each exactly once


def test_a_second_writer_waits_for_the_first(database):
    order, ready = [], threading.Event()

    def slow():
        with database.connection() as conn:
            conn.execute("INSERT INTO users (display_name) VALUES ('first')")
            ready.set()
            threading.Event().wait(0.5)
            order.append("first done")

    thread = threading.Thread(target=slow)
    thread.start()
    ready.wait(5)
    with database.connection() as conn:                              # waits for the 0.5 s above instead of failing
        order.append("second in")
        conn.execute("INSERT INTO users (display_name) VALUES ('second')")
    thread.join()
    assert order == ["first done", "second in"]


def test_a_named_lock_lets_one_in_at_a_time_and_always_lets_go(database):
    inside, overlap = [], []

    def work():
        with named_lock(database, "demo"):
            inside.append(1)
            overlap.append(len(inside))
            threading.Event().wait(0.1)
            inside.pop()

    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert max(overlap) == 1
    with database.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM app_state WHERE key LIKE 'lock:%'").fetchone()["n"] == 0
    with pytest.raises(RuntimeError):
        with named_lock(database, "demo"):
            raise RuntimeError
    with named_lock(database, "demo"):                                # released after the failure too
        pass


def test_a_lock_left_by_a_dead_worker_expires(database):
    with database.connection() as conn:
        conn.execute("INSERT INTO app_state (key, value) VALUES ('lock:demo', %s)", (db._utc_text(datetime.now(timezone.utc) - timedelta(seconds=1)),))
    with named_lock(database, "demo"):
        pass


def test_the_outbox_claim_hands_each_row_to_one_worker(database):
    from app import push
    user = None
    with database.connection() as conn:
        user = conn.execute("INSERT INTO users (display_name) VALUES ('Anna') RETURNING id").fetchone()["id"]
        for n in range(10):
            conn.execute("INSERT INTO push_outbox (user_id, kind, payload, deliver_after) VALUES (%s, %s, %s, %s)",
                         (user, f"kind{n}", "{}", datetime.now(timezone.utc) - timedelta(minutes=1)))
    claimed = []

    def claim():
        with database.connection() as conn:
            claimed.extend(r["id"] for r in conn.execute(
                "UPDATE push_outbox SET deliver_after = %s WHERE id IN (SELECT id FROM push_outbox WHERE deliver_after <= %s ORDER BY deliver_after LIMIT 4) "
                "RETURNING id", (datetime.now(timezone.utc) + push.LEASE, datetime.now(timezone.utc))).fetchall())

    threads = [threading.Thread(target=claim) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(claimed) == 10 and len(set(claimed)) == 10


# --- blocks that only read, and the connections a thread keeps (docs/performance.md) ------------------------------------------------

def held_write_lock(path):
    """Another connection in the middle of a write: what every other writer waits for."""
    raw = sqlite3.connect(path, isolation_level=None)
    raw.execute("BEGIN IMMEDIATE")
    raw.execute("INSERT INTO packaging_items (name, price) VALUES ('not committed', 1)")
    return raw


def test_a_read_does_not_wait_for_a_writer_and_sees_what_was_committed(database, fresh_db, monkeypatch):
    with database.connection() as conn:
        conn.execute("INSERT INTO packaging_items (name, price) VALUES ('doos', 1)")
    writer = held_write_lock(fresh_db)
    try:
        began = time.monotonic()
        with database.read() as conn:
            names = [row["name"] for row in conn.execute("SELECT name FROM packaging_items").fetchall()]
        assert names == ["doos"] and time.monotonic() - began < 0.5                    # at once, and without the other's unfinished row
        monkeypatch.setattr(db, "BUSY_MS", 300)                                        # (a new connection waits this long; kept short for the test)
        database.close()
        with pytest.raises(sqlite3.OperationalError, match="locked"):                  # the same question in a block that may write does wait
            with database.connection():
                pass
    finally:
        writer.execute("ROLLBACK")
        writer.close()


def test_a_long_read_does_not_hold_up_a_writer_and_keeps_its_own_picture(database):
    with database.connection() as conn:
        conn.execute("INSERT INTO packaging_items (name, price) VALUES ('doos', 1)")
    with database.read() as reader:
        count = lambda: reader.execute("SELECT count(*) AS n FROM packaging_items").fetchone()["n"]
        assert count() == 1
        began = time.monotonic()
        with database.connection() as conn:                                            # a save while the read is still going
            conn.execute("INSERT INTO packaging_items (name, price) VALUES ('folie', 1)")
        assert time.monotonic() - began < 0.5
        assert count() == 1                                                            # one consistent snapshot until the block ends
    with database.read() as reader:
        assert reader.execute("SELECT count(*) AS n FROM packaging_items").fetchone()["n"] == 2


def test_a_block_that_only_reads_cannot_write(database):
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        with database.read() as conn:
            conn.execute("INSERT INTO packaging_items (name, price) VALUES ('doos', 1)")
    for statement in ("UPDATE users SET display_name = 'x'", "DELETE FROM users", "CREATE TABLE t (a)"):
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            with database.read() as conn:
                conn.execute(statement)
    with database.read() as conn:                                                      # and the next block is none the worse for it
        assert conn.read_only and conn.execute("SELECT count(*) AS n FROM packaging_items").fetchone()["n"] == 0
    with database.connection() as conn:
        assert not conn.read_only and conn.execute("PRAGMA query_only").fetchone()["query_only"] == 0


def test_a_thread_keeps_its_connections_between_blocks(database):
    """A new connection parses the whole schema before its first statement; a request has at least two blocks."""
    seen = {"write": [], "read": []}
    for _ in range(3):
        with database.connection() as conn:
            seen["write"].append(conn.raw)
            assert conn.raw.in_transaction
        with database.read() as conn:
            seen["read"].append(conn.raw)
    assert len(set(map(id, seen["write"]))) == 1 and len(set(map(id, seen["read"]))) == 1 and seen["write"][0] is not seen["read"][0]
    assert not seen["write"][0].in_transaction and not seen["read"][0].in_transaction     # nothing is held between blocks

    other = []
    def elsewhere():
        with database.connection() as conn:
            other.append(conn.raw)
    thread = threading.Thread(target=elsewhere)
    thread.start()
    thread.join()
    assert other[0] is not seen["write"][0]                                               # never shared between threads


def test_a_block_inside_a_block_gets_a_connection_of_its_own(database):
    with database.read() as outer:
        with database.read() as inner:
            assert inner.raw is not outer.raw and inner.execute("SELECT 1 AS n").fetchone()["n"] == 1
        assert outer.execute("SELECT 1 AS n").fetchone()["n"] == 1                        # the outer block is undisturbed
    with database.read() as again:
        assert again.raw is outer.raw


def test_a_kept_connection_is_clean_after_a_failed_block_and_gone_after_a_broken_one(database):
    with pytest.raises(RuntimeError):
        with database.connection() as conn:
            kept = conn.raw
            conn.execute("INSERT INTO packaging_items (name, price) VALUES ('doos', 1)")
            raise RuntimeError("the handler failed")
    with database.connection() as conn:
        assert conn.raw is kept and conn.execute("SELECT count(*) AS n FROM packaging_items").fetchone()["n"] == 0      # rolled back, and usable
    with pytest.raises(UniqueViolation):
        with database.connection() as conn:
            conn.execute("INSERT INTO counters (name, last) VALUES ('x', 1)")
            conn.execute("INSERT INTO counters (name, last) VALUES ('x', 1)")
    with database.connection() as conn:
        assert conn.raw is kept                                                           # a refused row is the app's business, not the connection's
    with pytest.raises(sqlite3.OperationalError):
        with database.connection() as conn:
            conn.execute("SELECT * FROM no_such_table")
    with database.connection() as conn:
        assert conn.raw is not kept                                                       # anything else: start again on a new one


def test_a_kept_connection_sees_what_others_wrote_and_closing_lets_go_of_all(database, fresh_db):
    with database.read() as conn:
        first = conn.raw
        assert conn.execute("SELECT count(*) AS n FROM packaging_items").fetchone()["n"] == 0
    other = sqlite3.connect(fresh_db)                                                     # another worker
    other.execute("INSERT INTO packaging_items (id, name, price) VALUES ('00000000-0000-4000-8000-000000000001', 'doos', 1)")
    other.commit()
    other.close()
    with database.read() as conn:
        assert conn.raw is first and conn.execute("SELECT count(*) AS n FROM packaging_items").fetchone()["n"] == 1
    database.close()
    with pytest.raises(sqlite3.ProgrammingError):
        first.execute("SELECT 1")                                                         # closed
    with database.read() as conn:
        assert conn.raw is not first and conn.execute("SELECT count(*) AS n FROM packaging_items").fetchone()["n"] == 1


def test_the_settings_of_a_connection_are_the_ones_chosen(database):
    """Durable commits (an invoice number that was printed must survive a power cut), SQLite's default cache and no memory mapping
    (db._open says why). Changing one is a decision: measure it and write it down in docs/performance.md."""
    for block in (database.connection, database.read):
        with block() as conn:
            setting = lambda name: next(iter(conn.execute(f"PRAGMA {name}").fetchone().values()))
            assert setting("journal_mode") == "wal" and setting("synchronous") == 2 and setting("foreign_keys") == 1
            assert setting("cache_size") == -2000 and setting("mmap_size") == 0
            assert setting("busy_timeout") == db.BUSY_MS
            assert setting("query_only") == (1 if conn.read_only else 0)
