"""The source of the filament and the printers: one at a time, chosen at the top of Settings -> Integrations. The choice decides what is used, never what
is kept: switching keeps every address, key and sign-in, and switching back uses them again. Until somebody chooses, it follows from what is set up."""
import dataclasses

import pytest

from app import bambu_cloud, bambu_live, sources
from tests.test_auth_api import H, post
from tests.test_bambu_cloud import sign_in, spool, sync as bambu_sync
from tests.test_bambu_live import FakeClient, SERIAL, Devices, live
from tests.test_bambu_live import fresh  # noqa: F401  (autouse fixture: no MQTT is ever reached)
from tests.test_domain_api import make, owner, sheet_payload  # noqa: F401  (fixture)
from tests.test_haspelsync import KEY as HASPEL_KEY, URL as HASPEL_URL
from tests.test_users import join_with_passkey, sql

SPOOLMAN = "http://spoolman.test:7912"


@pytest.fixture
def cloud(monkeypatch):
    fake = Devices()
    monkeypatch.setattr(bambu_cloud, "transport", fake)
    return fake


def source(client):
    res = client.get("/api/sources")
    assert res.status_code == 200
    return res.get_json()


def choose(client, name):
    return client.put("/api/sources", json={"source": name}, headers=H)


def set_haspelsync(owner):
    assert owner.put("/api/haspelsync/settings", json={"url": HASPEL_URL, "api_key": HASPEL_KEY}, headers=H).status_code == 200


# --- until somebody chooses, it follows from what is set up -----------------------------------------------------------------------

def test_a_fresh_installation_uses_spoolman_and_haspelsync(owner):
    answer = source(owner)
    assert (answer["source"], answer["chosen"], answer["can_change"]) == ("spoolman", False, True)
    assert [s["id"] for s in answer["sources"]] == ["spoolman", "bambu"]
    assert {s["id"]: s["uses"] for s in answer["sources"]} == {"spoolman": ["spoolman", "haspelsync"], "bambu": ["bambu_cloud"]}


def test_signed_in_to_bambu_without_spoolman_it_is_the_bambu_cloud(owner, cloud):
    sign_in(owner)
    assert source(owner)["source"] == "bambu"
    owner.put("/api/spoolman/settings", json={"url": SPOOLMAN}, headers=H)
    assert source(owner)["source"] == "spoolman"                       # a Spoolman address is recognised first


def test_a_choice_sticks_whatever_is_set_up(owner, cloud):
    assert choose(owner, "bambu").get_json()["chosen"] is True
    owner.put("/api/spoolman/settings", json={"url": SPOOLMAN}, headers=H)
    assert source(owner)["source"] == "bambu"


@pytest.mark.parametrize("bad", ["", "octoprint", None, 3, ["bambu"]])
def test_only_a_known_source_can_be_chosen(owner, bad):
    assert choose(owner, bad).status_code == 400
    assert source(owner)["chosen"] is False


def test_everybody_sees_the_source_but_only_an_administrator_chooses(app, owner):
    member = join_with_passkey(app, owner)
    assert source(member)["can_change"] is False
    assert choose(member, "bambu").status_code == 403
    assert app.test_client().get("/api/sources").status_code == 401


# --- the Bambu cloud chosen: Spoolman and HaspelSync rest, with their settings --------------------------------------------------

def test_with_the_bambu_cloud_chosen_spoolman_and_haspelsync_rest_but_keep_their_settings(app, owner, cloud):
    owner.put("/api/spoolman/settings", json={"url": SPOOLMAN}, headers=H)
    set_haspelsync(owner)
    sealed = sql(app, "SELECT url, api_key_enc FROM haspelsync_settings")[0]
    choose(owner, "bambu")
    assert owner.get("/api/spoolman").get_json()["enabled"] is False
    assert owner.post("/api/spoolman/sync", json={}, headers=H).status_code == 400
    haspel = owner.get("/api/haspelsync").get_json()
    assert (haspel["enabled"], haspel["configured"], haspel["ready"], haspel["key_set"]) == (False, True, False, True)
    assert owner.get("/api/haspelsync/connection").get_json()["state"] == "resting"           # and HaspelSync is not asked
    assert owner.get("/api/haspelsync/live").get_json() == {"enabled": False, "printers": []}
    assert owner.post("/api/haspelsync/test", json={}, headers=H).status_code == 409
    assert sql(app, "SELECT url, api_key_enc FROM haspelsync_settings")[0] == sealed           # nothing removed
    assert owner.get("/api/model-editor").get_json()["spoolman"] == {"enabled": False}


def test_with_the_bambu_cloud_chosen_a_booking_is_not_refused_for_a_spoolman_address(owner, cloud):
    owner.put("/api/spoolman/settings", json={"url": SPOOLMAN}, headers=H)
    choose(owner, "bambu")
    roll = make(owner, "/api/spools", {"brand": "Elegoo", "material": "PLA", "colour": "Rood", "roll_weight_g": 1000, "price": "15", "remaining_g": 500})
    project = make(owner, "/api/projects", sheet_payload(roll["id"]))
    assert post(owner, f"/api/projects/{project['id']}/book-stock").status_code == 200


def test_a_roll_of_a_source_that_rests_is_a_roll_like_any_other(app, owner, cloud):
    roll = make(owner, "/api/spools", {"brand": "Elegoo", "material": "PLA", "colour": "Rood", "roll_weight_g": 1000, "price": "15", "remaining_g": 500})
    sql(app, "UPDATE filament_spools SET spoolman_id = 7 WHERE id = %s", (roll["id"],))
    owner.put("/api/spoolman/settings", json={"url": SPOOLMAN}, headers=H)
    assert owner.patch(f"/api/spools/{roll['id']}", json={"price": "16"}, headers=H).status_code == 409        # Spoolman's while it is in use
    choose(owner, "bambu")
    assert owner.patch(f"/api/spools/{roll['id']}", json={"price": "16"}, headers=H).status_code == 200


# --- Spoolman + HaspelSync chosen: the Bambu cloud rests, with its sign-in ----------------------------------------------------------

def test_with_spoolman_chosen_the_bambu_cloud_rests_and_comes_back_when_chosen_again(app, owner, cloud):
    sign_in(owner)
    cloud.spools = [spool(1)]
    bambu_sync(owner)
    make(owner, "/api/printers", {"name": "Bambu P1S", "purchase_price": "700", "lifetime_hours": "3000", "power_kw": "0.15", "haspelsync_serial": SERIAL})
    roll = [r for r in owner.get("/api/spools").get_json() if r["bambu_id"] == 1][0]
    choose(owner, "spoolman")
    assert owner.get("/api/bambu-cloud").get_json()["active"] is False
    assert live(owner) == {"enabled": False, "printers": []} and FakeClient.made == []
    assert owner.get("/api/bambu-cloud/printers").status_code == 400
    assert owner.get("/api/model-editor").get_json()["bambu_cloud"] == {"enabled": False}
    assert owner.patch(f"/api/spools/{roll['id']}", json={"remaining_g": 10}, headers=H).status_code == 200
    project = make(owner, "/api/projects", sheet_payload(roll["id"]))
    assert post(owner, f"/api/projects/{project['id']}/book-stock").get_json()["cloud_waiting"] == 0
    assert sql(app, "SELECT count(*) AS n FROM bambu_cloud_pending_use")[0]["n"] == 0          # nothing is written back to a source that rests
    assert cloud.puts == []                                                                    # not even right away
    assert bambu_sync(owner).status_code == 409                                                # nor read from it
    choose(owner, "bambu")                                                                     # back: the sign-in is used again, no new sign-in
    assert owner.get("/api/bambu-cloud").get_json()["active"] is True
    assert owner.patch(f"/api/spools/{roll['id']}", json={"remaining_g": 20}, headers=H).status_code == 409
    assert live(owner)["enabled"] is True and len(FakeClient.made) == 1


def test_choosing_spoolman_closes_the_live_connection(owner, cloud):
    sign_in(owner)
    make(owner, "/api/printers", {"name": "Bambu P1S", "purchase_price": "700", "lifetime_hours": "3000", "power_kw": "0.15", "haspelsync_serial": SERIAL})
    live(owner)
    client = FakeClient.made[-1]
    choose(owner, "spoolman")
    assert client.disconnected and bambu_live._listener is None


def test_with_spoolman_chosen_haspelsync_is_used(owner, cloud):
    sign_in(owner)
    set_haspelsync(owner)
    assert owner.get("/api/haspelsync").get_json()["enabled"] is False                         # derived: the Bambu cloud, so HaspelSync rests
    choose(owner, "spoolman")
    assert owner.get("/api/haspelsync").get_json()["enabled"] is True


def test_a_spoolman_address_in_env_is_recognised_too(app, owner, cloud):
    sign_in(owner)
    app.config["APP_CONFIG"] = dataclasses.replace(app.config["APP_CONFIG"], spoolman_url=SPOOLMAN)
    assert source(owner)["source"] == "spoolman"


def test_the_choice_is_not_in_a_backup(owner):
    choose(owner, "bambu")
    assert sources.KEY not in owner.get("/api/backup").get_data(as_text=True)
