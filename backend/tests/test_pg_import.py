"""The one-off move from PostgreSQL to SQLite (`app/pg_import.py`).

The source is made the honest way: an app on SQLite is filled through its own API (people, passkeys, a password, calculations, orders, an invoice,
a template, pictures), the rows are copied into a PostgreSQL that has the *old* schema, and the importer must hand back a SQLite file that holds
the same rows, with which the app then works as before: the same passkey signs in, the invoice opens, the numbering carries on.
Needs a PostgreSQL (TEST_DATABASE_URL, or the system's binaries as root); CI provides one.
"""
import json
import shutil
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app import create_app, db, pg_import
from app.config import Config
from tests.conftest import ORIGIN, RP_ID, SECRET, SETUP_CODE
from tests.test_auth_api import H, login, post
from tests.test_backup import fill, fill_orders
from tests.test_password import PASSWORD, _reset_limits, enable_password, owner  # noqa: F401  (fixtures)

SIGNED_NAME = "Zoë Ñandú"                                           # not ASCII, on purpose


@pytest.fixture
def legacy(database_url):
    """An empty PostgreSQL, to be given the old schema."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    return database_url


def copy_to_postgres(sqlite_path: str, url: str) -> None:
    """Put the rows of an app database into a PostgreSQL that has the old schema, as that release would have kept them."""
    lite = db._open(sqlite_path)
    lite.row_factory = None
    pg_import.bring_up_to_date(url)
    with psycopg.connect(url) as pg:
        for table in pg_import._tables_in_order(lite):
            columns = [(name, (declared.split() or [""])[0].upper()) for _c, name, declared, *_r in lite.execute(f"PRAGMA table_info('{table}')").fetchall()]
            exists = {r[0] for r in pg.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s", (table,))}
            columns = [c for c in columns if c[0] in exists]
            if not columns:
                continue
            marks = ", ".join(["%s"] * len(columns))
            for row in lite.execute(f"SELECT {', '.join(c[0] for c in columns)} FROM {table}").fetchall():
                values = [Jsonb(v) if kind == "JSON" and v is not None else v for v, (_n, kind) in zip(row, columns)]
                pg.execute(f"INSERT INTO {table} ({', '.join(c[0] for c in columns)}) VALUES ({marks})", values)
        for name, sequence in (("project", "project_number_seq"), ("order", "order_number_seq")):
            last = lite.execute("SELECT last FROM counters WHERE name = ?", (name,)).fetchone()
            if last:
                pg.execute("SELECT setval(%s, %s)", (sequence, last[0]))
        for table in ("ai_image_log", "spoolman_pending_use"):
            pg.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), GREATEST((SELECT max(id) FROM {table}), 1), (SELECT count(*) > 0 FROM {table}))")
    lite.close()


def rows_of(path: str, table: str) -> list:
    conn = db._open(path)
    try:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        conn.close()
    return sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))


def app_on(path, tmp_path):
    cfg = Config(database_path=str(path), session_secret=SECRET, setup_code=SETUP_CODE, rp_id=RP_ID, rp_name="Test", rp_origins=(ORIGIN,), session_hours=24,
                 cookie_secure=True, upload_dir=str(tmp_path / "uploads"), max_upload_mb=2, static_dir=str(Path(__file__).parent / "static"))
    return create_app(cfg)


def test_everything_comes_across_and_the_app_goes_on_where_it_stopped(owner, app, legacy, tmp_path, fresh_db):
    fill(owner)
    _project, order, paper = fill_orders(owner)
    enable_password(owner)
    new_name = post(owner, "/api/users/invites", {"name": SIGNED_NAME})                          # an open invitation travels too
    assert new_name.status_code == 201
    before = {"orders": owner.get("/api/orders").get_json(), "projects": owner.get("/api/projects").get_json(),
              "spools": owner.get("/api/spools").get_json(), "pdf": owner.get(f"/api/orders/{order['id']}/invoice").data}
    copy_to_postgres(fresh_db, legacy)

    target = tmp_path / "imported" / "printpricing.sqlite3"
    counts = pg_import.import_from_postgres(legacy, str(target))
    assert target.exists() and not Path(str(target) + ".importing").exists()
    assert counts["orders"] == 1 and counts["invoice_pdfs"] == 1 and counts["users"] >= 1

    skipped = set(pg_import.SKIP)
    conn = db._open(fresh_db)
    tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall()]
    conn.close()
    for table in tables:
        if table in skipped or table == "app_state":
            continue
        assert rows_of(str(target), table) == rows_of(fresh_db, table), table                  # the same rows, value by value
    state = {r["key"]: r["value"] for r in rows_of(str(target), "app_state")}
    marker = json.loads(state.pop("imported_from_postgres"))                                       # what the import leaves to say that it happened
    assert marker["rows"]["orders"] == 1 and state == {r["key"]: r["value"] for r in rows_of(fresh_db, "app_state")}
    assert rows_of(str(target), "counters") == rows_of(fresh_db, "counters")
    assert rows_of(str(target), "webauthn_challenges") == [] and rows_of(str(target), "backup_jobs") == []
    assert [r["filename"] for r in rows_of(str(target), "schema_migrations")] == ["0001_init.sql"]
    assert db.run_migrations(str(target)) == []                                                    # the file is a normal one from here on

    imported = app_on(target, tmp_path).test_client()
    status = imported.get("/api/auth/status").get_json()
    assert status["onboarded"] and status["password_login"] is True and status["passkey_login"] is True
    signed_in = login(imported, owner.passkey)                                                      # the passkey that was registered before
    assert signed_in.status_code == 200
    by_password = imported.post("/api/auth/password/login", json={"name": "Helmer", "password": PASSWORD}, headers=H)
    assert by_password.status_code == 200
    assert imported.get("/api/orders").get_json() == before["orders"]
    assert imported.get("/api/projects").get_json() == before["projects"]
    assert imported.get("/api/spools").get_json() == before["spools"]
    assert imported.get(f"/api/orders/{order['id']}/invoice").data == before["pdf"]
    # the numbering carries on
    highest_project = max(p["number"] for p in before["projects"])
    highest_order = max(o["number"] for o in before["orders"])
    made = imported.post("/api/projects", json=imported.get(f"/api/projects/{before['projects'][0]['id']}").get_json(), headers=H).get_json()
    assert made["number"] == highest_project + 1
    follow = imported.post("/api/orders", json={"customer_id": order["customer_id"], "lines": [{"description": "Vaas", "quantity": 1, "unit_price": "1.00", "vat_pct": "21"}]}, headers=H).get_json()
    assert follow["number"] == highest_order + 1
    assert imported.post(f"/api/orders/{follow['id']}/invoice", headers=H).status_code == 200
    assert imported.get(f"/api/orders/{follow['id']}").get_json()["invoice_number"] != order["invoice_number"]


def test_a_failure_halfway_leaves_no_database_and_the_next_start_tries_again(owner, legacy, tmp_path, fresh_db, monkeypatch):
    fill(owner)
    copy_to_postgres(fresh_db, legacy)
    target = tmp_path / "new" / "printpricing.sqlite3"
    real = pg_import._copy_table
    seen = []

    def breaking(pg, lite, table):
        seen.append(table)
        if len(seen) == 6:
            raise RuntimeError("the disk is full")
        return real(pg, lite, table)

    monkeypatch.setattr(pg_import, "_copy_table", breaking)
    with pytest.raises(RuntimeError):
        pg_import.maybe_import(legacy, str(target))
    assert not target.exists()                                                                       # nothing was put in its place
    monkeypatch.setattr(pg_import, "_copy_table", real)
    assert pg_import.maybe_import(legacy, str(target))["filament_spools"] == 2                                 # and the leftovers did not matter
    assert target.exists()
    with psycopg.connect(legacy) as pg:
        assert pg.execute("SELECT count(*) FROM filament_spools").fetchone()[0] == 2                  # the old database was only read


def test_a_copy_that_differs_is_refused(owner, legacy, tmp_path, fresh_db, monkeypatch):
    fill_orders(owner)
    copy_to_postgres(fresh_db, legacy)
    real = pg_import._copy_table

    def lossy(pg, lite, table):
        count = real(pg, lite, table)
        if table == "invoice_pdfs":
            lite.execute("UPDATE invoice_pdfs SET content = substr(content, 1, length(content) - 1)")     # one byte lost
        return count

    monkeypatch.setattr(pg_import, "_copy_table", lossy)
    target = tmp_path / "x" / "printpricing.sqlite3"
    with pytest.raises(pg_import.ImportFailed, match="stored file differs"):
        pg_import.import_from_postgres(legacy, str(target))
    assert not target.exists()


def test_the_numbers_after_a_restore_that_left_the_sequences_uncalled_are_not_lower_than_the_rows(owner, legacy, tmp_path, fresh_db):
    fill(owner)
    copy_to_postgres(fresh_db, legacy)
    with psycopg.connect(legacy) as pg:
        pg.execute("ALTER SEQUENCE project_number_seq RESTART WITH 1")                              # as a restore does when nothing is left
    target = tmp_path / "x" / "printpricing.sqlite3"
    pg_import.import_from_postgres(legacy, str(target))
    conn = db._open(str(target))
    assert conn.execute("SELECT last FROM counters WHERE name = 'project'").fetchone()["last"] == conn.execute("SELECT max(number) AS n FROM projects").fetchone()["n"]


def test_nothing_happens_when_there_is_nothing_to_import(legacy, tmp_path, fresh_db, monkeypatch):
    monkeypatch.setattr(pg_import, "MAX_WAIT_SECONDS", 1)
    target = tmp_path / "x" / "printpricing.sqlite3"
    assert pg_import.maybe_import("", str(target)) is None                                           # no old database configured
    assert pg_import.maybe_import(legacy, str(target)) is None and not target.exists()               # a brand new, empty PostgreSQL
    target.parent.mkdir()
    target.write_bytes(b"")                                                                          # a SQLite file is there already: the old data is not looked at
    pg_import.bring_up_to_date(legacy)
    assert pg_import.maybe_import(legacy, str(target)) is None


def test_an_old_database_unreachable_stops_the_start_instead_of_starting_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(pg_import, "MAX_WAIT_SECONDS", 1)
    target = tmp_path / "x" / "printpricing.sqlite3"
    with pytest.raises(pg_import.ImportFailed, match="cannot be reached"):
        pg_import.maybe_import("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1", str(target))
    assert not target.exists()


def test_an_installation_from_several_releases_back_is_brought_up_to_date_first(legacy, tmp_path, monkeypatch):
    old = tmp_path / "old_migrations"
    old.mkdir()
    for path in sorted(pg_import.LEGACY_MIGRATIONS_DIR.glob("*.sql")):
        if path.name[:4] <= "0010":
            shutil.copy(path, old / path.name)
    monkeypatch.setattr(pg_import, "LEGACY_MIGRATIONS_DIR", old)
    pg_import.bring_up_to_date(legacy)
    with psycopg.connect(legacy) as pg:                                                              # the data of that release
        pg.execute("INSERT INTO users (display_name, preferences) VALUES ('Helmer', %s)", (Jsonb({"theme": "dark", "business": {"name": "Flux76"}}),))
        pg.execute("INSERT INTO printers (name, purchase_price, lifetime_hours) VALUES ('X1C', 1500, 3000)")
        pg.execute("INSERT INTO projects (name, data, totals) VALUES ('Vaas', %s, %s)", (Jsonb({}), Jsonb({"cost_price": "2.74"})))
    monkeypatch.undo()
    target = tmp_path / "x" / "printpricing.sqlite3"
    counts = pg_import.maybe_import(legacy, str(target))
    assert counts["users"] == 1 and counts["printers"] == 1 and counts["projects"] == 1
    conn = db._open(str(target))
    assert conn.execute("SELECT role, is_owner FROM users").fetchone() == {"role": "admin", "is_owner": True}        # what migration 0024 made of the first person
    assert conn.execute("SELECT preferences FROM shared_preferences").fetchone()["preferences"] == {"business": {"name": "Flux76"}}
    assert conn.execute("SELECT preferences FROM users").fetchone()["preferences"] == {"theme": "dark"}
    assert conn.execute("SELECT number FROM projects").fetchone()["number"] == 1
    assert conn.execute("SELECT last FROM counters WHERE name = 'project'").fetchone()["last"] >= 1


def test_text_with_accents_stays_unique_in_the_new_file(owner, legacy, tmp_path, fresh_db):
    post(owner, "/api/customers", {"name": SIGNED_NAME, "number": "Ñ-1"})
    copy_to_postgres(fresh_db, legacy)
    target = tmp_path / "x" / "printpricing.sqlite3"
    pg_import.import_from_postgres(legacy, str(target))
    imported = app_on(target, tmp_path).test_client()
    login(imported, owner.passkey)
    assert imported.get("/api/customers").get_json()[0]["name"] == SIGNED_NAME
    clash = imported.post("/api/customers", json={"name": "Someone", "number": "ñ-1"}, headers=H)
    assert clash.status_code == 409
