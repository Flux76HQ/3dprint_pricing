"""Reading does not wait for writing, and the other way round (`Database.read()`, section 6h of AGENTS.md).

Every block used to take the file's write lock, also one that only read, so a list waited for a save and everything waited for a
backup, which reads every picture. The screens' reads and the backup are snapshots now. Numbers: docs/performance.md."""
import sqlite3
import threading
import time

import pytest

from app import backup, db
from tests.test_auth_api import H, onboard
from tests.test_domain_api import make, sheet_payload


@pytest.fixture
def owner(client):
    onboard(client)
    return client


def test_the_screens_read_while_another_request_is_in_the_middle_of_a_write(owner, app, fresh_db, monkeypatch):
    printer = make(owner, "/api/printers", {"name": "P1S", "purchase_price": "699", "lifetime_hours": "5000", "power_kw": "0.11"})
    project = make(owner, "/api/projects", sheet_payload())
    customer = make(owner, "/api/customers", {"number": "", "name": "Anna"})
    order = make(owner, "/api/orders", {"customer_id": customer["id"], "status": "nieuw", "order_date": "2026-11-11", "price_rounding": "none",
                                        "lines": [{"project_id": None, "description": "los", "quantity": 1, "vat_pct": "21", "unit_price": "12.10"}]})
    monkeypatch.setattr(db, "BUSY_MS", 300)                       # how long a block that needs the write lock waits; short, so a mistake fails fast
    app.extensions["pool"].close()
    writer = sqlite3.connect(fresh_db, isolation_level=None)      # another worker, half way through a save
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("UPDATE printers SET name = 'not committed'")
    try:
        # What the lists, the model editor and the order editor ask for when they open, and what every request starts with (the session).
        for path in ("/api/auth/status", "/api/preferences", "/api/projects", f"/api/projects/{project['id']}", "/api/spools", "/api/spools/stock",
                     "/api/printers", "/api/tariffs", "/api/packaging", "/api/parts", "/api/accessories", "/api/filament-library", "/api/orders",
                     f"/api/orders/{order['id']}", "/api/customers", f"/api/customers/{customer['id']}", "/api/spoolman", "/api/users",
                     "/api/push/config", "/api/auth/password/status", "/api/auth/credentials", "/api/invoice-template", "/api/invoice-logo",
                     "/api/backup/auto", "/readyz"):                                        # (a backup download ends with a small write: the moment it was made)
            began = time.monotonic()
            answer = owner.get(path)
            assert answer.status_code == 200 and time.monotonic() - began < 0.25, path
        assert owner.get("/api/printers").get_json()[0]["name"] == "P1S"                       # the other's unfinished change is not seen
        # A save does wait for that other save, and gives up after the wait: the lock is real.
        refused = owner.patch(f"/api/printers/{printer['id']}", json={"name": "X1"}, headers=H)
        assert refused.status_code == 500
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    assert owner.patch(f"/api/printers/{printer['id']}", json={"name": "X1"}, headers=H).status_code == 200


@pytest.mark.parametrize("path", ["/api/backup", "/api/backup?files=1"])
def test_a_backup_being_read_does_not_hold_up_a_save(owner, app, monkeypatch, path):
    """The backup reads everything, pictures included, in one block. That block is a snapshot: a save in the meantime goes through, and
    the backup holds the data as it was when it started."""
    import io
    import json
    import zipfile
    make(owner, "/api/printers", {"name": "P1S", "purchase_price": "699", "lifetime_hours": "5000", "power_kw": "0.11"})
    reading, saved, result = threading.Event(), threading.Event(), {}
    export_orders = backup._export_orders

    def slow(conn):
        reading.set()                                             # the backup is in the middle of its read
        saved.wait(5)
        return export_orders(conn)

    monkeypatch.setattr(backup, "_export_orders", slow)
    cookie = owner.get_cookie("pp_session").value

    def download():                                               # another person's browser, in another thread of the worker
        client = app.test_client()
        client.set_cookie("pp_session", cookie)
        result["answer"] = client.get(path)

    thread = threading.Thread(target=download)
    thread.start()
    assert reading.wait(5)
    began = time.monotonic()
    made = owner.post("/api/printers", json={"name": "A1", "purchase_price": "249", "lifetime_hours": "3500", "power_kw": "0.08"}, headers=H)
    waited = time.monotonic() - began
    saved.set()
    thread.join()
    assert made.status_code == 201 and waited < 0.5
    answer = result["answer"]
    assert answer.status_code == 200
    doc = json.loads(zipfile.ZipFile(io.BytesIO(answer.data)).read("backup.json")) if "files" in path else answer.get_json()
    assert [p["name"] for p in doc["printers"]] == ["P1S"]                                     # as it was when the backup started
    assert sorted(p["name"] for p in owner.get("/api/printers").get_json()) == ["A1", "P1S"]


def test_requests_in_several_threads_at_once_each_use_their_own_connection(owner, app):
    """Gunicorn runs the app with threads (`--worker-class gthread`, deploy/entrypoint.sh): every thread reads and writes at once.
    A thread keeps its own connections; a write waits its turn for the file's one write lock and none is lost."""
    cookie = owner.get_cookie("pp_session").value
    pool, used, errors = app.extensions["pool"], set(), []
    take = pool._take

    def watched(read_only):
        conn, kept = take(read_only)
        used.add((threading.get_ident(), id(conn.raw)))
        return conn, kept

    pool._take = watched
    start = threading.Barrier(8)

    def person(n):
        client = app.test_client()
        client.set_cookie("pp_session", cookie)
        start.wait(5)
        try:
            for i in range(12):
                made = client.post("/api/packaging", json={"name": f"doos {n}-{i}", "price": "0.42"}, headers=H)
                assert made.status_code == 201, made.get_json()
                assert client.get("/api/packaging").status_code == 200 and client.get("/api/projects").status_code == 200
        except Exception as exc:                                   # an assertion in a thread is otherwise lost
            errors.append(exc)

    threads = [threading.Thread(target=person, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    del pool._take
    assert not errors, errors[0]
    assert len(owner.get("/api/packaging").get_json()) == 8 * 12                               # every save is there, once
    by_thread = {}
    for thread, conn in used:
        by_thread.setdefault(conn, set()).add(thread)
    assert all(len(threads) == 1 for threads in by_thread.values())                            # no connection was ever used by two threads
    assert len({thread for thread, _conn in used}) == 8
