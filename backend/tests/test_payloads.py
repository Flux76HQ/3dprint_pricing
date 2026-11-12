"""A list sends what a list shows, and a screen asks once for what it needs to open (docs/performance.md, section 3).

The list of calculations carried every line of every calculation (1.3 kB a row) for the three numbers a row shows, and the screen of
one calculation sent nine requests before it could draw."""
from pathlib import Path

import pytest

from tests.test_auth_api import H, onboard
from tests.test_domain_api import make, sheet_payload

FRONT = Path(__file__).resolve().parents[2] / "frontend"
LIST_PRICES = {"cost_price", "sell_price", "vat_amount", "sell_price_incl_vat"}


@pytest.fixture
def owner(client):
    onboard(client)
    return client


def shop(owner) -> dict:
    """A little of everything the model editor chooses from, and one calculation."""
    spool = make(owner, "/api/spools", {"brand": "Bambu Lab", "product_type": "Basic", "material": "PLA", "colour": "Zwart", "roll_weight_g": "1000",
                                        "price": "19.99", "remaining_g": "720", "barcode": "6975337030011", "diameter_mm": "1.75", "notify_low": True})
    make(owner, "/api/spools", {"brand": "Sunlu", "material": "PETG", "colour": "Transparant", "roll_weight_g": "1000", "price": "17.50",
                                "remaining_g": "1000", "archived": True})
    make(owner, "/api/printers", {"name": "P1S", "purchase_price": "699", "lifetime_hours": "5000", "power_kw": "0.11"})
    make(owner, "/api/tariffs", {"name": "Thuis", "price_per_kwh": "0.28"})
    make(owner, "/api/packaging", {"name": "Verzenddoos S", "price": "0.42"})
    make(owner, "/api/parts", {"name": "M2.5 schroeven", "price": "0.06", "unit": "stuks"})
    make(owner, "/api/accessories", {"name": "USB-C kabel", "price": "1.40", "unit": "stuks"})
    return make(owner, "/api/projects", {**sheet_payload(spool["id"]), "margin_pct": "120", "vat_pct": "21"})


def test_the_list_of_calculations_carries_their_prices_and_not_their_lines(owner):
    project = shop(owner)
    row, = owner.get("/api/projects").get_json()
    whole = owner.get(f"/api/projects/{project['id']}").get_json()
    assert set(row["totals"]) == LIST_PRICES                                             # what a row shows and sorts on, and nothing else of the totals
    assert row["totals"] == {key: whole["totals"][key] for key in LIST_PRICES}           # the same amounts, to the cent, as text
    assert all(isinstance(value, str) and "." in value for value in row["totals"].values())
    assert "data" not in row and "notes" not in row
    assert {"filament", "parts", "subtotals"} <= set(whole["totals"]) and "data" in whole       # the lines are in the calculation itself
    for key in ("id", "number", "name", "margin_pct", "vat_pct", "price_rounding", "links", "stock_booked_at", "created_at", "updated_at"):
        assert row[key] == whole[key], key
    assert row["cover_image_id"] is None and row["ai_busy"] is False


def test_the_order_editor_asks_for_the_model_it_adds_because_the_list_does_not_hold_its_lines():
    """`modelLines` turns a calculation's accessories into lines of their own; they are in the calculation, not in a row of the list."""
    orders = (FRONT / "js/orders.js").read_text(encoding="utf-8")
    assert "modelLines(await api('GET', `/api/projects/${p.id}`))" in orders and "...modelLines(p)" not in orders       # never from a row of the list


def test_the_screen_of_a_calculation_gets_what_it_opens_with_in_one_answer(owner):
    project = shop(owner)
    bundle = owner.get(f"/api/model-editor?project={project['id']}")
    assert bundle.status_code == 200 and bundle.headers["Cache-Control"] == "no-store"
    answer = bundle.get_json()
    # Every part is exactly what its own address answers: the screen cannot tell the difference, and nothing is decided in two places.
    for part in ("spools", "printers", "tariffs", "packaging", "parts", "accessories"):
        assert answer[part] == owner.get(f"/api/{part}").get_json() and answer[part], part
    assert answer["stock"] == owner.get("/api/spools/stock").get_json() and answer["stock"]["groups"]
    assert answer["project"] == owner.get(f"/api/projects/{project['id']}").get_json()
    assert answer["listing"] == owner.get(f"/api/projects/{project['id']}/listing").get_json() == {"listing": None, "photos": [], "max_photos": 12}
    assert answer["spoolman"] == {"enabled": owner.get("/api/spoolman").get_json()["enabled"]} == {"enabled": False}
    assert answer["haspelsync"] == {"enabled": owner.get("/api/haspelsync").get_json()["enabled"]} == {"enabled": False}
    assert set(answer) == {"spools", "printers", "tariffs", "packaging", "parts", "accessories", "stock", "project", "listing", "spoolman", "haspelsync"}
    assert any(roll["archived"] for roll in answer["spools"])                            # the lists are whole; the screen leaves out what is archived

    new = owner.get("/api/model-editor").get_json()                                      # a new calculation: the lists, and no calculation
    assert new["project"] is None and new["listing"] is None and new["printers"] == answer["printers"]


def test_the_one_answer_refuses_what_the_calculation_itself_would_refuse(owner, client):
    shop(owner)
    for unknown in ("00000000-0000-4000-8000-000000000000", "not-an-id"):
        refused = owner.get(f"/api/model-editor?project={unknown}")
        assert refused.status_code == 404 and refused.get_json()["error"], unknown
    owner.post("/api/auth/logout", headers=H)
    assert client.get("/api/model-editor").status_code == 401


def test_with_a_spoolman_the_one_answer_says_so(owner, app):
    import dataclasses
    app.config["APP_CONFIG"] = dataclasses.replace(app.config["APP_CONFIG"], spoolman_url="http://spoolman.test:7912")
    assert owner.get("/api/model-editor").get_json()["spoolman"] == {"enabled": True}
    assert owner.get("/api/spoolman").get_json()["enabled"] is True


def test_the_screen_asks_once():
    source = (FRONT / "js/projects.js").read_text(encoding="utf-8")
    editor = source[source.index("export function projectEditorView"):source.index("function buildEditor")]
    assert "api('GET', `/api/model-editor${id ? `?project=${id}` : ''}`)" in editor and editor.count("api('GET'") == 1


def test_the_list_of_orders_reads_only_what_a_row_shows(owner, monkeypatch):
    """An order has 30 columns and each of its lines three ids; turning all of that into Python values was most of the time of the list."""
    from app import db
    customer = make(owner, "/api/customers", {"number": "", "name": "Anna"})
    lines = [{"project_id": None, "description": "los", "quantity": 2, "vat_pct": "21", "unit_price": "12.10"},
             {"project_id": None, "description": "boek", "quantity": 1, "vat_pct": "9", "unit_price": "10.90"}]
    order = make(owner, "/api/orders", {"customer_id": customer["id"], "status": "nieuw", "order_date": "2026-11-11", "price_rounding": "none", "lines": lines})
    sent, execute = [], db.Connection.execute
    monkeypatch.setattr(db.Connection, "execute", lambda self, sql, params=(): sent.append(sql) or execute(self, sql, params))
    row, = owner.get("/api/orders").get_json()
    read = [sql for sql in sent if "FROM orders" in sql or "FROM order_lines" in sql]
    assert len(read) == 2 and not any("SELECT *" in sql for sql in read), read
    assert any(sql.startswith("SELECT order_id, quantity, unit_price, vat_pct FROM order_lines") for sql in read)
    whole = owner.get(f"/api/orders/{order['id']}").get_json()
    assert row["total"] == whole["totals"]["total"] == "35.10" and row["line_count"] == 2          # the same total as the order itself works out
    for key in ("id", "number", "status", "order_date", "delivery_date", "customer_id", "customer_name", "customer_number", "subject", "city",
                "invoice_number", "invoice_date", "updated_at"):
        assert row[key] == whole[key], key
    assert set(row) == {"id", "number", "status", "order_date", "delivery_date", "customer_id", "customer_name", "customer_number", "subject", "city",
                        "invoice_number", "invoice_date", "updated_at", "line_count", "total"}
