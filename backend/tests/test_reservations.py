"""Filament that open orders reserve: worked out from the lines, never stored, and let go of when the order is sent or done."""
from decimal import Decimal

from tests.test_auth_api import H
from tests.test_domain_api import make, owner, sheet_payload      # noqa: F401  (fixture)
from tests.test_orders import line, new_order

ROLL = {"brand": "Bambu", "product_type": "PLA Basic", "material": "PLA", "colour": "Zwart", "roll_weight_g": 1000, "price": 20, "remaining_g": 500,
        "barcode": "1234567890"}


def roll(owner, **extra):
    return make(owner, "/api/spools", {**ROLL, **extra})


def model(owner, spool_id, grams=100, name="Vaas"):
    """A saved calculation that takes `grams` of this roll for one piece."""
    payload = sheet_payload(spool_id)
    payload["name"] = name
    payload["data"]["filament"][0]["grams"] = grams
    res = owner.post("/api/projects", json=payload, headers=H)
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def model_line(project, quantity=1, **extra):
    return line(project["name"], quantity, "10.00", "21", project_id=project["id"], **extra)


def kind(owner, spool_id):
    stock = owner.get("/api/spools/stock").get_json()["groups"]
    return [g for g in stock if spool_id in g["spool_ids"]][0]


def test_an_open_order_reserves_grams_per_piece_times_quantity(owner):
    r = roll(owner)
    p = model(owner, r["id"], grams=100)
    new_order(owner, [model_line(p, 3)])
    group = kind(owner, r["id"])
    assert Decimal(group["reserved_g"]) == 300 and Decimal(group["available_g"]) == 200 and Decimal(group["remaining_g"]) == 500


def test_nothing_is_booked_off_the_roll(owner):
    r = roll(owner)
    new_order(owner, [model_line(model(owner, r["id"]), 2)])
    assert [x for x in owner.get("/api/spools").get_json() if x["id"] == r["id"]][0]["remaining_g"] == "500.0"


def test_two_open_orders_add_up_and_both_statuses_reserve(owner):
    r = roll(owner)
    p = model(owner, r["id"], grams=50)
    new_order(owner, [model_line(p, 2)], status="nieuw")
    new_order(owner, [model_line(p, 4)], status="verwerkt")
    assert Decimal(kind(owner, r["id"])["reserved_g"]) == 300


def test_sent_or_done_orders_let_go(owner):
    r = roll(owner)
    p = model(owner, r["id"], grams=100)
    order = new_order(owner, [model_line(p, 2)])
    assert Decimal(kind(owner, r["id"])["reserved_g"]) == 200
    for status in ("verstuurd", "afgehandeld"):
        assert owner.patch(f"/api/orders/{order['id']}/status", json={"status": "verwerkt"}, headers=H).status_code == 200
        assert Decimal(kind(owner, r["id"])["reserved_g"]) == 200
        assert owner.patch(f"/api/orders/{order['id']}/status", json={"status": status}, headers=H).status_code == 200
        assert Decimal(kind(owner, r["id"])["reserved_g"]) == 0, status


def test_a_deleted_order_lets_go(owner):
    r = roll(owner)
    order = new_order(owner, [model_line(model(owner, r["id"]), 2)])
    assert owner.delete(f"/api/orders/{order['id']}", headers=H).status_code == 200
    assert Decimal(kind(owner, r["id"])["reserved_g"]) == 0


def test_loose_optional_and_packaging_lines_reserve_nothing(owner):
    r = roll(owner)
    p = model(owner, r["id"])
    new_order(owner, [line("Verzending", 1), model_line(p, 1, optional=True), model_line(p, 1, packaging=True)])
    assert Decimal(kind(owner, r["id"])["reserved_g"]) == 0


def test_rolls_of_one_kind_share_the_reservation(owner):
    a, b = roll(owner, remaining_g=100), roll(owner, remaining_g=250)         # the same barcode: one kind
    new_order(owner, [model_line(model(owner, a["id"], grams=120), 2)])
    group = kind(owner, b["id"])
    assert Decimal(group["remaining_g"]) == 350 and Decimal(group["reserved_g"]) == 240 and Decimal(group["available_g"]) == 110


def test_the_reservation_is_shared_by_the_refill_and_the_roll_with_spool_of_one_colour(owner):
    refill, spool = roll(owner, remaining_g=100, barcode="REFILL"), roll(owner, remaining_g=250, barcode="SPOOL")       # one filament, a barcode each
    new_order(owner, [model_line(model(owner, spool["id"], grams=120), 2)])             # the calculation names the roll that is not called by the kind's key
    for pick in (refill, spool):
        group = kind(owner, pick["id"])
        assert Decimal(group["remaining_g"]) == 350 and Decimal(group["reserved_g"]) == 240 and Decimal(group["available_g"]) == 110


def test_a_roll_of_another_colour_is_not_touched(owner):
    black = roll(owner)
    white = roll(owner, colour="Wit", barcode="999")
    new_order(owner, [model_line(model(owner, black["id"]), 1)])
    assert Decimal(kind(owner, white["id"])["reserved_g"]) == 0


def test_a_calculation_without_a_roll_reserves_nothing(owner):
    p = model(owner, None)
    new_order(owner, [model_line(p, 5)])
    assert all(Decimal(g["reserved_g"]) == 0 for g in owner.get("/api/spools/stock").get_json()["groups"])


def check(owner, lines, status="nieuw", order_id=None):
    res = owner.post("/api/orders/filament-check", json={"lines": lines, "status": status, "order_id": order_id}, headers=H)
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def test_the_check_says_what_is_short_next_to_other_orders(owner):
    r = roll(owner, remaining_g=500)
    p = model(owner, r["id"], grams=100)
    new_order(owner, [model_line(p, 3)])                                      # 300 g is held
    ok = check(owner, [model_line(p, 2)])                                      # 200 g more: exactly what is left
    assert ok["reserving"] is True and ok["short"] is False
    assert ok["kinds"][0]["need_g"] == "200.0" and ok["kinds"][0]["reserved_others_g"] == "300.0" and ok["kinds"][0]["short_g"] == "0.0"
    over = check(owner, [model_line(p, 3)])
    assert over["short"] is True and over["kinds"][0]["short_g"] == "100.0" and over["kinds"][0]["remaining_g"] == "500.0"


def test_the_check_leaves_the_order_being_edited_out_of_what_others_hold(owner):
    r = roll(owner, remaining_g=300)
    p = model(owner, r["id"], grams=100)
    order = new_order(owner, [model_line(p, 3)])
    assert check(owner, [model_line(p, 3)], order_id=order["id"])["short"] is False       # it does not compete with itself
    assert check(owner, [model_line(p, 3)])["short"] is True                              # a new one with the same lines would


def test_a_sent_order_reserves_nothing_and_is_never_short(owner):
    r = roll(owner, remaining_g=50)
    result = check(owner, [model_line(model(owner, r["id"], grams=100), 5)], status="verstuurd")
    assert result["reserving"] is False and result["short"] is False and result["kinds"][0]["short_g"] == "0.0"
    assert result["kinds"][0]["need_g"] == "500.0"


def test_the_check_refuses_a_bad_status_and_needs_a_session(owner, app):
    assert owner.post("/api/orders/filament-check", json={"lines": [], "status": "nope"}, headers=H).status_code == 400
    assert app.test_client().post("/api/orders/filament-check", json={"lines": []}, headers=H).status_code == 401
