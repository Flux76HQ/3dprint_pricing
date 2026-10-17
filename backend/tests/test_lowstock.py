"""The notification for a kind of filament that is nearly used up: the threshold setting, the per-roll choice that belongs to the
kind (rolls with one barcode count together), when a message is queued (and, just as important, when it is not), what it says,
and that it can never get in the way of saving a roll."""
import dataclasses
import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock

import pytest

from app import lowstock, push
from tests.test_auth_api import H, post
from tests.test_domain_api import make, sheet_payload
from tests.test_push import NIGHT, at, owner, pushapp, subscribe      # noqa: F401  (fixtures)


def settings(owner, **low):
    body = {"threshold_g": 500, "materials": {}, **low}
    res = owner.put("/api/preferences", json={"low_stock": body}, headers=H)
    assert res.status_code == 200, res.get_json()
    return res.get_json()["low_stock"]


def roll(owner, remaining, *, notify=True, material="PLA", colour="Black", barcode="", **extra):
    return make(owner, "/api/spools", {"brand": "Bambu", "material": material, "colour": colour, "barcode": barcode, "roll_weight_g": 1000,
                                       "price": 20, "remaining_g": remaining, "notify_low": notify, **extra})


def outbox(pushapp):
    with pushapp.extensions["pool"].connection() as conn:
        return conn.execute("SELECT kind, payload FROM push_outbox ORDER BY created_at").fetchall()


def clear_outbox(pushapp):
    with pushapp.extensions["pool"].connection() as conn:
        conn.execute("DELETE FROM push_outbox")


def alerts(pushapp):
    with pushapp.extensions["pool"].connection() as conn:
        return sorted(r["stock_key"] for r in conn.execute("SELECT stock_key FROM low_stock_alerts").fetchall())


def flags(owner):
    return {r["id"]: r["notify_low"] for r in owner.get("/api/spools").get_json()}


# --- the thresholds ---------------------------------------------------------------------------------------------

def test_the_thresholds_are_stored_with_material_names_in_lower_case(owner):
    saved = settings(owner, threshold_g="750", materials={" PETG ": "200", "pla": 0})
    assert saved == {"threshold_g": 750, "materials": {"petg": 200, "pla": 0}}
    assert owner.get("/api/preferences").get_json()["low_stock"] == saved


def test_without_thresholds_the_default_applies(owner):
    assert owner.put("/api/preferences", json={"low_stock": {}}, headers=H).get_json()["low_stock"] == {"threshold_g": 500, "materials": {}}


@pytest.mark.parametrize("bad", [
    None, "on", ["x"], {"threshold_g": -1}, {"threshold_g": "lots"}, {"threshold_g": 1.5}, {"threshold_g": ""}, {"threshold_g": 1_000_001},
    {"materials": ["PLA"]}, {"materials": {"": 100}}, {"materials": {"PLA": "x"}}, {"materials": {"PLA": None}},
    {"materials": {"x" * 41: 100}}, {"materials": {str(i): 1 for i in range(101)}},
])
def test_a_setting_that_makes_no_sense_is_refused(owner, bad):
    assert owner.put("/api/preferences", json={"low_stock": bad}, headers=H).status_code == 400


# --- the choice is made on the roll and belongs to the kind -------------------------------------------------------

def test_rolls_start_without_a_notification(owner):
    plain = make(owner, "/api/spools", {"brand": "x", "roll_weight_g": 1000, "price": 1, "remaining_g": 1})
    assert plain["notify_low"] is False


def test_the_choice_is_shared_by_every_roll_with_the_same_barcode(owner):
    a = roll(owner, 1000, barcode="8719", notify=True)
    b = make(owner, "/api/spools", {"brand": "Bambu", "material": "PLA", "barcode": "8719", "roll_weight_g": 1000, "price": 20,
                                    "remaining_g": 1000})                                  # says nothing: takes over what the kind has
    other = roll(owner, 1000, barcode="1234", notify=False)
    assert b["notify_low"] is True and flags(owner) == {a["id"]: True, b["id"]: True, other["id"]: False}
    owner.patch(f"/api/spools/{b['id']}", json={"notify_low": False}, headers=H)               # switched off on one roll: off for the kind
    assert flags(owner) == {a["id"]: False, b["id"]: False, other["id"]: False}
    owner.patch(f"/api/spools/{a['id']}", json={"notify_low": True}, headers=H)
    assert flags(owner) == {a["id"]: True, b["id"]: True, other["id"]: False}


def test_a_roll_that_says_it_explicitly_sets_it_for_its_kind(owner):
    a = roll(owner, 1000, barcode="8719", notify=True)
    b = roll(owner, 1000, barcode="8719", notify=False)                                      # a deliberate "no" for the whole kind
    assert flags(owner) == {a["id"]: False, b["id"]: False}


def test_without_a_barcode_the_same_brand_type_material_and_colour_are_one_kind(owner):
    a = roll(owner, 1000, notify=True)
    b = roll(owner, 1000, notify=False)
    white = roll(owner, 1000, colour="White", notify=True)
    assert flags(owner) == {a["id"]: False, b["id"]: False, white["id"]: True}


def test_editing_a_roll_without_the_field_leaves_the_choice_alone(owner):
    a = roll(owner, 1000, barcode="8719", notify=True)
    owner.patch(f"/api/spools/{a['id']}", json={"notes": "half used"}, headers=H)
    assert flags(owner) == {a["id"]: True}


# --- when a message is queued -----------------------------------------------------------------------------------

def test_a_watched_kind_dropping_to_the_threshold_queues_one_message_that_names_it(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    first = roll(owner, 900, barcode="8719")
    assert outbox(pushapp) == []                                          # plenty left
    owner.patch(f"/api/spools/{first['id']}", json={"remaining_g": 500}, headers=H)       # exactly at the threshold counts
    (queued,) = outbox(pushapp)
    assert queued["kind"] == lowstock.KIND == "low_stock"
    assert queued["payload"]["title"] == "Filament bijna op" and queued["payload"]["body"] == "Bijna op: Bambu Black (PLA): 500 g"
    assert queued["payload"]["url"] == "/#/filament" and queued["payload"]["silent"] is True


def test_a_kind_that_is_not_watched_is_never_announced(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    roll(owner, 10, barcode="8719", notify=False)
    assert outbox(pushapp) == [] and alerts(pushapp) == []


def test_the_rolls_of_one_barcode_count_together(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    rolls = [roll(owner, 1000, barcode="8719") for _ in range(3)]          # three rolls of 1 kg are one kind with 3 kg
    for spool in rolls:
        owner.patch(f"/api/spools/{spool['id']}", json={"remaining_g": 200}, headers=H)
    assert outbox(pushapp) == [] and alerts(pushapp) == []                # every roll is under 500 g, together they are 600 g
    owner.patch(f"/api/spools/{rolls[2]['id']}", json={"remaining_g": 100}, headers=H)       # 500 g together
    (queued,) = outbox(pushapp)
    assert queued["payload"]["body"] == "Bijna op: Bambu Black (PLA): 500 g" and alerts(pushapp) == ["barcode:8719"]


def test_kinds_with_other_barcodes_are_counted_apart(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    roll(owner, 300, barcode="1111")
    roll(owner, 300, barcode="2222", colour="White")                      # 600 g of PLA in total, but two kinds
    assert alerts(pushapp) == ["barcode:1111", "barcode:2222"]


def test_it_is_delivered_by_the_outbox_worker_on_the_usual_terms(owner, pushapp):
    subscribe(owner)
    cfg, pool = pushapp.config["APP_CONFIG"], pushapp.extensions["pool"]
    settings(owner, threshold_g=500)
    roll(owner, 100, barcode="8719")
    with mock.patch("app.push.webpush") as mocked:
        assert push.run_outbox_once(pool, cfg, now=datetime.now(timezone.utc)) == 1
    (call,) = mocked.call_args_list
    assert json.loads(call.kwargs["data"])["body"] == "Bijna op: Bambu Black (PLA): 100 g"
    assert call.kwargs["ttl"] == push.TTL_SECONDS and call.kwargs["headers"]["Topic"] == "low_stock"


def test_quiet_hours_hold_it_back_until_morning(owner, pushapp):
    subscribe(owner)
    cfg, pool = pushapp.config["APP_CONFIG"], pushapp.extensions["pool"]
    owner.put("/api/preferences", json={"quiet_hours": NIGHT}, headers=H)
    settings(owner, threshold_g=500)
    roll(owner, 100, barcode="8719")
    with mock.patch("app.push.webpush") as mocked:
        # the worker decides by the clock: it was queued "now", so move the row into the middle of a night first
        with pool.connection() as conn:
            conn.execute("UPDATE push_outbox SET deliver_after = %s", (at("2026-06-10 23:30"),))
        assert push.run_outbox_once(pool, cfg, now=at("2026-06-10 23:45")) == 0
        assert mocked.call_count == 0
        assert push.run_outbox_once(pool, cfg, now=at("2026-06-11 07:00")) == 1
    assert mocked.call_count == 1


def test_changing_a_roll_that_is_already_low_does_not_repeat_the_message(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    low = roll(owner, 100, barcode="8719")
    assert len(outbox(pushapp)) == 1 and alerts(pushapp) == ["barcode:8719"]
    clear_outbox(pushapp)
    owner.patch(f"/api/spools/{low['id']}", json={"remaining_g": 60}, headers=H)
    owner.patch(f"/api/spools/{low['id']}", json={"notes": "half used"}, headers=H)
    assert outbox(pushapp) == []


def test_it_is_announced_again_after_the_stock_was_back_above_the_threshold(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    roll(owner, 100, barcode="8719")
    clear_outbox(pushapp)
    new = roll(owner, 1000, barcode="8719")                               # a purchase: 1100 g in total
    assert outbox(pushapp) == [] and alerts(pushapp) == []                # recovered: forgotten
    owner.delete(f"/api/spools/{new['id']}", headers=H)                   # ... and gone again
    (queued,) = outbox(pushapp)
    assert queued["payload"]["body"] == "Bijna op: Bambu Black (PLA): 100 g"


def test_a_threshold_for_the_material_beats_the_default(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500, materials={"petg": 50})
    roll(owner, 200, barcode="1111", material="PETG")                      # 200 g is under the default but over PETG's own 50
    assert outbox(pushapp) == [] and alerts(pushapp) == []
    roll(owner, 200, barcode="2222", material="pla", colour="White")
    assert alerts(pushapp) == ["barcode:2222"]


def test_booking_a_print_can_run_a_kind_low(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    spool = make(owner, "/api/spools", {"brand": "ABS", "material": "ABS", "barcode": "8719", "roll_weight_g": 1000, "price": 20,
                                        "remaining_g": 560, "notify_low": True})
    project = make(owner, "/api/projects", sheet_payload(spool["id"]))
    assert outbox(pushapp) == []
    assert post(owner, f"/api/projects/{project['id']}/book-stock").status_code == 200       # 70 g used: 490 g left
    (queued,) = outbox(pushapp)
    assert queued["payload"]["body"] == "Bijna op: ABS: 490 g"


def test_switching_it_on_for_a_kind_that_is_low_announces_it_now_and_off_forgets_it(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    low = roll(owner, 100, barcode="8719", notify=False)
    assert outbox(pushapp) == []
    owner.patch(f"/api/spools/{low['id']}", json={"notify_low": True}, headers=H)
    assert len(outbox(pushapp)) == 1 and alerts(pushapp) == ["barcode:8719"]
    clear_outbox(pushapp)
    owner.patch(f"/api/spools/{low['id']}", json={"notify_low": False}, headers=H)
    assert alerts(pushapp) == [] and outbox(pushapp) == []
    owner.patch(f"/api/spools/{low['id']}", json={"notify_low": True}, headers=H)
    assert len(outbox(pushapp)) == 1


def test_raising_the_threshold_announces_what_is_under_it_now_once(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    roll(owner, 700, barcode="8719")
    assert outbox(pushapp) == []
    settings(owner, threshold_g=800)
    assert len(outbox(pushapp)) == 1
    clear_outbox(pushapp)
    settings(owner, threshold_g=900)                                       # still the same kind, already announced
    assert outbox(pushapp) == []


def test_several_kinds_running_low_are_listed_in_one_message_with_the_emptiest_first(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    roll(owner, 400, barcode="1111", colour="White")
    roll(owner, 100, barcode="2222", colour="Black", material="PETG")
    (queued,) = outbox(pushapp)
    assert queued["payload"]["body"] == "Bijna op: Bambu Black (PETG): 100 g, Bambu White (PLA): 400 g"
    assert alerts(pushapp) == ["barcode:1111", "barcode:2222"]


def test_archived_rolls_do_not_count_and_a_kind_without_rolls_is_forgotten(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    only = roll(owner, 100, barcode="8719")
    assert alerts(pushapp) == ["barcode:8719"]
    clear_outbox(pushapp)
    owner.patch(f"/api/spools/{only['id']}", json={"archived": True}, headers=H)
    assert alerts(pushapp) == [] and outbox(pushapp) == []
    roll(owner, 1000, barcode="8719")                                      # bought again: not low
    assert outbox(pushapp) == []


def test_passing_a_material_on_to_the_rolls_with_the_same_barcode_changes_which_threshold_applies(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500, materials={"pla": 100, "petg": 1000})
    roll(owner, 300, barcode="8719", material="PLA")                       # the kind is PLA: its own threshold is 100 g
    wrong = roll(owner, 0, barcode="8719", material="PETG")                # entered with another material
    assert alerts(pushapp) == []
    res = post(owner, f"/api/spools/{wrong['id']}/propagate", {"fields": ["material"]})
    assert res.status_code == 200 and res.get_json()["updated"] == 1
    assert alerts(pushapp) == ["barcode:8719"]                             # now PETG: 300 g is under 1000 g


# --- what the message says -------------------------------------------------------------------------------------

def group(brand, grams, **extra):
    return {"key": f"name:{brand}", "brand": brand, "product_type": "", "material": "PLA", "colour": "", "remaining_g": str(grams),
            "notify_low": True, **extra}


def test_a_name_has_brand_type_and_colour_and_the_material_only_when_it_is_not_in_there_already():
    assert lowstock.kind_name(group("Bambu Lab", 1, product_type="Matte", colour="Zwart")) == "Bambu Lab Matte Zwart (PLA)"
    assert lowstock.kind_name(group("Bambu PLA Basic", 1, colour="Zwart")) == "Bambu PLA Basic Zwart"
    assert lowstock.kind_name(group("Sunlu", 1, material="")) == "Sunlu"


def test_a_long_list_is_cut_short_with_the_emptiest_first():
    low = {b: group(b, grams, material="") for b, grams in (("A", 400), ("B", 90), ("C", 250), ("D", 10), ("E", 300), ("F", 20))}
    title, body = lowstock.build_message("nl", low)
    assert title == "Filament bijna op"
    assert body == "Bijna op: D: 10 g, F: 20 g, B: 90 g, C: 250 g en 2 andere soorten"
    assert lowstock.build_message("en", low)[1].endswith("and 2 other materials")
    assert lowstock.build_message("en", {k: v for k, v in list(low.items())[:5]})[1].endswith("and 1 other material")


def test_the_message_follows_the_language_saved_with_the_account(owner, pushapp):
    subscribe(owner)
    owner.put("/api/preferences", json={"language": "en"}, headers=H)
    settings(owner, threshold_g=500)
    owner.post("/api/spools", json={"brand": "x", "material": "", "barcode": "8719", "roll_weight_g": 1000, "price": 1, "remaining_g": 100,
                                    "notify_low": True}, headers={**H, "X-Lang": "nl"})
    (queued,) = outbox(pushapp)
    assert queued["payload"]["title"] == "Filament running low" and queued["payload"]["body"] == "Running low: x: 100 g"


# --- what must not happen -------------------------------------------------------------------------------------

def test_nothing_is_queued_without_push_but_the_roll_is_still_saved(owner, pushapp):
    settings(owner, threshold_g=500)
    cfg = dataclasses.replace(pushapp.config["APP_CONFIG"], vapid_public_key="", vapid_private_key="")
    roll(owner, 100, barcode="8719")
    clear_outbox(pushapp)
    assert lowstock.check(pushapp.extensions["pool"], cfg) == 0 and outbox(pushapp) == []


def test_a_failing_check_never_turns_saving_a_roll_into_an_error(owner, pushapp):
    settings(owner, threshold_g=500)
    with mock.patch("app.lowstock.stock.groups", side_effect=RuntimeError("database hiccup")):
        res = owner.post("/api/spools", json={"brand": "x", "roll_weight_g": 1000, "price": 1, "remaining_g": 100, "notify_low": True},
                         headers=H)
    assert res.status_code == 201


def test_two_checks_at_once_announce_a_kind_only_once(owner, pushapp):
    subscribe(owner)
    cfg, pool = pushapp.config["APP_CONFIG"], pushapp.extensions["pool"]
    settings(owner, threshold_g=500)
    roll(owner, 100, barcode="8719")
    clear_outbox(pushapp)
    with pool.connection() as conn:
        conn.execute("DELETE FROM low_stock_alerts")                       # as if neither worker had seen it yet
    assert lowstock.check(pool, cfg) == 1
    assert lowstock.check(pool, cfg) == 0


# --- the stock overview and backups --------------------------------------------------------------------------

def test_the_stock_overview_says_which_kinds_are_watched_and_which_of_those_are_low(owner, pushapp):
    roll(owner, 100, barcode="1111")
    roll(owner, 700, barcode="2222", colour="White", material="PETG")
    roll(owner, 10, barcode="3333", colour="Red", notify=False)
    settings(owner, threshold_g=500, materials={"petg": 800})
    stock = owner.get("/api/spools/stock").get_json()
    by = {g["barcode"]: g for g in stock["groups"]}
    assert (by["1111"]["notify_low"], by["1111"]["threshold_g"], by["1111"]["low"]) == (True, 500, True)
    assert (by["2222"]["notify_low"], by["2222"]["threshold_g"], by["2222"]["low"]) == (True, 800, True)
    assert (by["3333"]["notify_low"], by["3333"]["threshold_g"], by["3333"]["low"]) == (False, None, False)
    materials = {m["key"]: m for m in stock["materials"]}
    assert set(materials) == {"pla", "petg"} and Decimal(materials["pla"]["remaining_g"]) == 110


def test_a_barcode_lookup_carries_the_choice_of_the_kind(owner):
    roll(owner, 100, barcode="8719", notify=True)
    found = owner.get("/api/spools/lookup?barcode=8719").get_json()
    assert found["spool"]["notify_low"] is True and found["stock"]["notify_low"] is True


def test_a_backup_carries_the_choice_and_restoring_it_checks_the_shelf(owner, pushapp):
    subscribe(owner)
    roll(owner, 100, barcode="8719")
    settings(owner, threshold_g=500)
    backup = owner.get("/api/backup").get_json()
    assert backup["preferences"]["low_stock"]["threshold_g"] == 500
    assert [s["notify_low"] for s in backup["spools"]] == [True]
    clear_outbox(pushapp)
    with pushapp.extensions["pool"].connection() as conn:
        conn.execute("DELETE FROM low_stock_alerts")
    assert owner.post("/api/backup/restore", json=backup, headers=H).status_code == 200
    assert len(outbox(pushapp)) == 1
    assert all(flags(owner).values())
