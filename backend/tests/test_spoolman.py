"""Spoolman as the source of the rolls: the sync, what a mirrored roll may and may not do, and reporting booked filament back."""
import dataclasses

import pytest
import requests

from app import config as config_module
from app.config import ConfigError
from tests.test_auth_api import H, post
from tests.test_domain_api import make, owner, sheet_payload  # noqa: F401  (fixture)
from tests.test_users import join_with_passkey, sql

URL = "http://spoolman.test:7912"
NL = {"X-Lang": "nl"}


def spool(number, *, vendor="Bambu Lab", name="Zwart", material="PLA", remaining=800.0, initial=1000.0, price=19.5, archived=False, **filament):
    return {"id": number, "archived": archived, "price": price, "remaining_weight": remaining, "initial_weight": initial, "used_weight": 0,
            "comment": "", "filament": {"id": number, "name": name, "material": material, "vendor": {"name": vendor}, "diameter": 1.75,
                                       "color_hex": "1A1A1A", "article_number": f"EAN-{number}", "settings_extruder_temp": 220,
                                       "settings_bed_temp": 55, **filament}}


class Reply:
    def __init__(self, status=200, body=b"[]"):
        self.status_code, self.body = status, body

    def iter_content(self, size):
        yield self.body

    def close(self):
        pass


class Spoolman:
    """A stand-in for the Spoolman server: it holds spools, answers the pages, and takes the use calls. A test never reaches a real one."""

    def __init__(self):
        self.vendors, self.filaments, self.created = [], [], []
        self.spools, self.used, self.down, self.answer, self.no_use = [], [], False, None, False

    def request(self, method, url, params=None, json=None, **kwargs):
        import json as jsonlib
        assert url.startswith(URL + "/api/v1/") and kwargs["allow_redirects"] is False and kwargs["timeout"]
        if self.down:
            raise requests.ConnectionError("down")
        if self.answer:
            return self.answer
        path = url[len(URL + "/api/v1"):]
        if method == "GET" and path == "/spool":
            assert params["allow_archived"] == "true"
            page = self.spools[params["offset"]:params["offset"] + params["limit"]]
            return Reply(body=jsonlib.dumps(page).encode())
        if method == "GET" and path in ("/vendor", "/filament"):
            items = self.vendors if path == "/vendor" else self.filaments
            return Reply(body=jsonlib.dumps(items[params["offset"]:params["offset"] + params["limit"]]).encode())
        if method == "POST" and path in ("/vendor", "/filament"):
            made = {"id": 100 + len(self.created), **json}
            self.created.append((path, json))
            if path == "/vendor":
                self.vendors.append(made)
            else:
                vendor = next(v for v in self.vendors if v["id"] == json["vendor_id"])
                self.filaments.append({**made, "vendor": vendor})
            return Reply(body=jsonlib.dumps(made).encode())
        if method == "PUT" and path.endswith("/use"):
            if self.no_use:
                raise requests.ConnectionError("down")
            number = int(path.split("/")[2])
            if number not in {s["id"] for s in self.spools}:
                return Reply(404, b"{}")
            self.used.append((number, json["use_weight"]))
            return Reply(body=b"{}")
        raise AssertionError((method, path))


@pytest.fixture
def server(app, monkeypatch):
    fake = Spoolman()
    monkeypatch.setattr(requests, "request", fake.request)
    app.config["APP_CONFIG"] = dataclasses.replace(app.config["APP_CONFIG"], spoolman_url=URL)
    return fake


def sync(owner):
    return owner.post("/api/spoolman/sync", json={}, headers=H)


def rolls(owner):
    return {r["spoolman_id"]: r for r in owner.get("/api/spools").get_json() if r["spoolman_id"]}


# --- configuration -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [("", ""), ("http://spoolman:8000", "http://spoolman:8000"), (" https://s.example.org/ ", "https://s.example.org")])
def test_the_address_is_read_from_the_environment(monkeypatch, value, expected):
    monkeypatch.setenv("SPOOLMAN_URL", value)
    assert config_module._spoolman_url() == expected


@pytest.mark.parametrize("value", ["spoolman:8000", "ftp://spoolman", "http://user:pw@spoolman:8000", "http://spoolman:8000?x=1", "http://"])
def test_an_address_that_is_not_plain_http_or_https_is_refused(monkeypatch, value):
    monkeypatch.setenv("SPOOLMAN_URL", value)
    with pytest.raises(ConfigError):
        config_module._spoolman_url()


def test_without_an_address_there_is_no_spoolman(owner):
    assert owner.get("/api/spoolman").get_json() == {"enabled": False}
    assert sync(owner).status_code == 400


# --- the sync ----------------------------------------------------------------------------------------------------

def test_a_sync_makes_a_roll_of_every_spool_and_the_status_says_so(owner, server):
    server.spools = [spool(1), spool(2, vendor="Prusament", name="Oranje", material="PETG", remaining=None, price=None, color_hex=None, weight=750.0, article_number="")]
    server.spools[1]["initial_weight"] = None
    server.spools[1]["used_weight"] = 250.0
    server.spools[1]["filament"]["price"] = 24.99
    res = sync(owner)
    assert res.status_code == 200 and res.get_json() == {"created": 2, "updated": 0, "archived": 0, "skipped": 0, "total": 2, "sent": 0, "dropped": 0}
    black, orange = rolls(owner)[1], rolls(owner)[2]
    assert (black["brand"], black["colour"], black["material"], black["colour_hex"], black["barcode"]) == ("Bambu Lab", "Zwart", "PLA", "#1a1a1a", "EAN-1")
    assert (black["roll_weight_g"], black["remaining_g"], black["price"], black["diameter_mm"], black["print_temp_c"], black["bed_temp_c"]) == \
        ("1000.0", "800.0", "19.50", "1.75", 220, 55)
    assert (orange["brand"], orange["roll_weight_g"], orange["remaining_g"], orange["price"], orange["colour_hex"], orange["barcode"]) == \
        ("Prusament", "750.0", "500.0", "24.99", "", "")
    status = owner.get("/api/spoolman").get_json()
    assert status["enabled"] and status["host"] == "spoolman.test:7912" and status["rolls"] == 2 and status["pending"] == 0 and status["last_sync"]
    assert status["can_sync"] is True


def test_a_second_sync_updates_the_roll_instead_of_adding_one_and_keeps_what_is_the_apps(owner, server):
    server.spools = [spool(1)]
    sync(owner)
    roll = rolls(owner)[1]
    assert owner.patch(f"/api/spools/{roll['id']}", json={"notify_low": True}, headers=H).status_code == 200
    server.spools[0]["remaining_weight"] = 640.5
    res = sync(owner).get_json()
    assert (res["created"], res["updated"]) == (0, 1)
    after = rolls(owner)[1]
    assert after["id"] == roll["id"] and after["remaining_g"] == "640.5" and after["notify_low"] is True
    assert (sync(owner).get_json()["updated"]) == 0
    assert len(owner.get("/api/spools").get_json()) == 1


def test_an_archived_spool_is_archived_here_and_one_that_was_never_here_is_not_added(owner, server):
    server.spools = [spool(1), spool(2, archived=True)]
    assert sync(owner).get_json()["created"] == 1
    server.spools[0]["archived"] = True
    sync(owner)
    assert rolls(owner)[1]["archived"] is True and 2 not in rolls(owner)


def test_a_spool_that_is_gone_from_spoolman_is_archived_here_and_never_deleted(owner, server):
    server.spools = [spool(1), spool(2)]
    sync(owner)
    server.spools = [spool(2)]
    assert sync(owner).get_json()["archived"] == 1
    assert rolls(owner)[1]["archived"] is True and rolls(owner)[2]["archived"] is False


def test_a_roll_typed_in_by_hand_is_left_alone(owner, server):
    mine = make(owner, "/api/spools", {"brand": "Eigen", "roll_weight_g": 1000, "price": 10, "remaining_g": 400})
    server.spools = [spool(1)]
    sync(owner)
    server.spools = []
    sync(owner)
    assert [r for r in owner.get("/api/spools").get_json() if r["id"] == mine["id"]][0]["archived"] is False


def test_more_than_a_page_is_read_and_a_spool_that_is_not_one_is_skipped(owner, server):
    server.spools = [spool(n) for n in range(1, 251)] + ["junk", {"id": "x"}, {"id": True}]
    res = sync(owner).get_json()
    assert (res["created"], res["skipped"], res["total"]) == (250, 3, 250)


def test_a_spool_with_nonsense_in_it_is_clamped_rather_than_refused(owner, server):
    server.spools = [spool(1, vendor=None, name="x" * 500, diameter=500, settings_extruder_temp=9999, settings_bed_temp=-5, color_hex="zzz",
                           weight=-4)]
    server.spools[0].update(remaining_weight=-20, initial_weight=0, price=-1, comment="c" * 5000)
    server.spools[0]["filament"]["vendor"] = None
    assert sync(owner).status_code == 200
    roll = rolls(owner)[1]
    assert roll["brand"] == "Spoolman" and len(roll["colour"]) == 40 and roll["diameter_mm"] == "1.75" and roll["print_temp_c"] is None
    assert roll["bed_temp_c"] is None and roll["colour_hex"] == "" and roll["remaining_g"] == "0.0" and roll["roll_weight_g"] == "1000.0"
    assert roll["price"] == "0.00" and len(roll["notes"]) == 1000


def test_a_sync_that_cannot_reach_spoolman_says_so_and_changes_nothing(owner, server):
    server.spools = [spool(1)]
    sync(owner)
    server.down = True
    res = owner.post("/api/spoolman/sync", json={}, headers={**H, **NL})
    assert res.status_code == 502 and "niet bereikbaar" in res.get_json()["error"]
    server.down = False
    server.answer = Reply(302, b"")
    assert sync(owner).status_code == 502
    server.answer = Reply(500, b"")
    assert sync(owner).get_json()["error"]
    server.answer = Reply(200, b"<html>")
    assert sync(owner).status_code == 502
    server.answer = Reply(200, b"{}")
    assert sync(owner).status_code == 502
    assert len(rolls(owner)) == 1


# --- the library to Spoolman ---------------------------------------------------------------------------------------

GREY = {"brand": "Bambu Lab", "product_type": "Basic", "material": "PLA", "colour": "Grijs", "colour_hex": "#8e9089", "barcode": "43992833229019",
        "roll_weight_g": 1000, "diameter_mm": "1.75", "print_temp_c": 220, "bed_temp_c": 55, "price": "19.32"}


def push(owner, dry=False):
    return owner.post("/api/spoolman/push-library" + ("?dry_run=1" if dry else ""), json={}, headers=H)


def test_the_library_is_put_in_spoolman_as_vendors_and_filaments(owner, server):
    make(owner, "/api/filament-library", GREY)
    make(owner, "/api/filament-library", {"brand": "Bambu Lab", "material": "PETG", "colour": "Zwart", "roll_weight_g": 1000, "diameter_mm": "1.75"})
    res = push(owner)
    assert res.status_code == 200 and res.get_json() == {"created": 2, "existing": 0, "vendors": 1, "skipped": 0, "left": 0}
    assert [path for path, _ in server.created] == ["/vendor", "/filament", "/filament"]
    assert server.created[0][1] == {"name": "Bambu Lab"}
    grey = server.created[1][1]
    assert grey == {"name": "Basic Grijs", "vendor_id": 100, "material": "PLA", "price": 19.32, "density": 1.24, "diameter": 1.75, "weight": 1000.0,
                    "article_number": "43992833229019", "settings_extruder_temp": 220, "settings_bed_temp": 55, "color_hex": "8E9089"}
    assert server.created[2][1]["density"] == 1.27 and "price" not in server.created[2][1]


def test_pushing_again_adds_nothing_and_a_dry_run_changes_nothing(owner, server):
    make(owner, "/api/filament-library", GREY)
    assert push(owner, dry=True).get_json()["created"] == 1 and server.created == []
    push(owner)
    again = push(owner).get_json()
    assert (again["created"], again["existing"], again["vendors"]) == (0, 1, 0) and len(server.created) == 2


def test_a_filament_spoolman_already_has_is_left_as_it_is(owner, server):
    server.vendors = [{"id": 5, "name": "BAMBU LAB"}]
    server.filaments = [{"id": 9, "name": "iets anders", "material": "pla", "article_number": "43992833229019", "price": 1.0, "vendor": server.vendors[0]},
                        {"id": 10, "name": "basic grijs", "material": "PETG", "article_number": "", "vendor": server.vendors[0]}]
    make(owner, "/api/filament-library", GREY)                                                  # same vendor and article number
    make(owner, "/api/filament-library", {**GREY, "material": "PETG", "barcode": "other"})     # same vendor, name and material
    res = push(owner).get_json()
    assert (res["created"], res["existing"], res["vendors"]) == (0, 2, 0) and server.created == []
    assert server.filaments[0]["price"] == 1.0


def test_an_entry_that_is_the_same_filament_twice_in_spoolman_terms_is_made_once(owner, server):
    make(owner, "/api/filament-library", {**GREY, "refill": True, "barcode": "", "sku": "A1"})
    make(owner, "/api/filament-library", {**GREY, "refill": False, "barcode": "", "sku": "A2"})
    assert push(owner).get_json()["created"] == 1


def test_the_library_is_not_changed_by_a_push_and_a_missing_spoolman_is_reported(owner, server):
    entry = make(owner, "/api/filament-library", GREY)
    push(owner)
    assert owner.get("/api/filament-library").get_json()[0]["id"] == entry["id"]
    server.down = True
    assert push(owner).status_code == 502


def test_a_push_is_refused_without_spoolman(owner):
    assert push(owner).status_code == 400


def test_a_big_library_goes_over_in_runs(owner, server, monkeypatch):
    from app import spoolman
    monkeypatch.setattr(spoolman, "MAX_CREATED", 2)
    for n in range(5):
        make(owner, "/api/filament-library", {**GREY, "colour": f"K{n}", "barcode": f"B{n}"})
    assert push(owner).get_json()["left"] == 3
    assert push(owner).get_json()["left"] == 1
    assert push(owner).get_json()["left"] == 0 and len(server.filaments) == 5


# --- a roll from Spoolman is Spoolman's ----------------------------------------------------------------------------

def test_a_mirrored_roll_can_only_have_its_own_setting_changed(owner, server):
    server.spools = [spool(1)]
    sync(owner)
    roll = rolls(owner)[1]
    for body in ({"remaining_g": 1}, {"archived": True}, {"colour": "Rood"}, {"notify_low": True, "notes": "x"}):
        res = owner.patch(f"/api/spools/{roll['id']}", json=body, headers={**H, **NL})
        assert res.status_code == 409 and "Spoolman" in res.get_json()["error"], body
    assert owner.patch(f"/api/spools/{roll['id']}", json={"notify_low": True}, headers=H).status_code == 200
    assert owner.delete(f"/api/spools/{roll['id']}", headers=H).status_code == 409
    assert rolls(owner)[1]["colour"] == "Zwart"


def test_copying_product_details_to_rolls_with_the_same_barcode_skips_mirrored_ones(owner, server):
    server.spools = [spool(1, article_number="SAME")]
    sync(owner)
    mine = make(owner, "/api/spools", {"brand": "Eigen", "barcode": "SAME", "roll_weight_g": 1000, "price": 10, "remaining_g": 400})
    assert owner.get(f"/api/spools/{mine['id']}/siblings").get_json() == {"count": 0}
    res = post(owner, f"/api/spools/{mine['id']}/propagate", {"fields": ["brand"]})
    assert res.get_json() == {"updated": 0} and rolls(owner)[1]["brand"] == "Bambu Lab"


# --- reporting what was used ---------------------------------------------------------------------------------------

def booked(owner, server):
    server.spools = [spool(7, remaining=500.0)]
    sync(owner)
    roll = rolls(owner)[7]
    project = make(owner, "/api/projects", sheet_payload(roll["id"]))
    return roll, project


def test_booking_a_calculation_reports_the_grams_to_spoolman(owner, server, app):
    roll, project = booked(owner, server)
    assert post(owner, f"/api/projects/{project['id']}/book-stock").status_code == 200
    assert server.used == [(7, 70.0)]
    assert rolls(owner)[7]["remaining_g"] == "430.0"
    assert sql(app, "SELECT count(*) AS n FROM spoolman_pending_use")[0]["n"] == 0
    assert owner.get("/api/spoolman").get_json()["pending"] == 0


def test_a_booking_while_spoolman_is_away_still_works_and_is_sent_by_the_next_sync(owner, server, app):
    roll, project = booked(owner, server)
    server.down = True
    assert post(owner, f"/api/projects/{project['id']}/book-stock").status_code == 200
    assert server.used == [] and owner.get("/api/spoolman").get_json()["pending"] == 1
    server.down = False
    server.spools[0]["remaining_weight"] = 500.0                  # Spoolman has not heard of the 70 g yet
    res = sync(owner).get_json()
    assert res["sent"] == 1 and server.used == [(7, 70.0)]
    assert owner.get("/api/spoolman").get_json()["pending"] == 0
    server.spools[0]["remaining_weight"] = 430.0                  # ...and now it has
    sync(owner)
    assert rolls(owner)[7]["remaining_g"] == "430.0"


def test_what_is_still_owed_is_taken_off_the_weight_spoolman_reports(owner, server):
    roll, project = booked(owner, server)
    server.down = True
    post(owner, f"/api/projects/{project['id']}/book-stock")                   # 70 g owed
    server.down = False
    server.no_use = True
    assert sync(owner).status_code == 502                                      # it cannot send them, so it does not read the shelf either
    assert rolls(owner)[7]["remaining_g"] == "430.0"
    server.no_use = False
    assert sync(owner).get_json()["sent"] == 1


def test_a_booking_that_lands_during_a_sync_is_counted_against_the_weight_just_read(owner, server, app, monkeypatch):
    from app import spoolman
    server.spools = [spool(1, remaining=800.0)]
    monkeypatch.setattr(spoolman, "flush", lambda *, wait: (0, 0))        # the booking is committed after the flush, before the shelf is written
    sql(app, "INSERT INTO spoolman_pending_use (spoolman_id, grams) VALUES (1, 30)")
    sync(owner)
    assert rolls(owner)[1]["remaining_g"] == "770.0"


def test_a_use_that_spoolman_refuses_for_good_is_dropped_and_not_retried_forever(owner, server, app):
    sql(app, "INSERT INTO spoolman_pending_use (spoolman_id, grams) VALUES (99, 5)")        # no such spool in Spoolman
    server.spools = [spool(1)]
    res = sync(owner).get_json()
    assert res["dropped"] == 1 and res["sent"] == 0
    assert owner.get("/api/spoolman").get_json()["pending"] == 0


def test_a_roll_typed_in_by_hand_reports_nothing(owner, server):
    mine = make(owner, "/api/spools", {"brand": "Eigen", "roll_weight_g": 1000, "price": 10, "remaining_g": 500})
    project = make(owner, "/api/projects", sheet_payload(mine["id"]))
    assert post(owner, f"/api/projects/{project['id']}/book-stock").status_code == 200
    assert server.used == []


# --- backup ------------------------------------------------------------------------------------------------------

def test_a_backup_keeps_a_restored_roll_linked_to_its_spool(owner, server, app):
    server.spools = [spool(1), spool(2)]
    sync(owner)
    doc = owner.get("/api/backup").get_json()
    assert sorted(s["spoolman_id"] for s in doc["spools"]) == [1, 2]
    assert "spoolman_pending_use" not in str(doc) and "spoolman_synced_at" not in str(doc)
    assert post(owner, "/api/backup/restore", doc).status_code == 200
    assert sorted(rolls(owner)) == [1, 2]
    assert sync(owner).get_json()["created"] == 0                  # linked, so nothing is added a second time


@pytest.mark.parametrize("bad", ["1", 0, -3, True, 2 ** 31])
def test_a_backup_with_a_bad_spoolman_number_is_refused(owner, server, bad):
    server.spools = [spool(1)]
    sync(owner)
    doc = owner.get("/api/backup").get_json()
    doc["spools"][0]["spoolman_id"] = bad
    assert post(owner, "/api/backup/restore", doc).status_code == 400


def test_two_rolls_cannot_share_a_spoolman_number_in_a_backup(owner, server):
    server.spools = [spool(1), spool(2)]
    sync(owner)
    doc = owner.get("/api/backup").get_json()
    doc["spools"][1]["spoolman_id"] = doc["spools"][0]["spoolman_id"]
    assert post(owner, "/api/backup/restore", doc).status_code == 400


# --- who may --------------------------------------------------------------------------------------------------------

def test_everybody_may_read_the_status_but_only_an_administrator_may_sync(app, owner, server):
    member = join_with_passkey(app, owner)
    assert member.get("/api/spoolman").get_json()["can_sync"] is False
    assert member.post("/api/spoolman/sync", json={}, headers=H).status_code == 403
