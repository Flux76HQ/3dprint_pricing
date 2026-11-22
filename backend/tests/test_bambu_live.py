"""The live view of a Bambu Lab printer through the Bambu cloud: who the account is, the connection that is only open while somebody looks, the reports merged
as they come, what a screen gets of them (every field named and clamped), which roll is in a slot, and that the app only ever asks for a full report.
A test never reaches Bambu: `bambu_cloud.transport` is `Cloud` and `bambu_live.make_client` is `FakeClient`."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import bambu_cloud, bambu_live
from tests.test_auth_api import H
from tests.test_bambu_cloud import API, Cloud, sign_in, spool, sync
from tests.test_domain_api import make, owner  # noqa: F401  (fixture)
from tests.test_users import join_with_passkey, sql

SERIAL = "01P00A123456789"
NL = {"X-Lang": "nl"}


class Devices(Cloud):
    """The Bambu cloud of `test_bambu_cloud`, with the account's printers and its preference (the uid)."""

    def __init__(self):
        super().__init__()
        self.devices = [{"dev_id": SERIAL, "name": "Werkbank", "online": True, "dev_access_code": "93847561", "print_status": "RUNNING"},
                        {"dev_id": "03W00X987654321", "name": "Zolder"}, {"dev_id": "../etc", "name": "kwaad"}]

    def __call__(self, method, url, *, headers, body):
        if url in (API + bambu_live.DEVICES, API + bambu_live.PREFERENCE) and headers.get("Authorization") != f"Bearer {self.token}":
            return bambu_cloud.Reply(401, b'{"code": 401}')
        if url == API + bambu_live.DEVICES:
            self.calls.append((method, url, headers, body))
            return bambu_cloud.Reply(200, json.dumps({"message": "success", "devices": self.devices}).encode())
        if url == API + bambu_live.PREFERENCE:
            self.calls.append((method, url, headers, body))
            return bambu_cloud.Reply(200, json.dumps({"uid": 1234567, "name": "maker"}).encode())
        return super().__call__(method, url, headers=headers, body=body)


class Message:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload if isinstance(payload, bytes) else json.dumps(payload).encode()


class FakeClient:
    """A stand-in for paho's client: it records what the app does and lets a test play the broker."""

    made = []

    def __init__(self, client_id):
        self.client_id, self.subscribed, self.published, self.unsubscribed = client_id, [], [], []
        self.login = self.address = None
        self.running = self.disconnected = False
        FakeClient.made.append(self)

    def username_pw_set(self, user, password):
        self.login = (user, password)

    def connect_async(self, host, port, keepalive):
        self.address = (host, port, keepalive)

    def loop_start(self):
        self.running = True

    def loop_stop(self):
        self.running = False

    def disconnect(self):
        self.disconnected = True

    def subscribe(self, topic):
        self.subscribed.append(topic)

    def unsubscribe(self, topic):
        self.unsubscribed.append(topic)

    def publish(self, topic, payload):
        self.published.append((topic, payload))

    # the broker
    def accept(self, code=0):
        self.on_connect(self, None, {}, code, None)

    def deliver(self, payload, serial=SERIAL, topic=None):
        self.on_message(self, None, Message(topic or f"device/{serial}/report", payload))


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    FakeClient.made = []
    monkeypatch.setattr(bambu_live, "make_client", FakeClient)
    bambu_live.close()
    bambu_live._users.clear()
    bambu_live._devices.clear()
    yield
    bambu_live.close()


@pytest.fixture
def cloud(monkeypatch):
    fake = Devices()
    monkeypatch.setattr(bambu_cloud, "transport", fake)
    return fake


@pytest.fixture
def ready(owner, cloud):
    """Signed in, with a printer here that is the account's printer."""
    assert sign_in(owner).get_json()["step"] == "done"
    make(owner, "/api/printers", {"name": "Bambu P1S", "purchase_price": "700", "lifetime_hours": "3000", "power_kw": "0.15", "haspelsync_serial": SERIAL})
    return cloud


def live(client, lang="en"):
    res = client.get("/api/bambu-cloud/live", headers={"X-Lang": lang})
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def tray(n, material="PLA", colour="FF6A13FF", remain=80, weight="1000", tag="0000000000000000", **more):
    return {"id": str(n), "tray_type": material, "tray_sub_brands": f"{material} Basic", "tray_color": colour, "cols": [colour], "remain": remain,
            "tray_weight": weight, "tag_uid": tag, "tray_uuid": "5F3D8925633343C29FB9A97FA9125971", "tray_id_name": "A00-A0", **more}


def report(**more):
    return {"print": {"gcode_state": "RUNNING", "mc_percent": 42, "mc_remaining_time": 75, "layer_num": 120, "total_layer_num": 300,
                      "subtask_name": "Gearbox housing", "gcode_start_time": "1794750000", "nozzle_temper": 220.5,
                      "ams": {"tray_now": "1", "ams": [{"id": "0", "humidity": "4", "humidity_raw": "23", "temp": "26.2", "dry_time": 0,
                                                       "tray": [tray(0), tray(1, colour="000000FF", remain=-1, weight="0"), {"id": "2"}, tray(3, material="PETG")]}]},
                      "vt_tray": {"id": "254", "tray_type": "", "tray_color": "00000000"}, **more}}


def connected(owner):
    """The first call opens the connection; the broker accepts it."""
    first = live(owner)
    client = FakeClient.made[-1]
    client.accept()
    return first, client


# --- who the account is, and the connection ----------------------------------------------------------------------------------------

def test_without_a_sign_in_there_is_no_live_view(owner, cloud):
    assert live(owner) == {"enabled": False, "printers": []}
    assert FakeClient.made == []


def test_without_a_linked_printer_nothing_is_opened(owner, cloud):
    sign_in(owner)
    assert live(owner) == {"enabled": True, "printers": []}
    assert FakeClient.made == []


def test_the_connection_signs_in_as_the_account_with_its_token_at_the_fixed_broker(owner, ready):
    first, client = connected(owner)
    assert client.login == ("u_1234567", ready.token)                     # the uid from Bambu's preference route: this token carries none
    assert client.address == ("us.mqtt.bambulab.com", 8883, bambu_live.KEEPALIVE) and client.running
    assert client.subscribed == [f"device/{SERIAL}/report"]
    assert client.published == [(f"device/{SERIAL}/request", bambu_live.PUSHALL)]
    entry = first["printers"][0]
    assert (entry["serial"], entry["live"], entry["error"]) == (SERIAL, None, "bambu.live_waiting")


def test_the_user_name_is_read_from_a_token_that_carries_it(owner, ready):
    assert bambu_live.user_name(_jwt({"username": "u_42"})) == "u_42"
    assert not any(url.endswith(bambu_live.PREFERENCE) for _, url, _, _ in ready.calls)


def _jwt(claims):
    import jwt
    return jwt.encode(claims, "x" * 32, algorithm="HS256")


def test_the_china_region_reads_at_its_own_broker(app, owner, ready):
    sql(app, "UPDATE bambu_cloud_settings SET region = 'china'")
    bambu_live._users[hashlib.sha256(ready.token.encode()).hexdigest()] = "u_1234567"     # known already: this stand-in only answers at the global cloud
    live(owner)
    assert FakeClient.made[-1].address[0] == "cn.mqtt.bambulab.com"


def test_one_connection_per_worker_and_a_new_one_for_a_new_sign_in(owner, ready):
    connected(owner)
    live(owner)
    assert len(FakeClient.made) == 1
    ready.token = bambu_live.__name__ + "-another-token-value"
    sign_in(owner)
    live(owner)
    assert len(FakeClient.made) == 2 and FakeClient.made[0].disconnected and FakeClient.made[0].running is False


def test_a_connection_nobody_asks_for_closes(owner, ready):
    _, client = connected(owner)
    bambu_live.reap_once()
    assert bambu_live._listener is not None and not client.disconnected                # asked for just now: kept
    bambu_live._listener.asked -= bambu_live.IDLE_SECONDS + 1
    bambu_live.reap_once()
    assert bambu_live._listener is None and client.disconnected and client.running is False
    live(owner)
    assert len(FakeClient.made) == 2                                                    # the next look opens a new one


def test_signing_out_closes_the_connection(owner, ready):
    _, client = connected(owner)
    owner.delete("/api/bambu-cloud/login", headers=H)
    assert client.disconnected and bambu_live._listener is None
    assert live(owner) == {"enabled": False, "printers": []}


def test_a_refused_token_says_to_sign_in_again_and_does_not_knock_again(owner, ready):
    live(owner)
    client = FakeClient.made[-1]
    client.accept(code=5)
    entry = live(owner, "nl")["printers"][0]
    assert entry["error"] == "bambu.expired" and "verlopen" in entry["message"] and client.disconnected
    assert client.subscribed == [] and client.published == []


def test_a_printer_that_does_not_report_says_so_after_a_while(owner, ready):
    connected(owner)
    bambu_live._listener.opened -= timedelta(seconds=bambu_live.WAIT_SECONDS + 1)
    assert live(owner)["printers"][0]["error"] == "bambu.live_silent"
    bambu_live._listener.connected = False
    assert live(owner)["printers"][0]["error"] == "bambu.live_no_connection"


def test_the_app_only_ever_asks_for_a_full_report(owner, ready):
    _, client = connected(owner)
    client.deliver({"event": {"event": "client.disconnected"}})
    client.deliver({"event": {"event": "client.connected"}})
    client.deliver(report())
    live(owner)
    assert client.published and all(json.loads(payload) == {"pushing": {"sequence_id": "0", "command": "pushall"}} for _, payload in client.published)
    assert all(topic == f"device/{SERIAL}/request" for topic, _ in client.published)


def test_a_printer_that_is_unlinked_is_no_longer_followed(app, owner, ready):
    _, client = connected(owner)
    sql(app, "UPDATE printers SET haspelsync_serial = '03W00X987654321'")
    live(owner)
    assert client.unsubscribed == [f"device/{SERIAL}/report"] and client.subscribed[-1] == "device/03W00X987654321/report"


# --- what a screen gets -------------------------------------------------------------------------------------------------------------

def test_a_report_becomes_the_view_the_panel_draws(owner, ready):
    _, client = connected(owner)
    client.deliver(report())
    view = live(owner)["printers"][0]["live"]
    assert view["connected"] is True and view["last_report"]
    job = view["job"]
    assert (job["state"], job["busy"], job["name"], job["layer"], job["total_layers"], job["progress_pct"], job["remaining_min"]) == \
        ("RUNNING", True, "Gearbox housing", 120, 300, 42, 75)
    assert job["ends_at"] and job["started_at"].startswith("2026-11-15")
    slots = {s["label"]: s for s in view["slots"]}
    assert list(slots) == ["A1", "A2", "A3", "A4"]                                      # the empty external holder is left out
    assert slots["A2"]["active"] is True and slots["A1"]["active"] is False
    assert (slots["A1"]["material"], slots["A1"]["colours"], slots["A1"]["remaining_g"], slots["A1"]["remaining_pct"], slots["A1"]["estimate"]) == \
        ("PLA", ["#ff6a13"], 800.0, 80, True)                                         # the AMS's own estimate: 80% of 1000 g
    assert slots["A2"]["remaining_g"] is None and slots["A2"]["linked"] is False       # no estimate (-1): nothing made up
    assert slots["A3"] == {"label": "A3", "loaded": False, "active": False}
    assert view["ams"] == [{"id": "A", "model": None, "humidity": 4, "humidity_pct": 23, "temperature": 26, "drying": False, "drying_min": None}]


def test_a_partial_report_is_laid_over_what_is_known(owner, ready):
    _, client = connected(owner)
    client.deliver(report())
    client.deliver({"print": {"layer_num": 121, "ams": {"ams": [{"id": "0", "tray": [{"id": "0", "remain": 79}]}]}}})
    view = live(owner)["printers"][0]["live"]
    slots = {s["label"]: s for s in view["slots"]}
    assert view["job"]["layer"] == 121 and view["job"]["name"] == "Gearbox housing"
    assert slots["A1"]["remaining_pct"] == 79 and slots["A1"]["material"] == "PLA" and slots["A4"]["material"] == "PETG"


def test_what_is_not_a_report_of_a_followed_printer_is_dropped(owner, ready):
    _, client = connected(owner)
    client.deliver(report(), serial="03W00X987654321")
    assert bambu_live._listener.reports == {}                                          # not even kept: it is not a printer here
    client.deliver(b"not json")
    client.deliver([1, 2, 3])
    client.deliver(report(), topic=f"device/{SERIAL}/request")
    client.deliver(json.dumps(report(padding="x" * bambu_live.MAX_PAYLOAD)).encode())          # a report, but larger than any report is
    assert live(owner)["printers"][0]["live"] is None


def test_every_field_is_clamped_and_a_wrong_type_is_a_missing_field(owner, ready):
    _, client = connected(owner)
    client.deliver({"print": {"gcode_state": "<script>", "layer_num": 999_999_999, "total_layer_num": "x", "mc_percent": 250, "mc_remaining_time": -5,
                              "subtask_name": "a" * 1000, "gcode_start_time": True,
                              "ams": {"tray_now": "nonsense", "ams": [{"id": "99"}, {"id": "0", "humidity": "9", "humidity_raw": "-3", "temp": "NaN",
                                                                    "tray": [tray(0, colour="javascript:", remain=500, weight="1e12"), {"id": "x"}]}]}}})
    view = live(owner)["printers"][0]["live"]
    job = view["job"]
    assert job["state"] is None and job["total_layers"] is None and job["progress_pct"] == 100 and job["remaining_min"] == 0 and len(job["name"]) == 200
    assert job["started_at"] is None
    assert [s["label"] for s in view["slots"]] == ["A1"]                              # AMS 99 and a slot without a number are left out
    slot = view["slots"][0]
    assert slot["colours"] == [] and slot["remaining_pct"] == 100 and slot["remaining_g"] == 100_000
    assert view["ams"][0]["humidity"] == 5 and view["ams"][0]["humidity_pct"] == 0 and view["ams"][0]["temperature"] is None


def test_the_cloud_saying_a_printer_went_away_shows_it_offline(owner, ready):
    _, client = connected(owner)
    client.deliver(report())
    client.deliver({"event": {"event": "client.disconnected"}})
    assert live(owner)["printers"][0]["live"]["connected"] is False


def test_an_ams_ht_and_a_second_external_holder_get_their_own_names(owner, ready):
    _, client = connected(owner)
    client.deliver({"print": {"ams": {"tray_now": "128", "ams": [{"id": "128", "tray": [tray(0)]}]},
                              "vir_slot": [tray(254), tray(255, material="PETG")]}})
    slots = {s["label"]: s for s in live(owner)["printers"][0]["live"]["slots"]}
    assert list(slots) == ["HT-A", "Ext", "Ext-2"] and slots["HT-A"]["active"] is True


# --- which roll is in a slot ----------------------------------------------------------------------------------------------------------

CHIP = "DE6CF07300000100"


def test_a_sync_keeps_a_trace_of_the_chip_and_the_slot_but_never_the_chip(app, owner, ready):
    ready.spools = [spool(1, RFID=CHIP, inPrinter=True, devId=SERIAL, amsId=0, slotId="2"), spool(2, colour="#FFFFFF")]
    sync(owner)
    rows = {r["bambu_id"]: r for r in sql(app, "SELECT bambu_id, bambu_tag, bambu_slot FROM filament_spools")}
    assert rows[1]["bambu_tag"] == hashlib.sha256(CHIP.encode()).hexdigest() and rows[1]["bambu_slot"] == f"{SERIAL}/0/2"
    assert rows[2]["bambu_tag"] == "" and rows[2]["bambu_slot"] == ""
    assert CHIP not in json.dumps(owner.get("/api/spools").get_json()) and CHIP not in json.dumps(owner.get("/api/backup").get_json())
    ready.spools[0]["inPrinter"] = False
    sync(owner)
    assert sql(app, "SELECT bambu_slot FROM filament_spools WHERE bambu_id = 1")[0]["bambu_slot"] == ""


def test_a_slot_is_the_roll_whose_chip_it_reads(owner, ready):
    ready.spools = [spool(1, RFID=CHIP, colour="#FF6A13", net=640)]
    sync(owner)
    roll = [r for r in owner.get("/api/spools").get_json() if r["bambu_id"] == 1][0]
    _, client = connected(owner)
    client.deliver(report(ams={"tray_now": "255", "ams": [{"id": "0", "tray": [tray(0, tag=CHIP)]}]}))
    slot = live(owner)["printers"][0]["live"]["slots"][0]
    assert (slot["linked"], slot["roll_id"], slot["remaining_g"], slot["initial_g"], slot["remaining_pct"], slot["estimate"]) == \
        (True, roll["id"], 640.0, 1000.0, 64, False)                                  # what the shelf says, write-backs included
    assert slot["vendor"] == "Bambu Lab" and slot["name"] == f"Basic {roll['colour']}"


def test_a_slot_is_the_roll_the_filament_manager_last_saw_there_when_the_material_agrees(app, owner, ready):
    ready.spools = [spool(1, inPrinter=True, devId=SERIAL, amsId=0, slotId=3, material="PETG", name="PETG HF", colour="#1F79E5")]
    sync(owner)
    _, client = connected(owner)
    client.deliver(report())
    slots = {s["label"]: s for s in live(owner)["printers"][0]["live"]["slots"]}
    assert slots["A4"]["linked"] is True and slots["A1"]["linked"] is False
    sql(app, "UPDATE filament_spools SET material = 'ABS' WHERE bambu_id = 1")        # the AMS reports PETG there: not this roll
    slots = {s["label"]: s for s in live(owner)["printers"][0]["live"]["slots"]}
    assert slots["A4"]["linked"] is False


def test_a_slot_is_never_a_roll_by_its_colour(owner, ready):
    ready.spools = [spool(1, colour="#FF6A13")]                                         # same colour and material as A1, no chip, no place
    sync(owner)
    _, client = connected(owner)
    client.deliver(report())
    assert live(owner)["printers"][0]["live"]["slots"][0]["linked"] is False


def test_the_calculation_editor_knows_there_is_a_live_source(owner, ready):
    assert owner.get("/api/model-editor").get_json()["bambu_cloud"] == {"enabled": True}


# --- the printers of the account, and who may ------------------------------------------------------------------------------------

def test_the_printers_of_the_account_are_listed_without_their_access_code(owner, ready):
    res = owner.get("/api/bambu-cloud/printers")
    assert res.status_code == 200
    assert res.get_json() == [{"id": SERIAL, "name": "Werkbank"}, {"id": "03W00X987654321", "name": "Zolder"}]
    assert "93847561" not in res.get_data(as_text=True)
    owner.get("/api/bambu-cloud/printers")
    assert sum(1 for _, url, _, _ in ready.calls if url.endswith(bambu_live.DEVICES)) == 1          # kept for a minute


def test_the_printers_need_a_sign_in(owner, cloud):
    assert owner.get("/api/bambu-cloud/printers").status_code == 400


def test_everybody_signed_in_may_look_and_nobody_else(app, owner, ready):
    member = join_with_passkey(app, owner)
    assert member.get("/api/bambu-cloud/printers").status_code == 200
    assert live(member)["enabled"] is True
    anonymous = app.test_client()
    assert anonymous.get("/api/bambu-cloud/live").status_code == 401 and anonymous.get("/api/bambu-cloud/printers").status_code == 401


def test_an_expired_sign_in_is_said_per_printer_before_anything_is_opened(app, owner, ready):
    ready.token = "a-token-that-is-not-a-jwt-and-not-the-one-the-app-has"
    bambu_live._users.clear()
    entry = live(owner)["printers"][0]
    assert entry["error"] == "bambu.expired" and entry["live"] is None and FakeClient.made == []


def test_merge_lays_lists_of_numbered_items_over_each_other_and_replaces_the_rest():
    old = {"a": 1, "list": [{"id": "0", "x": 1}, {"id": "1", "x": 2}], "plain": [1, 2]}
    new = {"b": 2, "list": [{"id": "1", "x": 3}], "plain": [3]}
    assert bambu_live.merge(old, new) == {"a": 1, "b": 2, "list": [{"id": "0", "x": 1}, {"id": "1", "x": 3}], "plain": [3]}
