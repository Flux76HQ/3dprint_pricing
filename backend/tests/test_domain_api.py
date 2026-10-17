import pytest

from tests.test_auth_api import H, onboard, post


@pytest.fixture
def owner(client):
    onboard(client)
    return client


def make(client, path, body):
    res = client.post(path, json=body, headers=H)
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def test_printer_crud_and_validation(owner):
    p = make(owner, "/api/printers", {"name": "Bambu X1C", "purchase_price": "750",
                                      "lifetime_hours": "3000", "power_kw": "0.15"})
    assert p["purchase_price"] == "750.00" and p["archived"] is False
    assert owner.post("/api/printers", json={"name": "x"}, headers=H).status_code == 400
    assert owner.post("/api/printers", json={"name": "x", "purchase_price": 1, "lifetime_hours": 0},
                      headers=H).status_code == 400
    res = owner.patch(f"/api/printers/{p['id']}", json={"archived": True}, headers=H)
    assert res.get_json()["archived"] is True
    assert owner.delete(f"/api/printers/{p['id']}", headers=H).status_code == 200
    assert owner.get("/api/printers").get_json() == []
    assert owner.delete(f"/api/printers/{p['id']}", headers=H).status_code == 404


def test_first_tariff_is_default_and_default_moves(owner):
    a = make(owner, "/api/tariffs", {"name": "Dynamisch", "price_per_kwh": "0.22"})
    assert a["is_default"] is True
    b = make(owner, "/api/tariffs", {"name": "Zon", "price_per_kwh": "0.05", "is_default": True})
    rows = {t["name"]: t["is_default"] for t in owner.get("/api/tariffs").get_json()}
    assert rows == {"Dynamisch": False, "Zon": True}
    assert b["is_default"] is True


def test_spool_price_per_kg_comes_from_the_roll(owner):
    s = make(owner, "/api/spools", {"brand": "Bambu ABS Basis", "colour": "Black",
                                    "roll_weight_g": "1000", "price": "26.99", "remaining_g": "1000"})
    assert s["roll_weight_g"] == "1000.0" and s["remaining_g"] == "1000.0"


def sheet_payload(spool_id=None):
    return {
        "name": "USW-Ultra 10-inch rack-mount", "margin_pct": "0",
        "data": {
            "filament": [{"spool_id": spool_id, "label": "Bambu ABS Basis Black", "grams": 70,
                          "price_per_kg": "26.99"}],
            "parts": [],
            "print": {"depreciation": [{"label": "Afschrijving printer", "hours": 3, "price_per_hour": "0.25"}],
                      "energy": [{"label": "Printer", "hours": 3, "kw": "0.15", "price_per_kwh": "0.22"}]},
        },
    }


def test_calculate_endpoint_matches_the_spreadsheet(owner):
    res = post(owner, "/api/calculate", sheet_payload())
    assert res.status_code == 200
    assert res.get_json()["cost_price"] == "2.74"


def test_calculate_rejects_bad_numbers_with_a_message(owner):
    bad = sheet_payload()
    bad["data"]["filament"][0]["grams"] = -5
    res = post(owner, "/api/calculate", bad)
    assert res.status_code == 400 and "gram" in res.get_json()["error"]


def test_project_saves_a_snapshot_and_totals(owner):
    p = make(owner, "/api/projects", sheet_payload())
    assert p["totals"]["cost_price"] == "2.74"
    # a later price change on the spool does not rewrite the saved calculation
    s = make(owner, "/api/spools", {"brand": "X", "roll_weight_g": 1000, "price": 99, "remaining_g": 1000})
    owner.patch(f"/api/spools/{s['id']}", json={"price": 1}, headers=H)
    again = owner.get(f"/api/projects/{p['id']}").get_json()
    assert again["totals"]["cost_price"] == "2.74"
    listing = owner.get("/api/projects").get_json()
    assert listing[0]["name"].startswith("USW") and "data" not in listing[0]
    updated = owner.put(f"/api/projects/{p['id']}", json={**sheet_payload(), "margin_pct": "50"}, headers=H)
    assert updated.get_json()["totals"]["sell_price"] == "4.11"


def test_book_stock_subtracts_once(owner):
    s = make(owner, "/api/spools", {"brand": "ABS", "roll_weight_g": 1000, "price": 26.99, "remaining_g": 500})
    p = make(owner, "/api/projects", sheet_payload(s["id"]))
    res = post(owner, f"/api/projects/{p['id']}/book-stock")
    assert res.status_code == 200 and res.get_json()["spools_updated"] == 1
    remaining = [x for x in owner.get("/api/spools").get_json() if x["id"] == s["id"]][0]["remaining_g"]
    assert remaining == "430.0"
    assert post(owner, f"/api/projects/{p['id']}/book-stock").status_code == 409


def test_book_stock_never_goes_negative_and_says_so(owner):
    s = make(owner, "/api/spools", {"brand": "ABS", "roll_weight_g": 1000, "price": 20, "remaining_g": 30})
    p = make(owner, "/api/projects", sheet_payload(s["id"]))
    res = post(owner, f"/api/projects/{p['id']}/book-stock").get_json()
    assert res["short"] and "ABS" in res["short"][0]
    assert owner.get("/api/spools").get_json()[0]["remaining_g"] == "0.0"


def test_preferences_merge_and_validate(owner):
    res = owner.put("/api/preferences", json={"theme": "dark", "accent": "#6C5CE7"}, headers=H)
    assert res.get_json() == {"theme": "dark", "accent": "#6c5ce7"}
    res = owner.put("/api/preferences", json={"sidebar_collapsed": True}, headers=H)
    assert res.get_json()["theme"] == "dark" and res.get_json()["sidebar_collapsed"] is True
    assert owner.put("/api/preferences", json={"theme": "neon"}, headers=H).status_code == 400
    assert owner.put("/api/preferences", json={"accent": "red"}, headers=H).status_code == 400


def test_health_endpoints_and_spa_fallback(client):
    assert client.get("/healthz").get_json()["status"] == "ok"
    assert client.get("/readyz").get_json()["status"] == "ready"
    assert client.get("/instellingen").status_code == 200       # SPA route
    assert client.get("/api/does-not-exist").status_code == 404  # but never HTML for the API
    assert client.get("/api/does-not-exist").is_json


def test_packaging_items_crud_and_validation(owner):
    box = make(owner, "/api/packaging", {"name": "Doos 20x15x10", "price": "0,85".replace(",", "."), "notes": "bruin karton"})
    assert box["price"] == "0.85" and box["archived"] is False
    assert owner.post("/api/packaging", json={"name": "x"}, headers=H).status_code == 400
    assert owner.post("/api/packaging", json={"name": "x", "price": -1}, headers=H).status_code == 400
    assert owner.patch(f"/api/packaging/{box['id']}", json={"price": "0.95"}, headers=H).get_json()["price"] == "0.95"
    assert owner.patch(f"/api/packaging/{box['id']}", json={"archived": True}, headers=H).get_json()["archived"] is True
    assert owner.delete(f"/api/packaging/{box['id']}", headers=H).status_code == 200
    assert owner.get("/api/packaging").get_json() == []


def test_a_saved_calculation_keeps_the_packaging_price_after_the_item_changes(owner):
    box = make(owner, "/api/packaging", {"name": "Doos", "price": "0.85"})
    body = sheet_payload()
    body["data"]["parts"] = [{"group": "verpakking", "label": "Doos", "packaging_id": box["id"],
                              "quantity": 2, "unit": "stuks", "unit_price": "0.85"}]
    p = make(owner, "/api/projects", body)
    assert p["totals"]["subtotals"]["packaging"] == "1.70"
    owner.patch(f"/api/packaging/{box['id']}", json={"price": "5"}, headers=H)
    owner.delete(f"/api/packaging/{box['id']}", headers=H)
    again = owner.get(f"/api/projects/{p['id']}").get_json()
    assert again["totals"]["subtotals"]["packaging"] == "1.70"
    assert again["data"]["parts"][0]["packaging_id"] == box["id"]      # the link survives; the price is a snapshot
