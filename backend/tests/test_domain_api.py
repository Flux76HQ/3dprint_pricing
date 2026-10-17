from decimal import Decimal

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


def test_project_stores_the_vat_rate_and_totals(owner):
    p = make(owner, "/api/projects", {**sheet_payload(), "margin_pct": "50", "vat_pct": "21"})
    assert p["vat_pct"] == "21.00"
    assert p["totals"]["vat_amount"] == "0.86" and p["totals"]["sell_price_incl_vat"] == "4.97"
    assert owner.get("/api/projects").get_json()[0]["vat_pct"] == "21.00"
    again = owner.put(f"/api/projects/{p['id']}", json={**sheet_payload(), "margin_pct": "50", "vat_pct": "9"}, headers=H)
    assert again.get_json()["totals"]["sell_price_incl_vat"] == "4.48"       # 4.11 + 0.37
    assert make(owner, "/api/projects", sheet_payload())["vat_pct"] == "0.00"  # omitted = no VAT


@pytest.mark.parametrize("vat", ["-1", "101", "abc"])
def test_project_rejects_a_bad_vat_rate(owner, vat):
    assert owner.post("/api/projects", json={**sheet_payload(), "vat_pct": vat}, headers=H).status_code == 400


def test_calculate_endpoint_returns_vat(owner):
    res = post(owner, "/api/calculate", {**sheet_payload(), "margin_pct": 50, "vat_pct": 21}).get_json()
    assert res["sell_price_incl_vat"] == "4.97"


def test_default_vat_preference(owner):
    assert owner.put("/api/preferences", json={"vat_pct": "21"}, headers=H).get_json()["vat_pct"] == "21"
    assert owner.put("/api/preferences", json={"vat_pct": "150"}, headers=H).status_code == 400
    assert owner.put("/api/preferences", json={"vat_pct": "x"}, headers=H).status_code == 400


def test_project_stores_the_price_rounding_and_reports_the_effective_margin(owner):
    body = {**sheet_payload(), "margin_pct": "50", "vat_pct": "21", "price_rounding": "0.50"}
    p = make(owner, "/api/projects", body)
    assert p["price_rounding"] == "0.50" and p["margin_pct"] == "50.00"
    t = p["totals"]
    assert t["sell_price_incl_vat"] == "5.00" and t["margin_pct_effective"] == "50.73"
    assert owner.get("/api/projects").get_json()[0]["price_rounding"] == "0.50"
    assert make(owner, "/api/projects", sheet_payload())["price_rounding"] == "none"


def test_bad_rounding_is_refused_and_a_default_can_be_saved(owner):
    assert owner.post("/api/projects", json={**sheet_payload(), "price_rounding": "0.07"}, headers=H).status_code == 400
    assert post(owner, "/api/calculate", {**sheet_payload(), "price_rounding": "x"}).status_code == 400
    assert owner.put("/api/preferences", json={"price_rounding": "x.95"}, headers=H).get_json()["price_rounding"] == "x.95"
    assert owner.put("/api/preferences", json={"price_rounding": "7"}, headers=H).status_code == 400


def test_display_preferences_are_validated_booleans(owner):
    res = owner.put("/api/preferences", json={"blur_costs": True, "auto_adopt_file": False}, headers=H).get_json()
    assert res["blur_costs"] is True and res["auto_adopt_file"] is False
    assert owner.put("/api/preferences", json={"blur_costs": "yes"}, headers=H).status_code == 400
    assert owner.put("/api/preferences", json={"auto_adopt_file": 1}, headers=H).status_code == 400


def test_version_endpoint_reports_the_short_commit(client, monkeypatch):
    monkeypatch.setenv("APP_COMMIT", "0123456789abcdef")
    body = client.get("/api/version").get_json()
    assert body["commit"] == "0123456" and body["version"]
    assert client.get("/healthz").get_json()["commit"] == "0123456"
    monkeypatch.delenv("APP_COMMIT")
    assert client.get("/api/version").get_json()["commit"] == "dev"      # local runs say so


def test_static_files_are_always_revalidated_so_updates_show_at_once(client):
    for path in ("/app.js", "/", "/instellingen"):
        res = client.get(path)
        assert res.status_code == 200
        assert "no-cache" in res.headers["Cache-Control"] and "max-age=3600" not in res.headers["Cache-Control"]
    first = client.get("/app.js")
    assert client.get("/app.js", headers={"If-None-Match": first.headers["ETag"]}).status_code == 304


def test_spool_details_barcode_diameter_and_temperatures(owner):
    s = make(owner, "/api/spools", {"brand": "Bambu ABS", "roll_weight_g": 1000, "price": 26.99, "remaining_g": 1000,
                                    "barcode": " 6975337030001 ", "diameter_mm": "1.75", "print_temp_c": "250", "bed_temp_c": "90"})
    assert s["barcode"] == "6975337030001" and s["diameter_mm"] == "1.75"
    assert (s["print_temp_c"], s["bed_temp_c"]) == (250, 90)
    plain = make(owner, "/api/spools", {"brand": "x", "roll_weight_g": 1000, "price": 1, "remaining_g": 1000})
    assert plain["barcode"] == "" and plain["diameter_mm"] == "1.75" and plain["print_temp_c"] is None
    cleared = owner.patch(f"/api/spools/{s['id']}", json={"print_temp_c": "", "bed_temp_c": None, "diameter_mm": "2.85"}, headers=H)
    assert cleared.get_json()["print_temp_c"] is None and cleared.get_json()["bed_temp_c"] is None
    assert cleared.get_json()["diameter_mm"] == "2.85"


@pytest.mark.parametrize("field, value", [("print_temp_c", "600"), ("print_temp_c", "abc"), ("print_temp_c", "215.5"),
                                          ("bed_temp_c", "-5"), ("bed_temp_c", "250"), ("diameter_mm", "0"),
                                          ("diameter_mm", "9"), ("barcode", "x" * 101)])
def test_spool_details_are_validated(owner, field, value):
    body = {"brand": "x", "roll_weight_g": 1000, "price": 1, "remaining_g": 1000, field: value}
    assert owner.post("/api/spools", json=body, headers=H).status_code == 400


def test_barcode_lookup_returns_the_newest_roll_with_that_barcode(owner):
    base = {"roll_weight_g": 1000, "price": 20, "remaining_g": 0, "barcode": "8719"}
    make(owner, "/api/spools", {**base, "brand": "Oud", "price": 20})
    make(owner, "/api/spools", {**base, "brand": "Nieuw", "price": 22})
    make(owner, "/api/spools", {**base, "brand": "Ander", "barcode": "1234"})
    assert owner.get("/api/spools/lookup?barcode=8719").get_json()["spool"]["brand"] == "Nieuw"
    assert owner.get("/api/spools/lookup?barcode=%208719%20").get_json()["spool"]["brand"] == "Nieuw"   # scanner whitespace
    assert owner.get("/api/spools/lookup?barcode=0000").get_json() == {"spool": None, "stock": None}
    assert owner.get("/api/spools/lookup").get_json() == {"spool": None, "stock": None}      # empty never matches the "no barcode" rolls
    assert owner.get("/api/spools").status_code == 200                            # the list route is unaffected


# --- stock per kind of filament -------------------------------------------------------------------------------

def roll(owner, remaining, **extra):
    body = {"brand": "Bambu PLA Basic", "material": "PLA", "colour": "Black", "roll_weight_g": 1000, "price": 20,
            "remaining_g": remaining, **extra}
    return make(owner, "/api/spools", body)


def test_stock_counts_the_rolls_you_still_have_with_their_weights_and_the_total(owner):
    roll(owner, 1000, barcode="111")
    roll(owner, 250, barcode="111")
    roll(owner, 0, barcode="111")                                          # empty: not a roll you still have
    gone = roll(owner, 700, barcode="111")
    owner.patch(f"/api/spools/{gone['id']}", json={"archived": True}, headers=H)       # archived: not stock
    stock = owner.get("/api/spools/stock").get_json()
    (group,) = stock["groups"]
    assert group["roll_count"] == 2 and Decimal(group["remaining_g"]) == 1250
    assert sorted(Decimal(r["remaining_g"]) for r in group["rolls"]) == [250, 1000]
    assert all(r["roll_weight_g"] == "1000.0" for r in group["rolls"])


def test_stock_groups_by_barcode_or_by_name_and_totals_per_material(owner):
    roll(owner, 800, barcode="111")
    roll(owner, 200, barcode="111", colour="Zwart")                        # same barcode = same kind, whatever it was typed as
    roll(owner, 500, colour="White")                                       # no barcode: grouped by brand + material + colour
    roll(owner, 400, colour="white")                                       # ... case does not matter
    roll(owner, 900, brand="Bambu ABS", material="ABS", colour="Black")
    roll(owner, 100, colour="Grey", material="pla")                        # the material's case does not matter either
    stock = owner.get("/api/spools/stock").get_json()
    by = {(g["material"], g["colour"].lower(), bool(g["barcode"])): g for g in stock["groups"]}
    assert Decimal(by[("PLA", "black", True)]["remaining_g"]) == 1000 and by[("PLA", "black", True)]["roll_count"] == 2
    assert Decimal(by[("PLA", "white", False)]["remaining_g"]) == 900 and by[("PLA", "white", False)]["roll_count"] == 2
    materials = {m["material"]: (m["roll_count"], Decimal(m["remaining_g"])) for m in stock["materials"]}
    assert materials == {"ABS": (1, 900), "PLA": (5, 2000)}


def test_a_sold_out_kind_stays_in_the_list_with_zero(owner):
    roll(owner, 0, colour="Red")
    (group,) = owner.get("/api/spools/stock").get_json()["groups"]
    assert group["roll_count"] == 0 and Decimal(group["remaining_g"]) == 0


def test_the_barcode_lookup_includes_what_is_in_stock_of_it(owner):
    roll(owner, 1000, barcode="999")
    roll(owner, 300, barcode="999")
    found = owner.get("/api/spools/lookup?barcode=999").get_json()
    assert found["spool"]["brand"] == "Bambu PLA Basic" and found["stock"]["roll_count"] == 2
    assert Decimal(found["stock"]["remaining_g"]) == 1300
    unknown = owner.get("/api/spools/lookup?barcode=000").get_json()
    assert unknown == {"spool": None, "stock": None}
    assert owner.get("/api/spools/lookup").get_json() == {"spool": None, "stock": None}


def test_stock_needs_a_session(client):
    assert client.get("/api/spools/stock").status_code == 401


# --- brand and type are separate ----------------------------------------------------------------------------

def test_a_roll_has_a_brand_and_a_separate_type_that_may_stay_empty(owner):
    matte = roll(owner, 1000, brand="Bambu Lab", product_type=" Matte ")
    assert matte["brand"] == "Bambu Lab" and matte["product_type"] == "Matte"
    assert roll(owner, 1000)["product_type"] == ""
    changed = owner.patch(f"/api/spools/{matte['id']}", json={"product_type": "Silk"}, headers=H).get_json()
    assert changed["product_type"] == "Silk" and changed["brand"] == "Bambu Lab"
    assert owner.post("/api/spools", json={"brand": "x", "roll_weight_g": 1000, "price": 1, "remaining_g": 1,
                                           "product_type": "x" * 61}, headers=H).status_code == 400


def test_stock_keeps_types_of_one_brand_apart_and_a_lookup_carries_the_type(owner):
    roll(owner, 500, brand="Bambu Lab", product_type="Matte", barcode="")
    roll(owner, 700, brand="Bambu Lab", product_type="Basic", barcode="")
    roll(owner, 100, brand="Bambu Lab", product_type="matte", barcode="")                # case does not matter
    groups = owner.get("/api/spools/stock").get_json()["groups"]
    assert sorted((g["product_type"], Decimal(g["remaining_g"])) for g in groups) == [("Basic", 700), ("Matte", 600)]
    roll(owner, 900, brand="Bambu Lab", product_type="Silk", barcode="777")
    assert owner.get("/api/spools/lookup?barcode=777").get_json()["spool"]["product_type"] == "Silk"


# --- passing product details on to rolls with the same barcode -----------------------------------------------------------

def test_product_details_can_be_passed_on_to_rolls_with_the_same_barcode_but_never_price_or_what_is_left(owner):
    a = roll(owner, 1000, barcode="555", price=20, notes="first")
    b = roll(owner, 400, barcode="555", price=25, notes="second")
    other = roll(owner, 300, barcode="999")
    assert owner.get(f"/api/spools/{a['id']}/siblings").get_json() == {"count": 1}
    owner.patch(f"/api/spools/{a['id']}", json={"brand": "Bambu Lab", "product_type": "Matte", "diameter_mm": "2.85",
                                               "price": 99, "remaining_g": 1, "notes": "changed"}, headers=H)
    done = owner.post(f"/api/spools/{a['id']}/propagate", json={"fields": ["brand", "product_type", "diameter_mm"]}, headers=H)
    assert done.get_json() == {"updated": 1}
    rows = {r["id"]: r for r in owner.get("/api/spools").get_json()}
    assert (rows[b["id"]]["brand"], rows[b["id"]]["product_type"], rows[b["id"]]["diameter_mm"]) == ("Bambu Lab", "Matte", "2.85")
    assert (Decimal(rows[b["id"]]["price"]), Decimal(rows[b["id"]]["remaining_g"]), rows[b["id"]]["notes"]) == (25, 400, "second")
    assert rows[other["id"]]["brand"] == "Bambu PLA Basic" and rows[other["id"]]["diameter_mm"] == "1.75"     # another barcode: untouched


def test_passing_on_only_takes_known_product_fields_and_needs_a_barcode(owner):
    a = roll(owner, 1000, barcode="555")
    for bad in (None, [], ["price"], ["remaining_g"], ["brand", "notes"], "brand"):
        assert owner.post(f"/api/spools/{a['id']}/propagate", json={"fields": bad}, headers=H).status_code == 400
    plain = roll(owner, 1000)
    roll(owner, 500)
    assert owner.get(f"/api/spools/{plain['id']}/siblings").get_json() == {"count": 0}                      # no barcode: no siblings
    assert owner.post(f"/api/spools/{plain['id']}/propagate", json={"fields": ["brand"]}, headers=H).get_json() == {"updated": 0}
    assert owner.get("/api/spools/00000000-0000-0000-0000-000000000000/siblings").status_code == 404
    assert owner.post("/api/spools/00000000-0000-0000-0000-000000000000/propagate", json={"fields": ["brand"]}, headers=H).status_code == 404


def test_passing_on_needs_a_session(client):
    assert client.get("/api/spools/00000000-0000-0000-0000-000000000000/siblings").status_code == 401
    assert client.post("/api/spools/00000000-0000-0000-0000-000000000000/propagate", json={"fields": ["brand"]}, headers=H).status_code == 401
