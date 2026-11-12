"""HaspelSync as the source of the running print and the filament per slot: what is asked of it (a GET on four fixed routes, with a key that goes nowhere else),
what is passed on (a projection, nothing of its own answer), what is kept (the key sealed, never returned, never in a backup) and the serial number a printer here names."""
import dataclasses
import json
import sqlite3
from datetime import datetime, timezone

import pytest
import requests

from app import config as config_module
from app import haspelsync, passwords
from app.config import ConfigError
from tests.test_auth_api import H, post
from tests.test_domain_api import make, owner  # noqa: F401  (fixture)
from tests.test_users import join_with_passkey, sql

URL = "http://haspelsync.test:4000"
KEY = "ams_" + "Ab3-_" * 8 + "xyz"                       # 4 + 43 characters, as HaspelSync makes them
OTHER_KEY = "ams_" + "Zy9_-" * 8 + "xyz"
SERIAL = "01P00A000000001"
SECOND = "01P00A000000002"
NL = {"X-Lang": "nl"}
EN = {"X-Lang": "en"}
STARTED = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
STARTED_MS = int(STARTED.timestamp() * 1000)


class Reply:
    def __init__(self, status=200, body=b"[]"):
        self.status_code, self.body = status, body

    def iter_content(self, size):
        yield self.body

    def close(self):
        pass


def slot(label, *, state="Loaded (Bambu Lab)", material="PLA", cols=("FF0000FF",), spool=True, remaining=612.5, percentage=61.25, name="Rood"):
    """One entry of HaspelSync's slot list, with the things this app must never pass on (the tag, the chip) in it."""
    if state == "Empty":
        return {"amsId": label, "slotState": "Empty", "slot": {"id": 0}, "existingSpool": None, "spoolmanId": None, "key": "none"}
    return {"amsId": label, "slotState": state, "vendor": "Bambu Lab", "material": material, "filamentName": name, "spoolmanId": 7 if spool else None, "key": "GFA00|FF0000",
            "slot": {"tray_uuid": "SECRET-UUID", "tag_uid": "SECRET-TAG", "tray_type": material, "tray_sub_brands": "PLA Basic", "cols": list(cols), "tray_color": cols[0], "remain": 80},
            "existingSpool": {"id": 7, "archived": False, "remaining_weight": remaining, "remaining_percentage": percentage, "initial_weight": 1000.0,
                              "filament": {"id": 3, "name": name, "material": material, "color_hex": "FF0000", "vendor": {"name": "Bambu Lab"}}} if spool else None}


def trio(serial=SERIAL, **print_over):
    """What HaspelSync answers for a running print: the status, the print and the slots."""
    spools = [slot("A1"), slot("A2", state="Loaded (3rd party)", material="PETG", cols=("00FF00FF",), spool=False, name="Groen"), slot("A3", state="Empty")]
    status = {"spoolmanStatus": "Connected", "mqttStatus": "Connected", "lastMqttUpdate": "2026-11-12T10:30:00.000Z", "PRINTER_ID": serial, "printerName": "P2S Werkplaats",
              "SPOOLMAN_URL": "http://secret-spoolman:7912", "VERSION": "1.3.8", "monitoringEnabled": True, "gcodeState": "RUNNING", "activeSlot": "A2",
              "amsEnv": [{"amsId": "A", "model": "AMS 2 Pro", "humidity": 2, "humidityPercent": 31, "temperature": 24.6,
                          "drying": {"active": True, "remainingMinutes": 95, "targetTemp": 55}}]}
    print_ = {"gcodeState": "RUNNING", "jobName": "0.2mm layer, 2 walls", "modelTitle": "Draak", "layerNum": 37, "totalLayers": 149, "loadedSpools": spools,
              "fullConsumption": {"0": {"amsId": "A1", "matchedAmsId": "A2", "grams": 42.34, "tray_uuid": "SECRET-UUID"}},
              "consumption": {"0": {"amsId": "A1", "matchedAmsId": "A2", "grams": 10.44}},
              "startedAt": STARTED_MS, "elapsedMs": 1_800_000, "remainingMinutes": 95, "estimatedEndAt": STARTED_MS + 95 * 60_000, "stage": "Printing", "preparing": False,
              "lastPrintSummary": {"printError": "internal"}}
    print_.update(print_over)
    return status, print_, spools


class HaspelSync:
    """A stand-in for HaspelSync: it knows printers, answers the four routes, and notes every call. A test never reaches a real one."""

    def __init__(self):
        self.status, self.print, self.spools, self.calls = {}, {}, {}, []
        self.printers, self.down, self.answer, self.codes, self.key = [], False, None, {}, KEY

    def add(self, serial=SERIAL, name="P2S Werkplaats", **print_over):
        self.status[serial], self.print[serial], self.spools[serial] = trio(serial, **print_over)
        self.printers.append({"id": serial, "name": name})

    def request(self, method, url, **kwargs):
        assert method == "GET" and url.startswith(URL + "/api/"), (method, url)          # nothing but a GET on HaspelSync's own API
        assert kwargs["allow_redirects"] is False and kwargs["timeout"] and kwargs["headers"]["Accept"] == "application/json"
        path = url[len(URL):]
        self.calls.append((path, kwargs["headers"].get("Authorization")))
        if self.down:
            raise requests.ConnectionError("down")
        if kwargs["headers"].get("Authorization") != f"Bearer {self.key}":
            return Reply(401, b'{"ok": false}')
        if path in self.codes:
            return Reply(self.codes[path], b'{"ok": false}')
        if self.answer is not None:
            return self.answer
        if path == "/api/printers":
            return Reply(body=json.dumps(self.printers).encode())
        _, _, kind, serial = path.split("/")
        store = {"status": self.status, "print": self.print, "spools": self.spools}[kind]
        return Reply(body=json.dumps(store[serial]).encode()) if serial in store else Reply(404, b'{"ok": false}')

    def paths(self):
        return [path for path, _ in self.calls]


@pytest.fixture(autouse=True)
def _fresh_memory():
    haspelsync.clear_cache()                  # what one test saw of a printer must not answer the next
    yield
    haspelsync.clear_cache()


@pytest.fixture
def stand_in(monkeypatch):
    """A HaspelSync that no address points to yet."""
    fake = HaspelSync()
    monkeypatch.setattr(requests, "request", fake.request)
    return fake


@pytest.fixture
def server(app, stand_in):
    """A HaspelSync at the address and with the key `.env` gives."""
    app.config["APP_CONFIG"] = dataclasses.replace(app.config["APP_CONFIG"], haspelsync_url=URL, haspelsync_api_key=KEY)
    return stand_in


@pytest.fixture
def typed(owner, stand_in):
    """A HaspelSync at the address and with the key an administrator typed in the app."""
    assert save(owner, url=URL, api_key=KEY).status_code == 200
    return stand_in


def save(owner, **body):
    return owner.put("/api/haspelsync/settings", json=body, headers={**H, **EN})


def status(client):
    return client.get("/api/haspelsync").get_json()


def live(client, headers=None):
    res = client.get("/api/haspelsync/live", headers=headers or {})
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def printer(owner, name="P2S", serial=SERIAL, **extra):
    body = {"name": name, "purchase_price": 500, "lifetime_hours": 5000, **extra}
    if serial is not None:
        body["haspelsync_serial"] = serial
    return make(owner, "/api/printers", body)


# --- configuration -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [("", ""), ("http://haspelsync:4000", "http://haspelsync:4000"), (" https://h.example.org/ ", "https://h.example.org")])
def test_the_address_is_read_from_the_environment(monkeypatch, value, expected):
    monkeypatch.setenv("HASPELSYNC_URL", value)
    assert config_module._haspelsync_url() == expected


@pytest.mark.parametrize("value", ["haspelsync:4000", "ftp://h", "http://user:pw@h:4000", "http://h:4000?x=1", "http://", "http://h:0", "http://h:4000#x", "http://" + "a" * 300])
def test_an_address_that_is_not_plain_http_or_https_is_refused(monkeypatch, value):
    monkeypatch.setenv("HASPELSYNC_URL", value)
    with pytest.raises(ConfigError, match="HASPELSYNC_URL"):
        config_module._haspelsync_url()


def test_the_key_is_read_from_the_environment_and_only_a_key_gets_through(monkeypatch):
    monkeypatch.setenv("HASPELSYNC_API_KEY", f"  {KEY}  ")
    assert config_module._haspelsync_key() == KEY
    monkeypatch.setenv("HASPELSYNC_API_KEY", "")
    assert config_module._haspelsync_key() == ""
    for bad in ("ams_short", "Bearer " + KEY, KEY + "\r\nX-Evil: 1", KEY + " extra", "xyz_" + "A" * 43, "ams_" + "A" * 300):
        monkeypatch.setenv("HASPELSYNC_API_KEY", bad)
        with pytest.raises(ConfigError, match="HASPELSYNC_API_KEY"):
            config_module._haspelsync_key()


def test_a_key_in_env_without_an_address_in_env_refuses_to_start(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("SETUP_CODE", "code")
    monkeypatch.setenv("HASPELSYNC_API_KEY", KEY)
    monkeypatch.delenv("HASPELSYNC_URL", raising=False)
    with pytest.raises(ConfigError, match="HASPELSYNC_URL"):
        config_module.load_config()
    monkeypatch.setenv("HASPELSYNC_URL", URL)
    assert config_module.load_config().haspelsync_api_key == KEY


def test_the_address_of_spoolman_is_still_checked_the_way_it_was(monkeypatch):
    monkeypatch.setenv("SPOOLMAN_URL", "spoolman:8000")
    with pytest.raises(ConfigError) as error:
        config_module._spoolman_url()
    assert str(error.value) == "SPOOLMAN_URL must be an http(s) address such as http://spoolman:8000 (no login, query or fragment), or empty."


# --- the address and the key, typed in the app ---------------------------------------------------------------------

def test_without_an_address_there_is_no_haspelsync_and_nothing_is_asked(owner, stand_in):
    assert status(owner) == {"enabled": False, "ready": False, "can_configure": True, "host": None, "url": "", "url_from_env": False, "key_set": False,
                             "key_readable": True, "key_from_env": False}
    printer(owner)
    assert live(owner) == {"enabled": False, "printers": []}
    assert owner.get("/api/haspelsync/printers").status_code == 400
    assert stand_in.calls == []


def test_an_administrator_types_the_address_and_the_key_and_they_are_used(owner, stand_in):
    stand_in.add()
    res = save(owner, url=URL + "/", api_key=KEY)
    assert res.status_code == 200 and res.get_json()["url"] == URL
    answer = status(owner)
    assert answer["enabled"] and answer["ready"] and answer["key_set"] and answer["key_readable"] and answer["host"] == "haspelsync.test:4000"
    assert answer["url_from_env"] is False and answer["key_from_env"] is False
    assert owner.post("/api/haspelsync/test", json={}, headers=H).get_json() == {"ok": True, "printers": 1}
    assert stand_in.calls == [("/api/printers", f"Bearer {KEY}")]


def test_the_key_is_sealed_under_a_label_of_its_own_and_is_never_returned(owner, stand_in, app):
    res = save(owner, url=URL, api_key=KEY)
    assert KEY not in res.get_data(as_text=True) and KEY not in json.dumps(status(owner))
    stored = sql(app, "SELECT api_key_enc FROM haspelsync_settings")[0]["api_key_enc"]
    secret = app.config["APP_CONFIG"].session_secret
    assert KEY not in stored and passwords.unseal(secret, stored.encode(), haspelsync.KEY_INFO) == KEY.encode()
    assert passwords.unseal(secret, stored.encode()) is None and passwords.unseal(secret, stored.encode(), b"printpricing/ai-key/v1") is None


@pytest.mark.parametrize("body", [{"url": "haspelsync:4000"}, {"url": "ftp://x"}, {"url": "http://u:p@x"}, {"url": "http://x?y=1"}, {"url": 5}, {"url": None}, {"url": ["http://x"]},
                                  {"api_key": "ams_short"}, {"api_key": "nope"}, {"api_key": KEY + "\nX: y"}, {"api_key": 5}, {"api_key": ["x"]}, {"api_key": "   "}])
def test_an_address_or_key_that_is_not_one_is_refused_and_nothing_is_saved(owner, stand_in, body):
    assert save(owner, **body).status_code == 400
    assert sql(owner.application, "SELECT * FROM haspelsync_settings") == []


def test_a_key_that_is_left_out_stays_and_null_removes_it(owner, typed):
    assert save(owner, url=URL).get_json()["key_set"] is True
    assert save(owner, api_key="").get_json()["key_set"] is True
    assert save(owner, api_key=None).get_json()["key_set"] is False and save(owner, url=URL).get_json()["url"] == URL
    assert save(owner, api_key=OTHER_KEY).get_json()["key_set"] is True


def test_an_address_that_replaces_another_takes_the_saved_key_with_it_unless_a_new_key_comes(owner, typed):
    """Otherwise an administrator could point the address at a server of their own and have the key sent there, to read it."""
    assert save(owner, url=URL).get_json()["key_set"] is True                              # the same address: the key stays
    assert save(owner, url="http://elsewhere.test:4000").get_json()["key_set"] is False    # another one: it does not follow
    assert sql(owner.application, "SELECT api_key_enc FROM haspelsync_settings")[0]["api_key_enc"] is None
    assert save(owner, url=URL, api_key=KEY).get_json()["key_set"] is True
    assert save(owner, url="http://third.test:4000", api_key=OTHER_KEY).get_json()["key_set"] is True    # a new key with the new address is the person's own choice
    assert save(owner, url="").get_json()["key_set"] is False                              # no address, no key


def test_clearing_the_address_switches_haspelsync_off(owner, typed):
    assert save(owner, url="").get_json()["enabled"] is False
    assert live(owner) == {"enabled": False, "printers": []}


def test_what_env_sets_wins_and_cannot_be_changed_in_the_app(owner, server):
    assert save(owner, url="http://other.test:1").status_code == 409
    res = save(owner, api_key=OTHER_KEY)
    assert res.status_code == 409 and "HASPELSYNC_API_KEY" in res.get_json()["error"]
    answer = status(owner)
    assert answer["url"] == URL and answer["url_from_env"] is True and answer["key_from_env"] is True and answer["ready"] is True
    assert sql(owner.application, "SELECT * FROM haspelsync_settings") == []


def test_an_address_from_env_takes_a_key_typed_in_the_app_and_never_the_other_way(owner, stand_in, app):
    app.config["APP_CONFIG"] = dataclasses.replace(app.config["APP_CONFIG"], haspelsync_url=URL)
    assert save(owner, api_key=KEY).status_code == 200
    assert status(owner)["ready"] is True and status(owner)["key_from_env"] is False
    assert save(owner, url="http://other.test:1").status_code == 409 and status(owner)["url"] == URL


def test_a_regular_user_sees_what_it_shows_but_not_where_it_is_or_whether_there_is_a_key(app, owner, typed):
    member = join_with_passkey(app, owner)
    answer = status(member)
    assert answer == {"enabled": True, "ready": True, "can_configure": False, "host": "haspelsync.test:4000"}
    assert member.put("/api/haspelsync/settings", json={"url": URL}, headers=H).status_code == 403
    assert member.post("/api/haspelsync/test", json={}, headers=H).status_code == 403
    assert member.get("/api/haspelsync/live").status_code == 200 and member.get("/api/haspelsync/printers").status_code == 200


def test_nobody_signed_out_gets_anything(client):
    for path in ("/api/haspelsync", "/api/haspelsync/live", "/api/haspelsync/printers"):
        assert client.get(path).status_code == 401


def test_neither_the_address_nor_the_key_is_in_a_backup(owner, typed):
    printer(owner)
    text = owner.get("/api/backup").get_data(as_text=True)
    assert "haspelsync.test" not in text and KEY not in text and "api_key_enc" not in text
    assert SERIAL in text                                                                  # what a printer here is called there is part of the printer


def test_a_key_that_can_no_longer_be_read_is_said_so_and_nothing_is_sent_with_it(owner, typed, app):
    """What SESSION_SECRET changing does to a sealed key: it cannot be opened any more (the secret itself stays: it would end the test's own session)."""
    printer(owner)
    sql(app, "UPDATE haspelsync_settings SET api_key_enc = %s", (passwords.seal("y" * 40, KEY.encode(), haspelsync.KEY_INFO).decode(),))
    answer = status(owner)
    assert answer["key_set"] is True and answer["key_readable"] is False and answer["ready"] is False
    entry = live(owner, EN)["printers"][0]
    assert entry["error"] == "haspelsync.key_unreadable" and "Enter the key again" in entry["message"] and typed.calls == []


def test_an_address_without_a_key_asks_for_one_and_sends_nothing(owner, stand_in):
    save(owner, url=URL)
    printer(owner)
    assert status(owner)["enabled"] is True and status(owner)["ready"] is False
    assert live(owner)["printers"][0]["error"] == "haspelsync.no_key" and stand_in.calls == []


# --- what is asked of HaspelSync ---------------------------------------------------------------------------------------

def test_only_a_get_on_the_four_fixed_routes_is_ever_made_and_always_with_the_key(owner, server):
    server.add()
    printer(owner)
    assert owner.post("/api/haspelsync/test", json={}, headers=H).status_code == 200
    live(owner)
    owner.get("/api/haspelsync/printers")
    assert set(server.paths()) == {"/api/printers", f"/api/status/{SERIAL}", f"/api/print/{SERIAL}"}
    assert {auth for _, auth in server.calls} == {f"Bearer {KEY}"}                          # the fake itself refuses any other method and any other address


def test_a_redirect_is_not_followed_so_the_key_goes_nowhere_else(owner, server):
    server.answer = Reply(302, b"")
    res = owner.post("/api/haspelsync/test", json={}, headers={**H, **EN})
    assert res.status_code == 502 and "redirects" in res.get_json()["error"] and len(server.calls) == 1


def test_a_serial_number_that_is_not_one_never_reaches_a_path(app, server):
    with app.test_request_context():
        for bad in ("../../api/settings", "A/B", "01P00A 0001", "abc", "", None, 5, "01P00A000000001/../x", "\n01P00A000000001"):
            with pytest.raises(haspelsync.HaspelSyncError) as error:
                haspelsync._get("print", bad)
            assert error.value.key == "haspelsync.bad_serial"
    assert server.calls == []


@pytest.mark.parametrize("code,fragment", [(401, "refuses the API key"), (403, "Allowed host names"), (302, "redirects"), (500, "status 500"), (404, "status 404")])
def test_what_haspelsync_refuses_is_said_in_words_and_is_never_a_401_of_ours(owner, server, code, fragment):
    server.codes["/api/printers"] = code
    res = owner.post("/api/haspelsync/test", json={}, headers={**H, **EN})
    assert res.status_code == 502 and fragment in res.get_json()["error"]


def test_a_refused_host_name_names_the_host_and_where_to_allow_it(owner, server):
    server.codes["/api/printers"] = 403
    assert "haspelsync.test" in owner.post("/api/haspelsync/test", json={}, headers={**H, **EN}).get_json()["error"]


def test_the_key_is_checked_by_haspelsync_and_a_wrong_one_is_refused_there(owner, stand_in):
    stand_in.key = OTHER_KEY
    save(owner, url=URL, api_key=KEY)
    res = owner.post("/api/haspelsync/test", json={}, headers={**H, **EN})
    assert res.status_code == 502 and "refuses the API key" in res.get_json()["error"]


def test_an_answer_that_is_not_json_or_too_big_is_not_trusted(owner, server, monkeypatch):
    server.answer = Reply(200, b"<html>not haspelsync</html>")
    assert owner.post("/api/haspelsync/test", json={}, headers=EN | H).status_code == 502
    monkeypatch.setattr(haspelsync, "MAX_BYTES", 100)
    server.answer = Reply(200, b"[" + b"0," * 200 + b"0]")
    assert "does not understand" in owner.post("/api/haspelsync/test", json={}, headers=EN | H).get_json()["error"]
    monkeypatch.setattr(haspelsync, "MAX_BYTES", 2 * 1024 * 1024)
    server.answer = Reply(200, b'{"not": "a list"}')
    assert owner.post("/api/haspelsync/test", json={}, headers=EN | H).status_code == 502


def test_haspelsync_that_is_down_is_said_so(owner, server):
    server.down = True
    res = owner.post("/api/haspelsync/test", json={}, headers={**H, **EN})
    assert res.status_code == 502 and "cannot be reached" in res.get_json()["error"]


def test_the_test_passes_on_a_verdict_and_a_count_and_nothing_else(owner, server):
    server.printers = [{"id": SERIAL, "name": "A", "ip": "192.168.1.60", "code": "12345678"}, {"id": SECOND, "name": "B"}]
    res = owner.post("/api/haspelsync/test", json={}, headers=H)
    assert res.get_json() == {"ok": True, "printers": 2} and "192.168" not in res.get_data(as_text=True)


def test_the_printers_of_haspelsync_come_as_serial_and_name_and_the_malformed_are_left_out(owner, server):
    server.printers = [{"id": SERIAL, "name": "P2S Werkplaats"}, {"id": SECOND}, {"id": "bad id!", "name": "x"}, {"id": 5, "name": "y"}, "text", {"name": "no id"},
                       {"id": "01p00a000000003", "name": "lowercase"}]
    assert owner.get("/api/haspelsync/printers").get_json() == [{"id": SERIAL, "name": "P2S Werkplaats"}, {"id": SECOND, "name": SECOND}]


# --- what is shown --------------------------------------------------------------------------------------------------------

def test_the_running_print_and_the_filament_of_a_printer_that_names_one(owner, server):
    server.add()
    printer(owner, name="Mijn P2S")
    answer = live(owner)
    assert answer["enabled"] is True and len(answer["printers"]) == 1
    entry = answer["printers"][0]
    assert (entry["name"], entry["serial"], entry["error"], entry["message"]) == ("Mijn P2S", SERIAL, None, None) and entry["printer_id"]
    view = entry["live"]
    assert (view["name"], view["connected"], view["monitoring"], view["last_report"]) == ("P2S Werkplaats", True, True, "2026-11-12T10:30:00+00:00")
    assert view["job"] == {"state": "RUNNING", "busy": True, "name": "Draak", "layer": 37, "total_layers": 150, "progress_pct": 25, "preparing": False,
                           "started_at": "2026-11-12T10:00:00+00:00", "elapsed_s": 1800, "remaining_min": 95, "ends_at": "2026-11-12T11:35:00+00:00"}
    red, green, empty = view["slots"]
    assert red == {"label": "A1", "loaded": True, "active": False, "material": "PLA", "vendor": "Bambu Lab", "name": "Rood", "colours": ["#ff0000"], "linked": True,
                   "remaining_g": 612.5, "initial_g": 1000.0, "remaining_pct": 61}
    assert (green["label"], green["active"], green["material"], green["colours"], green["linked"], green["remaining_g"], green["remaining_pct"]) == \
        ("A2", True, "PETG", ["#00ff00"], False, None, None)
    assert empty == {"label": "A3", "loaded": False, "active": False}
    assert view["uses"] == [{"slot": "A2", "needed_g": 42.3, "used_g": 10.4}]
    assert view["ams"] == [{"id": "A", "model": "AMS 2 Pro", "humidity": 2, "humidity_pct": 31, "temperature": 25, "drying": True, "drying_min": 95}]


def test_nothing_of_haspelsyncs_own_answer_is_passed_on(owner, server):
    server.add()
    printer(owner)
    text = json.dumps(live(owner))
    for private in ("SECRET-UUID", "SECRET-TAG", "secret-spoolman", "tray_uuid", "tag_uid", "SPOOLMAN_URL", "internal", "lastPrintSummary", "GFA00", "192."):
        assert private not in text, private


@pytest.mark.parametrize("layer,total,expected", [(15, 14, (15, 15, 100)), (99, 14, (15, 15, 100)), (0, 14, (0, 15, 0)), (7, None, (7, None, None)), (None, 14, (None, 15, None))])
def test_the_layers_count_the_way_haspelsync_does(owner, server, layer, total, expected):
    """The printer reports a count, the sliced file the index of its last layer: the total is one more, and nothing counts past it."""
    server.add(layerNum=layer, totalLayers=total)
    printer(owner)
    job = live(owner)["printers"][0]["live"]["job"]
    assert (job["layer"], job["total_layers"], job["progress_pct"]) == expected


def test_an_idle_printer_has_no_job(owner, server):
    server.add(gcodeState="IDLE", jobName=None, modelTitle=None, layerNum=0, totalLayers=None, fullConsumption=None, consumption=None, startedAt=None, elapsedMs=None,
               remainingMinutes=None, estimatedEndAt=None)
    server.status[SERIAL]["gcodeState"] = "IDLE"
    printer(owner)
    job = live(owner)["printers"][0]["live"]["job"]
    assert (job["state"], job["busy"], job["name"], job["progress_pct"], job["started_at"], job["ends_at"], job["remaining_min"]) == ("IDLE", False, None, None, None, None, None)
    assert live(owner)["printers"][0]["live"]["uses"] == []


def test_a_job_named_after_a_profile_is_shown_by_the_name_the_printer_reports_when_there_is_no_model_title(owner, server):
    server.add(modelTitle=None)
    printer(owner)
    assert live(owner)["printers"][0]["live"]["job"]["name"] == "0.2mm layer, 2 walls"


def test_a_short_answer_for_a_print_whose_file_could_not_be_read_still_shows_the_slots(owner, server):
    server.add(error="FTPS fetch failed: nope", loadedSpools=[], fullConsumption=None, consumption=None, sliceInfo=None)
    printer(owner)
    view = live(owner)["printers"][0]["live"]
    assert f"/api/spools/{SERIAL}" in server.paths() and [s["label"] for s in view["slots"]] == ["A1", "A2", "A3"] and view["uses"] == []


def test_a_malformed_answer_gives_missing_fields_and_never_an_error_or_raw_text(owner, server):
    huge = "x" * 5000
    server.add(gcodeState="EXPLODING", jobName=huge, modelTitle=["no"], layerNum="many", totalLayers=float("inf"), remainingMinutes=-5, elapsedMs=True,
               startedAt=10**30, estimatedEndAt="soon", preparing="yes", fullConsumption={"0": "text", "1": {"amsId": "../../x", "grams": 5}, "2": {"amsId": "B2", "grams": 10**9}},
               consumption=[1, 2],
               loadedSpools=[{"amsId": "A1", "slotState": "Loaded (Bambu Lab)", "material": huge, "vendor": 5, "filamentName": None,
                              "slot": {"cols": ["red", "FF00", "00FF00FF", 5, None] + ["112233"] * 20, "tray_color": 7},
                              "existingSpool": {"remaining_weight": "lots", "initial_weight": float("nan"), "remaining_percentage": 10**9, "filament": {"color_hex": "<script>"}}},
                             "not a slot", {"amsId": "../x", "slotState": "Empty"}, {"amsId": "A9", "slotState": 5}])
    server.status[SERIAL].update(mqttStatus=["x"], lastMqttUpdate="yesterday", printerName=huge, amsEnv=[{"amsId": "A", "humidity": 99, "temperature": "hot", "drying": "yes"}, 5, {"amsId": "!!"}],
                                 activeSlot={"a": 1})
    server.status[SERIAL]["gcodeState"] = 5
    printer(owner)
    res = owner.get("/api/haspelsync/live")
    assert res.status_code == 200
    view = res.get_json()["printers"][0]["live"]
    job = view["job"]
    assert (job["state"], job["busy"], job["layer"], job["total_layers"], job["progress_pct"], job["remaining_min"], job["elapsed_s"], job["started_at"], job["ends_at"],
            job["preparing"]) == (None, False, None, None, None, 0, None, None, None, False)
    assert len(job["name"]) == 200 and view["connected"] is False and view["last_report"] is None and len(view["name"]) == 80
    assert view["uses"] == [{"slot": "B2", "needed_g": 100000.0, "used_g": None}]
    loaded, unknown, bad_state = view["slots"][0], view["slots"][1:], None
    assert len(loaded["material"]) == 40 and loaded["vendor"] is None and loaded["name"] is None
    assert loaded["colours"] == ["#00ff00", "#112233", "#112233", "#112233"]            # only the first eight entries are looked at, and only the real colours stay
    assert (loaded["remaining_g"], loaded["initial_g"], loaded["remaining_pct"]) == (None, None, 100)
    assert [s["label"] for s in unknown] == ["A9"] and unknown[0]["loaded"] is False
    assert view["ams"] == [{"id": "A", "model": None, "humidity": 5, "humidity_pct": None, "temperature": None, "drying": False, "drying_min": None}]
    assert "<script>" not in res.get_data(as_text=True)


def test_a_json_nan_is_not_a_number_that_gets_through(owner, server):
    server.add()
    printer(owner)
    server.print[SERIAL]["layerNum"] = float("nan")                                    # json.dumps writes NaN, json.loads reads it back as a float
    assert live(owner)["printers"][0]["live"]["job"]["layer"] is None


def test_the_percentage_of_a_roll_is_worked_out_when_spoolman_gives_only_the_weights(owner, server):
    server.add()
    server.spools[SERIAL][0]["existingSpool"].pop("remaining_percentage")
    server.print[SERIAL]["loadedSpools"] = server.spools[SERIAL]
    printer(owner)
    assert live(owner)["printers"][0]["live"]["slots"][0]["remaining_pct"] == 61


def test_a_printer_that_haspelsync_does_not_know_says_so_in_the_language_of_the_person_and_the_others_are_shown(owner, server):
    server.add()
    printer(owner, name="Bekend")
    printer(owner, name="Onbekend", serial=SECOND)
    nl, en = live(owner, NL)["printers"], live(owner, EN)["printers"]
    assert [p["name"] for p in nl] == ["Bekend", "Onbekend"] and nl[0]["live"] and nl[0]["error"] is None
    assert nl[1]["live"] is None and nl[1]["error"] == "haspelsync.not_found" and SECOND in nl[1]["message"] and "kent geen printer" in nl[1]["message"]
    assert "does not know a printer" in en[1]["message"]


def test_when_the_address_fails_the_printers_after_the_first_are_not_asked_at_all(owner, server):
    server.down = True
    for n, serial in enumerate((SERIAL, SECOND, "01P00A000000003")):
        printer(owner, name=f"P{n}", serial=serial)
    shown = live(owner, EN)["printers"]
    assert [p["error"] for p in shown] == ["haspelsync.unreachable"] * 3 and all("cannot be reached" in p["message"] for p in shown)
    assert len(server.calls) == 1


def test_a_printer_that_is_archived_or_names_nothing_is_not_asked(owner, server):
    server.add()
    printer(owner, name="Gearchiveerd", archived=True)
    printer(owner, name="Zonder", serial=None)
    printer(owner, name="Leeg", serial="")
    assert live(owner)["printers"] == [] and server.calls == []
    printer(owner, name="Wel", serial=SECOND)
    assert [p["name"] for p in live(owner)["printers"]] == ["Wel"]


def test_a_screen_that_asks_every_few_seconds_costs_haspelsync_one_look_per_few_seconds(owner, server, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(haspelsync, "clock", lambda: now[0])
    server.add()
    printer(owner)
    live(owner)
    asked = len(server.calls)
    assert asked == 2                                                                   # the status and the print; the slots came with the print
    now[0] += haspelsync.CACHE_SECONDS - 0.5
    live(owner)
    assert len(server.calls) == asked
    server.print[SERIAL]["layerNum"] = 60
    now[0] += 1
    assert live(owner)["printers"][0]["live"]["job"]["layer"] == 60 and len(server.calls) == 2 * asked


def test_a_failure_is_remembered_as_briefly_and_a_new_address_forgets_it_at_once(owner, stand_in):
    stand_in.add()
    stand_in.down = True
    save(owner, url=URL, api_key=KEY)
    printer(owner)
    assert live(owner)["printers"][0]["error"] == "haspelsync.unreachable"
    stand_in.down = False
    assert live(owner)["printers"][0]["error"] == "haspelsync.unreachable"            # still the remembered answer
    save(owner, url=URL, api_key=KEY)
    assert live(owner)["printers"][0]["error"] is None


# --- the serial number of a printer here ------------------------------------------------------------------------------------

def test_a_serial_number_is_kept_in_upper_case_and_can_be_changed_and_cleared(owner):
    made = printer(owner, serial="01p00a000000001 ")
    assert made["haspelsync_serial"] == SERIAL
    patched = owner.patch(f"/api/printers/{made['id']}", json={"haspelsync_serial": SECOND.lower()}, headers=H)
    assert patched.status_code == 200 and patched.get_json()["haspelsync_serial"] == SECOND
    assert owner.patch(f"/api/printers/{made['id']}", json={"name": "Anders"}, headers=H).get_json()["haspelsync_serial"] == SECOND       # a save without it leaves it
    assert owner.patch(f"/api/printers/{made['id']}", json={"haspelsync_serial": ""}, headers=H).get_json()["haspelsync_serial"] == ""
    assert printer(owner, name="Zonder", serial=None)["haspelsync_serial"] == ""


@pytest.mark.parametrize("bad", ["../../api/settings", "A/B", "A B C D E F", "abc", "01P00A00000000é", "01P00A\n000000001", ["01P00A000000001"], {"a": 1}, 5, "A" * 33])
def test_a_serial_number_that_cannot_be_one_is_refused(owner, bad):
    res = owner.post("/api/printers", json={"name": "P", "purchase_price": 1, "lifetime_hours": 1, "haspelsync_serial": bad}, headers={**H, **EN})
    assert res.status_code == 400 and "Serial number" in res.get_json()["error"]
    assert owner.get("/api/printers").get_json() == []


def test_one_printer_of_haspelsync_is_one_printer_here(owner):
    first = printer(owner, name="Eerste")
    res = owner.post("/api/printers", json={"name": "Tweede", "purchase_price": 1, "lifetime_hours": 1, "haspelsync_serial": SERIAL.lower()}, headers={**H, **NL})
    assert res.status_code == 409 and "Eerste" in res.get_json()["error"]
    second = printer(owner, name="Tweede", serial=SECOND)
    taken = owner.patch(f"/api/printers/{second['id']}", json={"haspelsync_serial": SERIAL}, headers={**H, **EN})
    assert taken.status_code == 409 and "Eerste" in taken.get_json()["error"]
    assert owner.patch(f"/api/printers/{first['id']}", json={"haspelsync_serial": SERIAL, "name": "Eerste (nieuw)"}, headers=H).status_code == 200     # its own is not a clash
    owner.patch(f"/api/printers/{first['id']}", json={"archived": True}, headers=H)
    assert owner.patch(f"/api/printers/{second['id']}", json={"haspelsync_serial": SERIAL}, headers=H).status_code == 409    # an archived printer keeps it
    owner.patch(f"/api/printers/{first['id']}", json={"haspelsync_serial": ""}, headers=H)
    assert owner.patch(f"/api/printers/{second['id']}", json={"haspelsync_serial": SERIAL}, headers=H).status_code == 200


def test_the_database_insists_on_it_too(owner, app):
    printer(owner)
    with pytest.raises(sqlite3.IntegrityError):
        sql(app, "INSERT INTO printers (name, purchase_price, lifetime_hours, haspelsync_serial) VALUES ('Dubbel', 1, 1, %s)", (SERIAL,))
    sql(app, "INSERT INTO printers (name, purchase_price, lifetime_hours) VALUES ('Zonder 1', 1, 1)")
    sql(app, "INSERT INTO printers (name, purchase_price, lifetime_hours) VALUES ('Zonder 2', 1, 1)")                  # any number may name none


def test_the_serial_number_goes_through_a_backup_and_a_restore(owner):
    printer(owner)
    doc = owner.get("/api/backup").get_json()
    assert [p["haspelsync_serial"] for p in doc["printers"]] == [SERIAL]
    owner.delete(f"/api/printers/{owner.get('/api/printers').get_json()[0]['id']}", headers=H)
    assert post(owner, "/api/backup/restore", doc).status_code == 200
    assert [p["haspelsync_serial"] for p in owner.get("/api/printers").get_json()] == [SERIAL]


def test_a_backup_from_before_haspelsync_restores_with_no_serial_number(owner):
    printer(owner)
    doc = owner.get("/api/backup").get_json()
    for row in doc["printers"]:
        row.pop("haspelsync_serial")
    assert post(owner, "/api/backup/restore", doc).status_code == 200
    assert [p["haspelsync_serial"] for p in owner.get("/api/printers").get_json()] == [""]


def test_a_backup_that_names_one_serial_number_twice_gives_it_to_the_first_only(owner):
    printer(owner)
    doc = owner.get("/api/backup").get_json()
    doc["printers"].append({**doc["printers"][0], "id": "11111111-1111-1111-1111-111111111111", "name": "Tweede"})
    res = post(owner, "/api/backup/restore", doc)
    assert res.status_code == 200, res.get_json()
    assert sorted((p["name"], p["haspelsync_serial"]) for p in owner.get("/api/printers").get_json()) == [("P2S", SERIAL), ("Tweede", "")]


# --- the state of the connection, for the badge on its card ----------------------------------------------------------

def connection(client, lang="en"):
    res = client.get("/api/haspelsync/connection", headers={"X-Lang": lang})
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def test_the_connection_is_off_until_there_is_an_address_and_a_key(owner, stand_in):
    assert connection(owner) == {"state": "off", "message": None, "printers": None}
    save(owner, url=URL)
    state = connection(owner)
    assert state["state"] == "off" and "No API key" in state["message"] and stand_in.calls == []        # nothing is asked without a key
    save(owner, api_key=KEY)
    assert connection(owner)["state"] == "active"


def test_the_connection_is_active_and_counts_the_printers(owner, server):
    server.printers = [{"id": SERIAL, "name": "A"}, {"id": SECOND, "name": "B"}]
    assert connection(owner) == {"state": "active", "message": None, "printers": 2}


@pytest.mark.parametrize("code,fragment", [(401, "refuses the API key"), (403, "Allowed host names"), (500, "status 500")])
def test_the_connection_is_offline_and_says_why_in_the_language_of_the_person(owner, server, code, fragment):
    server.codes["/api/printers"] = code
    state = connection(owner)
    assert state["state"] == "offline" and fragment in state["message"] and state["printers"] is None


def test_the_connection_is_offline_when_haspelsync_is_down(owner, typed):
    typed.down = True
    assert "cannot be reached" in connection(owner)["message"] and "niet bereikbaar" in connection(owner, "nl")["message"]


def test_the_connection_is_offline_when_the_key_cannot_be_read_and_nothing_is_sent_with_it(owner, typed, app):
    sql(app, "UPDATE haspelsync_settings SET api_key_enc = %s", (passwords.seal("y" * 40, KEY.encode(), haspelsync.KEY_INFO).decode(),))
    state = connection(owner)
    assert state["state"] == "offline" and "Enter the key again" in state["message"] and typed.calls == []


def test_everybody_signed_in_may_ask_for_the_state_and_nobody_else(app, owner, server):
    assert connection(join_with_passkey(app, owner))["state"] == "active"
    assert app.test_client().get("/api/haspelsync/connection").status_code == 401
