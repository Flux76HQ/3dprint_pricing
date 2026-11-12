"""The statements the code really sends find their rows through an index.

An index that no test looks at is a hope: a rewritten query stops using it and nobody notices, because every query is fast on the
small database of a test. Here the statements are recorded while the app handles a request, and SQLite is asked for the plan of each
(`EXPLAIN QUERY PLAN`), so a changed query, a dropped index or one that the query cannot use fails here. The scans were found by
explaining every statement the suite sends on a grown database: docs/performance.md, migration 0006."""
import re

import pytest

from app import ai_images, db, push
from tests.test_ai_images import FakeOpenAI, KEY, photo
from tests.test_auth_api import H, onboard, post
from tests.test_domain_api import make, sheet_payload

# The indexes these plans rely on. One that goes missing (a table rebuilt by a migration loses its indexes) fails by name.
EXPECTED_INDEXES = {"filament_spools_barcode", "order_lines_project_idx", "ai_image_jobs_batch", "ai_image_jobs_unfinished", "push_outbox_due",
                    "project_images_one_cover", "project_images_project", "ai_image_jobs_project", "order_lines_order_idx", "orders_customer_idx",
                    "orders_order_date_idx", "projects_file_id"}


@pytest.fixture
def owner(client):
    onboard(client)
    return client


@pytest.fixture
def sent(monkeypatch):
    """Every statement the app sends from here on, with its values."""
    seen, execute = [], db.Connection.execute

    def recording(self, sql, params=()):
        seen.append((db.translate(sql), tuple(params)))
        return execute(self, sql, params)

    monkeypatch.setattr(db.Connection, "execute", recording)
    return seen


def plans(fresh_db, sent, containing):
    """[(statement, its plan as one text)] of the recorded statements that contain `containing`."""
    raw = db._open(fresh_db)
    try:
        return [(sql, "\n".join(row["detail"] for row in raw.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()))
                for sql, params in dict.fromkeys(sent) if containing in sql]
    finally:
        raw.close()


def through(plan: str, index: str) -> bool:
    return re.search(rf"USING (COVERING )?INDEX {index}\b", plan) is not None


def test_the_indexes_exist(fresh_db, app):
    raw = db._open(fresh_db)
    have = {row["name"] for row in raw.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()}
    raw.close()
    assert EXPECTED_INDEXES <= have, EXPECTED_INDEXES - have


def test_a_scanned_barcode_is_found_through_its_index(owner, fresh_db, sent):
    """The index used to be `WHERE barcode <> ''`, which `barcode = ?` cannot use: every scan read every roll."""
    roll = {"brand": "Bambu Lab", "product_type": "Basic", "material": "PLA", "colour": "Zwart", "roll_weight_g": "1000", "price": "19.99",
            "remaining_g": "720", "barcode": "6975337030011", "diameter_mm": "1.75"}
    first = make(owner, "/api/spools", roll)
    make(owner, "/api/spools", roll)
    sent.clear()
    assert owner.get("/api/spools/lookup?barcode=6975337030011").status_code == 200
    assert owner.get("/api/spools/from-barcode?barcode=6975337030011").status_code == 200
    assert owner.get(f"/api/spools/{first['id']}/siblings").get_json()["count"] == 1
    assert post(owner, f"/api/spools/{first['id']}/propagate", {"fields": ["brand"]}).status_code == 200
    found = plans(fresh_db, sent, "barcode = ?")
    assert len(found) >= 4
    for sql, plan in found:
        assert through(plan, "filament_spools_barcode") and "SCAN filament_spools" not in plan, (sql, plan)
    newest = [plan for sql, plan in found if "ORDER BY created_at DESC LIMIT 1" in sql]
    assert newest and all("TEMP B-TREE" not in plan for plan in newest)                       # and the newest roll comes without sorting them


def test_removing_a_model_does_not_read_every_order_line(owner, fresh_db, sent):
    project = make(owner, "/api/projects", sheet_payload())
    sent.clear()
    assert owner.delete(f"/api/projects/{project['id']}", headers=H).status_code == 200
    (sql, plan), = plans(fresh_db, sent, "DELETE FROM projects")
    assert through(plan, "order_lines_project_idx") and "SCAN order_lines" not in plan, plan
    assert through(plan, "project_images_project") and through(plan, "ai_image_jobs_project"), plan       # its pictures and their jobs go with it


def test_the_list_of_models_looks_up_each_cover_and_each_busy_mark_through_an_index(owner, fresh_db, sent):
    """They are looked up once per row of the list: without an index the list reads the pictures table once per model."""
    make(owner, "/api/projects", sheet_payload())
    sent.clear()
    assert len(owner.get("/api/projects").get_json()) == 1
    (sql, plan), = plans(fresh_db, sent, "FROM projects ORDER BY updated_at DESC")
    assert through(plan, "project_images_one_cover") and through(plan, "ai_image_jobs_project"), plan
    assert [line for line in plan.splitlines() if line.startswith("SCAN")] == ["SCAN projects"], plan     # the list itself is every row, by design


def test_orders_find_their_lines_and_a_customer_their_orders_through_an_index(owner, fresh_db, sent):
    customer = make(owner, "/api/customers", {"number": "", "name": "Anna"})
    order = make(owner, "/api/orders", {"customer_id": customer["id"], "status": "nieuw", "order_date": "2026-11-11", "price_rounding": "none",
                                        "lines": [{"project_id": None, "description": "los", "quantity": 1, "vat_pct": "21", "unit_price": "12.10"}]})
    sent.clear()
    assert len(owner.get("/api/orders").get_json()) == 1 and owner.get(f"/api/orders/{order['id']}").status_code == 200
    assert owner.get(f"/api/customers/{customer['id']}").status_code == 200
    lines = plans(fresh_db, sent, "FROM order_lines WHERE order_id IN")
    assert lines and all(through(plan, "order_lines_order_idx") and "SCAN order_lines" not in plan for _sql, plan in lines), lines
    (sql, plan), = plans(fresh_db, sent, "FROM orders WHERE customer_id = ?")
    assert through(plan, "orders_customer_idx"), plan
    (sql, plan), = plans(fresh_db, sent, "FROM orders ORDER BY order_date DESC")
    assert through(plan, "orders_order_date_idx"), plan                                        # newest first without sorting all of them


def test_the_pictures_being_made_are_found_by_batch_and_by_not_being_finished(owner, app, fresh_db, sent, monkeypatch):
    import dataclasses
    app.config["APP_CONFIG"] = dataclasses.replace(app.config["APP_CONFIG"], ai_images_enabled=True)
    monkeypatch.setattr(ai_images, "_start", lambda app, project_id, batch: ai_images._run_batch(app, project_id, batch))
    ai_images._limit.hits.clear()
    project = make(owner, "/api/projects", {**sheet_payload(), "object_description": "plantenbak"})
    assert owner.put("/api/ai-images/settings", json={"api_key": KEY}, headers=H).status_code == 200
    assert photo(owner, project["id"]).status_code == 201
    FakeOpenAI(monkeypatch)
    sent.clear()
    assert post(owner, f"/api/projects/{project['id']}/images/generate", {"purpose": "webshop", "variants": ["square"]}).status_code == 202
    assert owner.get(f"/api/projects/{project['id']}/images").status_code == 200
    batch = plans(fresh_db, sent, "batch_id = ?")
    assert len(batch) >= 2
    for sql, plan in batch:
        assert through(plan, "ai_image_jobs_batch") and "SCAN ai_image_jobs" not in plan, (sql, plan)
    stopped = plans(fresh_db, sent, "error_key = 'ai.err_interrupted'")                         # the look for jobs that stopped moving, at every visit
    assert stopped and all(through(plan, "ai_image_jobs_unfinished") and "SCAN ai_image_jobs" not in plan for _sql, plan in stopped), stopped


def test_the_notifications_that_are_due_are_found_through_an_index(owner, app, fresh_db, sent):
    """Every worker asks for them again and again; the table holds the ones that wait for the end of someone's quiet hours."""
    push.run_outbox_once(app.extensions["pool"], app.config["APP_CONFIG"])
    (sql, plan), = plans(fresh_db, sent, "FROM push_outbox WHERE deliver_after <= ?")
    assert through(plan, "push_outbox_due") and "SCAN push_outbox" not in plan and "TEMP B-TREE" not in plan, plan


def test_the_session_of_every_request_is_one_lookup_by_key(owner, fresh_db, sent):
    sent.clear()
    assert owner.get("/api/printers").status_code == 200
    (sql, plan), = plans(fresh_db, sent, "SELECT role, is_owner, session_epoch FROM users WHERE id = ?")
    assert plan.startswith("SEARCH users USING INDEX sqlite_autoindex_users_1"), plan
