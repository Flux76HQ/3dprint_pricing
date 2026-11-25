"""Groups of rolls (bins, shelves, drawers): the groups themselves, what a roll in a group looks like in the lists and the stock, the backup, and the
Spoolman side: a spool's location is the roll's group, a roll moved here is moved there first, and the labels Spoolman prints are read by the scanner."""
import pytest

from tests.test_auth_api import H
from tests.test_backup import backup
from tests.test_domain_api import make, owner  # noqa: F401  (fixture)
from tests.test_spoolman import Spoolman, rolls, server, spool, stand_in, sync  # noqa: F401  (fixtures)
from tests.test_users import sql

ROLL = {"brand": "Bambu Lab", "colour": "Zwart", "material": "PLA", "roll_weight_g": "1000", "price": "19.50", "remaining_g": "800", "barcode": "EAN-1"}


def roll(owner, **extra):
    return make(owner, "/api/spools", {**ROLL, **extra})


def groups(owner):
    return {g["name"]: g for g in owner.get("/api/groups").get_json()}


def by_name(owner):
    return {r["colour"]: r for r in owner.get("/api/spools").get_json()}


# --- the groups ---------------------------------------------------------------------------------------------------

def test_a_group_is_made_by_name_and_found_again_in_any_case(owner):
    made = make(owner, "/api/groups", {"name": "  Bak A "})
    assert made["name"] == "Bak A" and made["rolls"] == 0 and made["in_use"] == 0 and made["remaining_g"] == "0"
    again = owner.post("/api/groups", json={"name": "bak a"}, headers=H)
    assert again.status_code == 409 and "Bak A" in again.get_json()["error"]
    assert owner.post("/api/groups", json={"name": " "}, headers=H).status_code == 400
    assert owner.post("/api/groups", json={"name": "x" * 65}, headers=H).status_code == 400
    assert [g["name"] for g in owner.get("/api/groups").get_json()] == ["Bak A"]


def test_a_roll_is_put_in_a_group_by_name_and_the_group_is_made_when_it_is_new(owner):
    made = roll(owner, group="Bak B")
    assert made["group_name"] == "Bak B" and made["group_id"]
    other = roll(owner, colour="Wit", group="bak b")                       # the same group, whatever the case
    assert other["group_id"] == made["group_id"] and list(groups(owner)) == ["Bak B"]
    none = roll(owner, colour="Rood")
    assert none["group_name"] == "" and none["group_id"] is None
    listed = by_name(owner)
    assert (listed["Zwart"]["group_name"], listed["Wit"]["group_name"], listed["Rood"]["group_name"]) == ("Bak B", "Bak B", "")
    assert groups(owner)["Bak B"]["rolls"] == 2 and groups(owner)["Bak B"]["remaining_g"] == "1600.0"


def test_a_roll_moves_between_groups_and_out_of_any_with_an_empty_name(owner):
    one = roll(owner)
    moved = owner.patch(f"/api/spools/{one['id']}", json={"group": "Doos 1"}, headers=H).get_json()
    assert moved["group_name"] == "Doos 1" and moved["remaining_g"] == "800.0"
    both = owner.patch(f"/api/spools/{one['id']}", json={"group": "Doos 2", "remaining_g": "700"}, headers=H).get_json()   # the group and something else at once
    assert both["group_name"] == "Doos 2" and both["remaining_g"] == "700.0"
    assert owner.patch(f"/api/spools/{one['id']}", json={"remaining_g": "600"}, headers=H).get_json()["group_name"] == "Doos 2"       # not sending it leaves it
    assert owner.patch(f"/api/spools/{one['id']}", json={"group": ""}, headers=H).get_json()["group_name"] == ""
    assert owner.patch(f"/api/spools/{one['id']}", json={}, headers=H).status_code == 400                                   # nothing to change is still nothing to change
    assert owner.patch("/api/spools/00000000-0000-4000-8000-000000000000", json={"group": "Doos 1"}, headers=H).status_code == 404
    assert sorted(groups(owner)) == ["Doos 1", "Doos 2"]                   # a group stays when its last roll leaves


def test_a_group_is_renamed_but_not_into_another_groups_name(owner):
    a, b = make(owner, "/api/groups", {"name": "Plank 1"}), make(owner, "/api/groups", {"name": "Plank 2"})
    roll(owner, group="Plank 1")
    renamed = owner.patch(f"/api/groups/{a['id']}", json={"name": "Plank Boven"}, headers=H)
    assert renamed.status_code == 200 and renamed.get_json()["name"] == "Plank Boven" and renamed.get_json()["rolls"] == 1
    assert by_name(owner)["Zwart"]["group_name"] == "Plank Boven"          # the roll follows
    assert owner.patch(f"/api/groups/{a['id']}", json={"name": "plank 2"}, headers=H).status_code == 409
    assert owner.patch(f"/api/groups/{b['id']}", json={"name": "PLANK 2"}, headers=H).status_code == 200      # only the case of its own name
    assert owner.patch(f"/api/groups/{b['id']}", json={"name": ""}, headers=H).status_code == 400
    assert owner.patch("/api/groups/00000000-0000-4000-8000-000000000000", json={"name": "x"}, headers=H).status_code == 404


def test_only_an_empty_group_is_deleted_and_an_archived_roll_still_counts(owner):
    full, empty = make(owner, "/api/groups", {"name": "Vol"}), make(owner, "/api/groups", {"name": "Leeg"})
    one = roll(owner, group="Vol")
    refused = owner.delete(f"/api/groups/{full['id']}", headers=H)
    assert refused.status_code == 409 and "Vol" in refused.get_json()["error"] and "1 rol" in refused.get_json()["error"]
    owner.patch(f"/api/spools/{one['id']}", json={"archived": True}, headers=H)
    assert owner.delete(f"/api/groups/{full['id']}", headers=H).status_code == 409           # archived, but it still names the group
    assert groups(owner)["Vol"]["rolls"] == 0 and groups(owner)["Vol"]["in_use"] == 1
    assert owner.delete(f"/api/groups/{empty['id']}", headers=H).status_code == 200
    assert owner.delete(f"/api/groups/{empty['id']}", headers=H).status_code == 404
    owner.patch(f"/api/spools/{one['id']}", json={"group": ""}, headers=H)
    assert owner.delete(f"/api/groups/{full['id']}", headers=H).status_code == 200


def test_several_rolls_are_moved_at_once_and_only_the_ones_that_were_elsewhere_count(owner):
    a, b, c = roll(owner, group="Bak A"), roll(owner, colour="Wit"), roll(owner, colour="Rood")
    res = owner.post("/api/groups/assign", json={"ids": [a["id"], b["id"], c["id"]], "group": "Bak A"}, headers=H)
    assert res.status_code == 200 and res.get_json() == {"moved": 2}                        # `a` was there already
    assert {r["group_name"] for r in owner.get("/api/spools").get_json()} == {"Bak A"}
    assert owner.post("/api/groups/assign", json={"ids": [a["id"], b["id"]], "group": ""}, headers=H).get_json() == {"moved": 2}
    assert sorted(r["group_name"] for r in owner.get("/api/spools").get_json()) == ["", "", "Bak A"]
    for body in ({"ids": [], "group": "x"}, {"ids": "x", "group": "x"}, {"group": "x"}, {"ids": [a["id"]], "group": "x" * 65}):
        assert owner.post("/api/groups/assign", json=body, headers=H).status_code == 400, body
    assert owner.post("/api/groups/assign", json={"ids": ["nope"], "group": "x"}, headers=H).status_code == 404
    assert owner.post("/api/groups/assign", json={"ids": ["00000000-0000-4000-8000-000000000000"], "group": "x"}, headers=H).status_code == 404
    assert owner.post("/api/groups/assign", json={"ids": [a["id"]] * 2 + [b["id"]], "group": "Bak Z"}, headers=H).get_json() == {"moved": 2}   # a repeated id counts once


def test_a_copy_of_a_roll_takes_its_group_and_a_delivery_can_be_put_away_in_one(owner):
    one = roll(owner, group="Bak C", count=3)
    assert [r["group_name"] for r in owner.get("/api/spools").get_json()] == ["Bak C"] * 3 and one["group_name"] == "Bak C"
    owner.post("/api/filament-library", json={"brand": "Bambu Lab", "colour": "Zwart", "material": "PLA", "roll_weight_g": "1000", "diameter_mm": "1.75",
                                              "barcode": "LIB-9", "price": "17.00"}, headers=H)
    res = owner.post("/api/spools/bulk", json={"items": [{"barcode": "LIB-9", "count": 2}], "group": "Levering"}, headers=H)
    assert res.status_code == 201 and {r["group_name"] for r in res.get_json()["rolls"]} == {"Levering"}
    assert groups(owner)["Levering"]["rolls"] == 2
    plain = owner.post("/api/spools/bulk", json={"items": [{"barcode": "LIB-9", "count": 1}]}, headers=H).get_json()
    assert plain["rolls"][0]["group_name"] == ""


# --- the stock -------------------------------------------------------------------------------------------------------

def test_a_kind_in_the_stock_says_where_its_rolls_are_and_what_is_in_each_place(owner):
    roll(owner, group="Bak A", remaining_g="400")
    roll(owner, group="Bak B", remaining_g="600")
    roll(owner, remaining_g="900")
    roll(owner, group="Bak A", remaining_g="0")                            # an empty roll is no stock, but it is in its group
    roll(owner, colour="Wit", barcode="EAN-2", group="Bak C", remaining_g="0")      # a kind that is sold out
    stock = {g["colour"]: g for g in owner.get("/api/spools/stock").get_json()["groups"]}
    black = stock["Zwart"]
    assert black["groups"] == ["Bak A", "Bak B"] and black["roll_count"] == 3 and black["remaining_g"] == "1900.0"
    here = black["by_group"]
    assert (here["bak a"]["roll_count"], here["bak a"]["remaining_g"], here["bak a"]["group"]) == (1, "400.0", "Bak A")
    assert (here["bak b"]["roll_count"], here["bak b"]["remaining_g"]) == (1, "600.0")
    assert (here[""]["roll_count"], here[""]["remaining_g"], here[""]["group"]) == (1, "900.0", "")
    assert sorted(r["group"] for r in black["rolls"]) == ["", "Bak A", "Bak B"]
    assert stock["Wit"]["groups"] == ["Bak C"] and stock["Wit"]["by_group"]["bak c"]["roll_count"] == 0


# --- the backup ------------------------------------------------------------------------------------------------------

def test_the_groups_go_into_a_backup_and_come_back_with_their_rolls(owner):
    roll(owner, group="Bak A")
    roll(owner, colour="Wit", group="Bak B")
    roll(owner, colour="Rood")
    make(owner, "/api/groups", {"name": "Lege plank"})
    doc = backup(owner).get_json()
    assert doc["groups"] == ["Bak A", "Bak B", "Lege plank"]
    assert {r["colour"]: r["group"] for r in doc["spools"]} == {"Zwart": "Bak A", "Wit": "Bak B", "Rood": ""}
    owner.post("/api/groups/assign", json={"ids": [r["id"] for r in owner.get("/api/spools").get_json()], "group": "Anders"}, headers=H)
    for g in owner.get("/api/groups").get_json():
        if g["name"] != "Anders":
            assert owner.delete(f"/api/groups/{g['id']}", headers=H).status_code == 200
    assert owner.post("/api/backup/restore", json=doc, headers=H).status_code == 200
    assert sorted(groups(owner)) == ["Bak A", "Bak B", "Lege plank"]       # what the file said, and not what was there before
    assert {r["colour"]: r["group_name"] for r in owner.get("/api/spools").get_json()} == {"Zwart": "Bak A", "Wit": "Bak B", "Rood": ""}
    assert groups(owner)["Lege plank"]["rolls"] == 0


def test_a_backup_from_before_the_groups_restores_and_a_bad_group_is_refused(owner):
    roll(owner, group="Bak A")
    old = backup(owner).get_json()
    old.pop("groups")
    for row in old["spools"]:
        row.pop("group")
    old["format_version"] = 6
    assert owner.post("/api/backup/restore", json=old, headers=H).status_code == 200
    assert groups(owner) == {} and by_name(owner)["Zwart"]["group_name"] == ""
    named = backup(owner).get_json()
    named["spools"][0]["group"] = "Bak Z"                                  # a roll that names a group the file does not list: it is a group
    assert owner.post("/api/backup/restore", json=named, headers=H).status_code == 200 and "Bak Z" in groups(owner)
    for bad in ({"groups": [1]}, {"groups": ["a" * 65]}, {"groups": "Bak"}, {"groups": [""]}):
        res = owner.post("/api/backup/restore", json={**named, **bad}, headers=H)
        assert res.status_code == 400, bad
    again = backup(owner).get_json()
    again["groups"] = ["bak z", "Bak Z", "BAK Z"]                          # one group in three spellings is one group, the first spelling
    assert owner.post("/api/backup/restore", json=again, headers=H).status_code == 200
    assert list(groups(owner)) == ["bak z"] and by_name(owner)["Zwart"]["group_name"] == "bak z"


# --- Spoolman: a spool's location is the roll's group -------------------------------------------------------------------

def test_a_sync_makes_the_location_of_a_spool_the_group_of_its_roll(owner, server):
    server.spools = [spool(1, location="Plank 1"), spool(2, name="Wit", location="plank 1 "), spool(3, name="Rood")]
    res = sync(owner).get_json()
    assert res["groups"] == 1 and res["created"] == 3
    assert list(groups(owner)) == ["Plank 1"] and groups(owner)["Plank 1"]["from_spoolman"] == 2
    mirrored = rolls(owner)
    assert (mirrored[1]["group_name"], mirrored[2]["group_name"], mirrored[3]["group_name"]) == ("Plank 1", "Plank 1", "")
    server.spools[0]["location"] = "Droogbox"                              # moved in Spoolman: moved here
    server.spools[1]["location"] = None                                    # taken out of its location there: out of its group here
    res = sync(owner).get_json()
    assert (res["updated"], res["groups"]) == (2, 1)
    mirrored = rolls(owner)
    assert (mirrored[1]["group_name"], mirrored[2]["group_name"]) == ("Droogbox", "")
    assert sorted(groups(owner)) == ["Droogbox", "Plank 1"]                # a group stays when no spool is in it (it is the app's, and may be wanted again)
    assert sync(owner).get_json()["updated"] == 0                          # and nothing changes while nothing changed


def test_a_roll_typed_in_here_that_turns_out_to_be_a_spool_keeps_its_group_unless_spoolman_has_one(owner, server):
    typed = roll(owner, group="Mijn bak")
    server.spools = [spool(1, location=None)]
    res = sync(owner).get_json()
    assert res["linked"] == 1 and rolls(owner)[1]["id"] == typed["id"] and rolls(owner)[1]["group_name"] == "Mijn bak"
    assert sync(owner).get_json()["updated"] == 1                          # the next sync reads Spoolman's word, which is none: Spoolman is the truth for a spool
    assert rolls(owner)[1]["group_name"] == ""


def test_a_roll_linked_to_a_spool_takes_the_location_spoolman_has(owner, server):
    roll(owner, group="Mijn bak")
    server.spools = [spool(1, location="Plank 3")]
    assert sync(owner).get_json()["linked"] == 1 and rolls(owner)[1]["group_name"] == "Plank 3"


def test_moving_a_roll_from_spoolman_tells_spoolman_first(owner, server):
    server.spools = [spool(1), spool(2, name="Wit")]
    sync(owner)
    one = rolls(owner)[1]
    res = owner.patch(f"/api/spools/{one['id']}", json={"group": "Plank 9"}, headers=H)
    assert res.status_code == 200 and res.get_json()["group_name"] == "Plank 9"
    assert server.patched == [(1, {"location": "Plank 9"})] and server.spools[0]["location"] == "Plank 9"
    assert rolls(owner)[1]["group_name"] == "Plank 9" and rolls(owner)[2]["group_name"] == ""
    assert sync(owner).get_json()["updated"] == 0                          # Spoolman says what the app says
    res = owner.post("/api/groups/assign", json={"ids": [rolls(owner)[1]["id"], rolls(owner)[2]["id"]], "group": ""}, headers=H)
    assert res.get_json() == {"moved": 1} and server.patched[-1] == (1, {"location": None})        # out of its location there, and the one that had none costs no call
    assert len(server.patched) == 2


def test_a_roll_that_spoolman_cannot_be_told_about_does_not_move(owner, server):
    server.spools = [spool(1), spool(2, name="Wit"), spool(3, name="Rood")]
    sync(owner)
    server.no_patch = True
    ids = [rolls(owner)[n]["id"] for n in (1, 2, 3)]
    res = owner.patch(f"/api/spools/{ids[0]}", json={"group": "Plank 9"}, headers=H)
    assert res.status_code == 502 and "Spoolman" in res.get_json()["error"]
    assert rolls(owner)[1]["group_name"] == "" and groups(owner) == {}
    assert owner.post("/api/groups/assign", json={"ids": ids, "group": "Plank 9"}, headers=H).status_code == 502
    assert {r["group_name"] for r in rolls(owner).values()} == {""}
    server.no_patch = False
    typed = roll(owner, colour="Handgemaakt")                              # a roll that is not a spool is moved here, whatever Spoolman does
    server.no_patch = True
    assert owner.patch(f"/api/spools/{typed['id']}", json={"group": "Plank 9"}, headers=H).status_code == 200


def test_the_rest_of_a_mirrored_roll_is_still_spoolmans_to_change(owner, server):
    server.spools = [spool(1)]
    sync(owner)
    one = rolls(owner)[1]
    res = owner.patch(f"/api/spools/{one['id']}", json={"group": "Plank 9", "price": "1"}, headers=H)
    assert res.status_code == 409 and server.patched == [] and rolls(owner)[1]["group_name"] == ""      # refused before anything moved
    ok = owner.patch(f"/api/spools/{one['id']}", json={"group": "Plank 9", "notify_low": True}, headers=H)
    assert ok.status_code == 200 and ok.get_json()["notify_low"] is True and ok.get_json()["group_name"] == "Plank 9"


def test_without_spoolman_in_use_a_mirrored_roll_moves_here_only(owner, app, stand_in):
    stand_in.spools = [spool(1)]
    one = roll(owner)
    sql(app, "UPDATE filament_spools SET spoolman_id = 1 WHERE id = %s", (one["id"],))
    assert owner.patch(f"/api/spools/{one['id']}", json={"group": "Plank 9"}, headers=H).get_json()["group_name"] == "Plank 9"
    assert stand_in.patched == []                                          # no address, no Spoolman: nothing is called


def test_renaming_a_group_renames_the_location_in_spoolman_first(owner, server):
    server.spools = [spool(1, location="Plank 1"), spool(2, name="Wit", location="Plank 1")]
    sync(owner)
    made = groups(owner)["Plank 1"]
    res = owner.patch(f"/api/groups/{made['id']}", json={"name": "Plank Boven"}, headers=H)
    assert res.status_code == 200 and server.renamed == [("Plank 1", "Plank Boven")]
    assert [s["location"] for s in server.spools] == ["Plank Boven"] * 2 and sync(owner).get_json()["updated"] == 0
    server.no_patch = True
    assert owner.patch(f"/api/groups/{made['id']}", json={"name": "Anders"}, headers=H).status_code == 502
    assert list(groups(owner)) == ["Plank Boven"]                          # Spoolman did not take it, so it is not renamed here
    server.no_patch = False
    empty = make(owner, "/api/groups", {"name": "Zonder spoel"})
    assert owner.patch(f"/api/groups/{empty['id']}", json={"name": "Nog leeg"}, headers=H).status_code == 200
    assert server.renamed == [("Plank 1", "Plank Boven")]                  # a group without a spool of Spoolman's has nothing to rename there


def test_a_group_with_a_slash_in_its_name_is_renamed_there_under_that_name(owner, server):
    server.spools = [spool(1, location="Kast A/B")]
    sync(owner)
    assert owner.patch(f"/api/groups/{groups(owner)['Kast A/B']['id']}", json={"name": "Kast C"}, headers=H).status_code == 200
    assert server.renamed == [("Kast A/B", "Kast C")]


def test_a_roll_made_in_spoolman_by_a_push_has_its_group_as_location(owner, server):
    roll(owner, group="Bak A")
    roll(owner, colour="Wit", barcode="EAN-2")
    assert owner.post("/api/spoolman/push-rolls", json={}, headers=H).get_json()["created"] == 2
    assert sorted((s["filament"]["name"], s["location"] or "") for s in server.spools) == [("Wit", ""), ("Zwart", "Bak A")]


def test_pushing_the_groups_only_fills_in_a_location_that_spoolman_has_not_got(owner, app, server):
    typed = [roll(owner, colour=name, barcode=f"EAN-{n}", group=place)
             for n, (name, place) in enumerate((("Zwart", "Bak A"), ("Wit", "Bak B"), ("Rood", "Bak C"), ("Blauw", "")), 1)]
    server.spools = [spool(1, name="Zwart", location=None), spool(2, name="Wit", location="Bak B"), spool(3, name="Rood", location="Elders"), spool(4, name="Blauw")]
    for spool_ in server.spools:                                           # the article numbers of the rolls above: they are linked by `sync`
        spool_["filament"]["article_number"] = f"EAN-{spool_['id']}"
    sync(owner)
    assert {n: r["group_name"] for n, r in rolls(owner).items()} == {1: "Bak A", 2: "Bak B", 3: "Elders", 4: ""}      # Spoolman's word, except where it has none
    sql(app, "UPDATE filament_spools SET group_id = (SELECT id FROM filament_groups WHERE name = 'Bak C') WHERE spoolman_id = 3")    # another word here than there
    plan = owner.post("/api/spoolman/push-groups?dry_run=1", json={}, headers=H).get_json()
    assert plan == {"set": 1, "same": 1, "other": 1, "gone": 0, "left": 0} and server.patched == []
    done = owner.post("/api/spoolman/push-groups", json={}, headers=H).get_json()
    assert done["set"] == 1 and server.patched == [(1, {"location": "Bak A"})] and server.spools[2]["location"] == "Elders"      # Spoolman's other word is left alone
    assert owner.post("/api/spoolman/push-groups", json={}, headers=H).get_json() == {"set": 0, "same": 2, "other": 1, "gone": 0, "left": 0}
    assert typed[0]["group_name"] == "Bak A"


def test_pushing_the_groups_needs_a_spoolman_and_an_administrator(owner, stand_in):
    assert owner.post("/api/spoolman/push-groups", json={}, headers=H).status_code == 400          # no address: `spoolman.off`
    from app.access import is_admin_only
    assert is_admin_only("/api/spoolman/push-groups", "POST")
    assert not is_admin_only("/api/groups", "GET") and not is_admin_only("/api/groups/assign", "POST")


# --- the labels Spoolman prints -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("code,number", [
    ("WEB+SPOOLMAN:S-12", 12), ("web+spoolman:s-12", 12), ("Web+Spoolman:S-007", 7),
    ("http://spoolman:7912/spool/show/12", 12), ("https://spools.example.org/spool/show/12/", 12),
    ("https://example.org/spoolman/spool/show/12", 12), ("HTTP://HOST:8000/SPOOL/SHOW/12?x=1", 12)])
def test_a_label_of_spoolman_names_a_spool_in_every_form_it_is_printed_in(code, number):
    from app import spoolman
    assert spoolman.scanned_spool(code) == number


@pytest.mark.parametrize("code", ["", "8719", "EAN-1", "web+spoolman:s-0", "web+spoolman:s-", "web+spoolman:f-12", "web+spoolman:s-12x", "web+spoolman:s-99999999999",
                                  "web+spoolman:s-2147483648", "ftp://host/spool/show/12", "https://host/spool/show/", "https://host/filament/show/12",
                                  "https://host/spool/show/12/edit", "javascript:alert(1)//spool/show/12", "x" * 5000])
def test_anything_else_is_an_ordinary_barcode(code):
    from app import spoolman
    assert spoolman.scanned_spool(code) is None


def scan(owner, code):
    return owner.get("/api/spools/scan", query_string={"code": code}).get_json()


def test_scanning_a_label_of_spoolman_finds_the_roll_that_is_that_spool(owner, server):
    server.spools = [spool(12, location="Plank 1")]
    sync(owner)
    mine = rolls(owner)[12]
    for code in ("WEB+SPOOLMAN:S-12", "http://spoolman:7912/spool/show/12", " web+spoolman:s-12 "):
        found = scan(owner, code)["label"]
        assert found["number"] == 12 and found["roll"]["id"] == mine["id"] and found["roll"]["group_name"] == "Plank 1", code
    unknown = scan(owner, "WEB+SPOOLMAN:S-99")
    assert unknown["label"] == {"number": 99, "roll": None}                # a spool that has not been synced yet: the screen says so
    assert scan(owner, "EAN-12") == {"code": "EAN-12", "label": None} and scan(owner, "") == {"code": "", "label": None}


def test_a_label_is_never_a_barcode_to_look_up_or_to_add(owner, server):
    server.spools = [spool(12)]
    sync(owner)
    looked = owner.get("/api/spools/lookup", query_string={"barcode": "web+spoolman:s-12"}).get_json()
    assert looked["spool"] is None and looked["stock"] is None and looked["label"]["roll"]["colour"] == "Zwart"
    scanned = owner.get("/api/spools/from-barcode", query_string={"barcode": "web+spoolman:s-12"}).get_json()
    assert scanned["roll"] is None and scanned["source"] is None and scanned["label"]["number"] == 12
    assert owner.get("/api/spools/from-barcode", query_string={"barcode": "EAN-12"}).get_json()["label"] is None
    roll(owner, colour="Fout", barcode="web+spoolman:s-12")                 # a label that was saved as a barcode before this (it is not worth a roll of its own)
    again = owner.get("/api/spools/from-barcode", query_string={"barcode": "web+spoolman:s-12"}).get_json()
    assert again["roll"] is None and again["stock"] is None and again["label"]["roll"]["colour"] == "Zwart"
    assert owner.get("/api/spools/lookup", query_string={"barcode": "web+spoolman:s-12"}).get_json()["spool"] is None
