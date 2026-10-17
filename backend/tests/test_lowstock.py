"""The notification for a material that is nearly used up: the threshold setting, when a message is queued (and,
just as important, when it is not), what it says, and that it can never get in the way of saving a roll."""
import dataclasses
import json
from datetime import datetime, timezone
from unittest import mock

import pytest

from app import lowstock, push
from tests.test_auth_api import H, post
from tests.test_domain_api import make, sheet_payload
from tests.test_push import NIGHT, at, owner, pushapp, subscribe      # noqa: F401  (fixtures)


def settings(owner, **low):
    body = {"enabled": True, "threshold_g": 500, "materials": {}, **low}
    res = owner.put("/api/preferences", json={"low_stock": body}, headers=H)
    assert res.status_code == 200, res.get_json()
    return res.get_json()["low_stock"]


def roll(owner, remaining, material="PLA", **extra):
    return make(owner, "/api/spools", {"brand": "Bambu", "material": material, "colour": "Black", "roll_weight_g": 1000,
                                       "price": 20, "remaining_g": remaining, **extra})


def outbox(pushapp):
    with pushapp.extensions["pool"].connection() as conn:
        return conn.execute("SELECT kind, payload FROM push_outbox ORDER BY created_at").fetchall()


def clear_outbox(pushapp):
    with pushapp.extensions["pool"].connection() as conn:
        conn.execute("DELETE FROM push_outbox")


def alerts(pushapp):
    with pushapp.extensions["pool"].connection() as conn:
        return sorted(r["material"] for r in conn.execute("SELECT material FROM low_stock_alerts").fetchall())


# --- the setting ----------------------------------------------------------------------------------------------

def test_the_setting_is_stored_with_material_names_in_lower_case(owner):
    saved = settings(owner, threshold_g="750", materials={" PETG ": "200", "pla": 0})
    assert saved == {"enabled": True, "threshold_g": 750, "materials": {"petg": 200, "pla": 0}}
    assert owner.get("/api/preferences").get_json()["low_stock"] == saved


@pytest.mark.parametrize("bad", [
    None, "on", {}, {"enabled": "yes"}, {"enabled": True, "threshold_g": -1}, {"enabled": True, "threshold_g": "lots"},
    {"enabled": True, "threshold_g": 1.5}, {"enabled": True, "threshold_g": ""}, {"enabled": True, "threshold_g": 1_000_001},
    {"enabled": True, "materials": ["PLA"]}, {"enabled": True, "materials": {"": 100}}, {"enabled": True, "materials": {"PLA": "x"}},
    {"enabled": True, "materials": {"PLA": None}}, {"enabled": True, "materials": {"x" * 41: 100}},
    {"enabled": True, "materials": {str(i): 1 for i in range(101)}},
])
def test_a_setting_that_makes_no_sense_is_refused(owner, bad):
    assert owner.put("/api/preferences", json={"low_stock": bad}, headers=H).status_code == 400


# --- when a message is queued -----------------------------------------------------------------------------------

def test_a_material_dropping_to_the_threshold_queues_one_message_that_names_it(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    first = roll(owner, 900)
    assert outbox(pushapp) == []                                          # plenty left
    owner.patch(f"/api/spools/{first['id']}", json={"remaining_g": 500}, headers=H)       # exactly at the threshold counts
    (queued,) = outbox(pushapp)
    assert queued["kind"] == lowstock.KIND == "low_stock"
    assert queued["payload"]["title"] == "Filament bijna op" and queued["payload"]["body"] == "Bijna op: PLA: 500 g"
    assert queued["payload"]["url"] == "/#/filament" and queued["payload"]["silent"] is True


def test_it_is_delivered_by_the_outbox_worker_on_the_usual_terms(owner, pushapp):
    subscribe(owner)
    cfg, pool = pushapp.config["APP_CONFIG"], pushapp.extensions["pool"]
    settings(owner, threshold_g=500)
    roll(owner, 100)
    with mock.patch("app.push.webpush") as mocked:
        assert push.run_outbox_once(pool, cfg, now=datetime.now(timezone.utc)) == 1
    (call,) = mocked.call_args_list
    assert json.loads(call.kwargs["data"])["body"] == "Bijna op: PLA: 100 g"
    assert call.kwargs["ttl"] == push.TTL_SECONDS and call.kwargs["headers"]["Topic"] == "low_stock"


def test_quiet_hours_hold_it_back_until_morning(owner, pushapp):
    subscribe(owner)
    cfg, pool = pushapp.config["APP_CONFIG"], pushapp.extensions["pool"]
    owner.put("/api/preferences", json={"quiet_hours": NIGHT}, headers=H)
    settings(owner, threshold_g=500)
    roll(owner, 100)
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
    low = roll(owner, 100)
    assert len(outbox(pushapp)) == 1 and alerts(pushapp) == ["pla"]
    clear_outbox(pushapp)
    owner.patch(f"/api/spools/{low['id']}", json={"remaining_g": 60}, headers=H)
    owner.patch(f"/api/spools/{low['id']}", json={"notes": "half used"}, headers=H)
    assert outbox(pushapp) == []


def test_it_is_announced_again_after_the_stock_was_back_above_the_threshold(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    roll(owner, 100)
    clear_outbox(pushapp)
    new = roll(owner, 1000)                                               # a purchase: 1100 g in total
    assert outbox(pushapp) == [] and alerts(pushapp) == []                # recovered: forgotten
    owner.delete(f"/api/spools/{new['id']}", headers=H)                   # ... and gone again
    (queued,) = outbox(pushapp)
    assert queued["payload"]["body"] == "Bijna op: PLA: 100 g"


def test_the_totals_of_all_rolls_of_a_material_count_not_the_roll(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    roll(owner, 300)
    assert outbox(pushapp) != [] and alerts(pushapp) == ["pla"]
    clear_outbox(pushapp)
    roll(owner, 300, colour="White")                                      # 600 g of PLA in total: not low any more
    assert alerts(pushapp) == []


def test_a_threshold_of_its_own_beats_the_default(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500, materials={"petg": 50})
    roll(owner, 200, material="PETG")                                      # 200 g is under the default but over PETG's own 50
    assert outbox(pushapp) == [] and alerts(pushapp) == []
    roll(owner, 200, material="pla")
    assert alerts(pushapp) == ["pla"]


def test_booking_a_print_can_run_a_material_low(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    spool = make(owner, "/api/spools", {"brand": "ABS", "material": "ABS", "roll_weight_g": 1000, "price": 20, "remaining_g": 560})
    project = make(owner, "/api/projects", sheet_payload(spool["id"]))
    assert outbox(pushapp) == []
    assert post(owner, f"/api/projects/{project['id']}/book-stock").status_code == 200       # 70 g used: 490 g left
    (queued,) = outbox(pushapp)
    assert queued["payload"]["body"] == "Bijna op: ABS: 490 g"


def test_switching_it_on_announces_what_is_low_at_that_moment_once(owner, pushapp):
    subscribe(owner)
    roll(owner, 100)
    roll(owner, 100, material="PETG")
    assert outbox(pushapp) == []                                          # off: nothing is watched
    settings(owner, threshold_g=500)
    (queued,) = outbox(pushapp)
    assert queued["payload"]["body"] == "Bijna op: PETG: 100 g, PLA: 100 g" and alerts(pushapp) == ["petg", "pla"]
    clear_outbox(pushapp)
    settings(owner, threshold_g=600)                                       # saving again changes nothing: both known already
    assert outbox(pushapp) == []


def test_switching_it_off_forgets_so_switching_on_again_tells_you_again(owner, pushapp):
    subscribe(owner)
    roll(owner, 100)
    settings(owner, threshold_g=500)
    clear_outbox(pushapp)
    settings(owner, enabled=False)
    assert alerts(pushapp) == [] and outbox(pushapp) == []
    settings(owner, threshold_g=500)
    assert len(outbox(pushapp)) == 1


def test_rolls_without_a_material_and_archived_rolls_are_not_followed(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=500)
    roll(owner, 10, material="")
    archived = roll(owner, 10)
    assert alerts(pushapp) == ["pla"]
    clear_outbox(pushapp)
    roll(owner, 1000, colour="White")
    owner.patch(f"/api/spools/{archived['id']}", json={"archived": True}, headers=H)
    assert outbox(pushapp) == [] and alerts(pushapp) == []


def test_passing_a_material_on_to_the_rolls_with_the_same_barcode_moves_their_grams_to_that_total(owner, pushapp):
    subscribe(owner)
    settings(owner, threshold_g=400)
    mine = roll(owner, 300, material="PLA", barcode="8719")
    roll(owner, 700, material="PETG", barcode="8719")                      # entered with the wrong material
    assert alerts(pushapp) == ["pla"]                                      # 300 g of PLA is low, 700 g of PETG is not
    res = post(owner, f"/api/spools/{mine['id']}/propagate", {"fields": ["material"]})
    assert res.status_code == 200 and res.get_json()["updated"] == 1
    assert alerts(pushapp) == []                                           # now 1000 g of PLA: recovered, and noticed


# --- what the message says -------------------------------------------------------------------------------------

def test_a_long_list_is_cut_short_with_the_emptiest_first():
    low = {name.lower(): {"name": name, "rolls": 1, "grams": grams}
           for name, grams in (("PLA", 400), ("PETG", 90), ("ABS", 250), ("TPU", 10), ("ASA", 300), ("PA", 20))}
    title, body = lowstock.build_message("nl", low)
    assert title == "Filament bijna op"
    assert body == "Bijna op: TPU: 10 g, PA: 20 g, PETG: 90 g, ABS: 250 g en 2 andere soorten"
    assert lowstock.build_message("en", low)[1].endswith("and 2 other materials")
    one_more = {k: v for k, v in list(low.items())[:5]}
    assert lowstock.build_message("en", one_more)[1].endswith("and 1 other material")


def test_the_message_follows_the_language_saved_with_the_account(owner, pushapp):
    subscribe(owner)
    owner.put("/api/preferences", json={"language": "en"}, headers=H)
    settings(owner, threshold_g=500)
    owner.post("/api/spools", json={"brand": "x", "material": "PLA", "roll_weight_g": 1000, "price": 1, "remaining_g": 100},
               headers={**H, "X-Lang": "nl"})
    (queued,) = outbox(pushapp)
    assert queued["payload"]["title"] == "Filament running low" and queued["payload"]["body"] == "Running low: PLA: 100 g"


# --- what must not happen -------------------------------------------------------------------------------------

def test_nothing_is_queued_without_push_but_the_roll_is_still_saved(owner, pushapp):
    settings(owner, threshold_g=500)
    cfg = dataclasses.replace(pushapp.config["APP_CONFIG"], vapid_public_key="", vapid_private_key="")
    roll(owner, 100)
    clear_outbox(pushapp)
    assert lowstock.check(pushapp.extensions["pool"], cfg) == 0 and outbox(pushapp) == []


def test_a_failing_check_never_turns_saving_a_roll_into_an_error(owner, pushapp):
    settings(owner, threshold_g=500)
    with mock.patch("app.lowstock.totals", side_effect=RuntimeError("database hiccup")):
        res = owner.post("/api/spools", json={"brand": "x", "material": "PLA", "roll_weight_g": 1000, "price": 1,
                                              "remaining_g": 100}, headers=H)
    assert res.status_code == 201


def test_two_checks_at_once_announce_a_material_only_once(owner, pushapp):
    subscribe(owner)
    cfg, pool = pushapp.config["APP_CONFIG"], pushapp.extensions["pool"]
    settings(owner, threshold_g=500)
    roll(owner, 100)
    clear_outbox(pushapp)
    with pool.connection() as conn:
        conn.execute("DELETE FROM low_stock_alerts")                       # as if neither worker had seen it yet
    assert lowstock.check(pool, cfg) == 1
    assert lowstock.check(pool, cfg) == 0


# --- the stock overview ----------------------------------------------------------------------------------------

def test_the_stock_overview_says_which_materials_are_low(owner, pushapp):
    roll(owner, 100)
    roll(owner, 700, material="PETG")
    roll(owner, 10, material="")
    plain = owner.get("/api/spools/stock").get_json()["materials"]
    assert all(m["low"] is False and m["threshold_g"] is None for m in plain)           # off: nothing is flagged
    settings(owner, threshold_g=500, materials={"petg": 800})
    by = {m["key"]: m for m in owner.get("/api/spools/stock").get_json()["materials"]}
    assert (by["pla"]["low"], by["pla"]["threshold_g"]) == (True, 500)
    assert (by["petg"]["low"], by["petg"]["threshold_g"]) == (True, 800)
    assert by[""]["low"] is False and by[""]["threshold_g"] is None                     # no material: not followed


def test_a_backup_carries_the_setting_and_restoring_it_checks_the_shelf(owner, pushapp):
    subscribe(owner)
    roll(owner, 100)
    settings(owner, threshold_g=500)
    backup = owner.get("/api/backup").get_json()
    assert backup["preferences"]["low_stock"]["threshold_g"] == 500
    clear_outbox(pushapp)
    with pushapp.extensions["pool"].connection() as conn:
        conn.execute("DELETE FROM low_stock_alerts")
    assert owner.post("/api/backup/restore", json=backup, headers=H).status_code == 200
    assert len(outbox(pushapp)) == 1
