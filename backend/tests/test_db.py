"""The SQLite layer: what comes back as which Python type, the rewrites of Postgres spellings, and the write lock that stands in for
advisory locks, `FOR UPDATE` and `SKIP LOCKED`."""
import sqlite3
import subprocess
import sys
import threading
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
