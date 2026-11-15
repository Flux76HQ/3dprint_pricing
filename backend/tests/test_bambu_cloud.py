"""The Filament Manager of Bambu Lab as the source of the rolls: signing in (with a mailed code or an authenticator app), the sync, a roll that is one
row wherever it was entered, what the cloud keeps and what the app keeps, writing back what a calculation used, and one source at a time.
A test never reaches Bambu: `bambu_cloud.transport` is replaced by `Cloud`."""
import dataclasses
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app import bambu_cloud, passwords
from app.i18n import L, render
from tests.test_auth_api import H, post
from tests.test_domain_api import make, owner, sheet_payload  # noqa: F401  (fixture)
from tests.test_users import join_with_passkey, sql

API, WEB = "https://api.bambulab.com", "https://bambulab.com"
EMAIL, PASSWORD = "maker@example.org", "s3cret-Pa55word"
NL = {"X-Lang": "nl"}


def token(days=90):
    return jwt.encode({"exp": int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp()), "uid": 1}, "not-bambus-key", algorithm="HS256")


def spool(number, *, vendor="Bambu Lab", name="PLA Basic", material="PLA", colour="#000000FF", net=800, total=1000, tray="", note="", **more):
    return {"id": number, "createType": "ams" if tray else "manual", "filamentVendor": vendor, "filamentType": material, "filamentName": name,
            "filamentId": "GFA00", "RFID": "", "color": colour, "colorType": 2, "colors": [colour], "netWeight": net, "totalNetWeight": total,
            "note": note, "status": 0, "trayIdName": tray, "category": material, **more}


class Cloud:
    """A stand-in for the Bambu cloud: it signs in, holds spools, pages them and takes edits. `login` is how the account signs in: `token` at once,
    `code` with a mailed code, `tfa` with an authenticator app."""

    def __init__(self):
        self.login, self.spools, self.calls, self.puts = "token", [], [], []
        self.token, self.code, self.tfa_code = token(), "123456", "654321"
        self.down = self.blocked = self.refuse_puts = False
        self.answer = None                                           # a Reply that answers every call

    def __call__(self, method, url, *, headers, body):
        self.calls.append((method, url, headers, body))
        if self.down:
            raise bambu_cloud.BambuCloudError("bambu.unreachable")
        if self.blocked:
            return bambu_cloud.Reply(403, b"<html>Attention Required! | Cloudflare</html>")
        if self.answer:
            return self.answer
        reply = lambda doc, status=200, cookies=None: bambu_cloud.Reply(status, json.dumps(doc).encode(), cookies or {})
        if url == API + bambu_cloud.LOGIN:
            if body.get("password") not in (None, PASSWORD) or body.get("account") != EMAIL:
                return reply({"code": 1, "error": "Incorrect password"}, 400)
            if "code" in body:
                return reply({"accessToken": self.token, "expiresIn": 7776000}) if body["code"] == self.code else reply({"code": 2}, 400)
            if self.login == "token":
                return reply({"accessToken": self.token, "refreshToken": "r", "expiresIn": 7776000})
            return reply({"loginType": "verifyCode"} if self.login == "code" else {"loginType": "tfa", "tfaKey": "tfa-key-1"})
        if url == API + "/v1/user-service/user/sendemail/code":
            return reply({})
        if url == WEB + "/api/csrf":
            return bambu_cloud.Reply(204, b"", {"bbl_csrf_token": "csrf-abcdef123"})
        if url == WEB + "/api/sign-in/tfa":
            assert headers["x-bbl-csrf-token"] == "csrf-abcdef123" and "bbl_csrf_token=csrf-abcdef123" in headers["Cookie"]
            ok = body == {"tfaKey": "tfa-key-1", "tfaCode": self.tfa_code}
            return bambu_cloud.Reply(200 if ok else 400, b"{}", {"token": self.token} if ok else {})
        if headers.get("Authorization") != f"Bearer {self.token}":
            return reply({"code": 401, "error": "token expired"}, 401)
        if url.startswith(API + bambu_cloud.SPOOLS + "?") and method == "GET":
            query = dict(part.split("=") for part in url.split("?", 1)[1].split("&"))
            offset, limit = int(query["offset"]), int(query["limit"])
            return reply({"total": len(self.spools), "hits": self.spools[offset:offset + limit]})
        if url == API + bambu_cloud.SPOOLS and method == "PUT":
            if self.refuse_puts:
                raise bambu_cloud.BambuCloudError("bambu.unreachable")
            assert set(body) == {"id", "filamentName", "netWeight"} and isinstance(body["netWeight"], int)
            target = next((s for s in self.spools if s["id"] == body["id"]), None)
            if target is None:
                return reply({"code": 404}, 404)
            self.puts.append(body)
            target["netWeight"] = body["netWeight"]
            return reply({"filamentV2": target})
        raise AssertionError((method, url))


@pytest.fixture
def cloud(monkeypatch):
    fake = Cloud()
    monkeypatch.setattr(bambu_cloud, "transport", fake)
    return fake


def sign_in(client, **extra):
    return client.post("/api/bambu-cloud/login", json={"region": "global", "account": EMAIL, "password": PASSWORD, **extra}, headers=H)


@pytest.fixture
def signed_in(owner, cloud):
    res = sign_in(owner)
    assert res.status_code == 200 and res.get_json()["step"] == "done", res.get_json()
    return cloud


def sync(client):
    return client.post("/api/bambu-cloud/sync", json={}, headers=H)


def rolls(client):
    return {r["bambu_id"]: r for r in client.get("/api/spools").get_json() if r["bambu_id"]}


def stored(app):
    return [tuple(r.values()) for r in sql(app, "SELECT region, account, token_enc, expires_at, pending_enc FROM bambu_cloud_settings")]


def waiting(app):
    return sql(app, "SELECT count(*) AS n FROM bambu_cloud_pending_use")[0]["n"]


def says(res, status, key, **params):
    """The answer is this status with the words of this message (in either language: the screens send theirs)."""
    words = {render(L(key, **params), lang) for lang in ("nl", "en")}
    return res.status_code == status and res.get_json().get("error") in words


# --- signing in ---------------------------------------------------------------------------------------------------------------

def test_signing_in_keeps_the_token_sealed_and_never_the_password(app, owner, cloud):
    res = sign_in(owner)
    assert res.status_code == 200
    answer = res.get_json()
    assert (answer["step"], answer["enabled"], answer["account"], answer["region"]) == ("done", True, EMAIL, "global")
    assert answer["expires_at"] and not answer["expired"]
    region, account, sealed, expires, pending = stored(app)[0]
    assert (region, account, pending) == ("global", EMAIL, None) and expires
    assert cloud.token not in sealed and PASSWORD not in json.dumps(stored(app), default=str)
    for path in ("/api/bambu-cloud", "/api/bambu-cloud/connection"):
        assert cloud.token not in owner.get(path).get_data(as_text=True)
    method, url, headers, body = cloud.calls[0]
    assert (method, url, body) == ("POST", API + bambu_cloud.LOGIN, {"account": EMAIL, "password": PASSWORD, "apiError": ""})


def test_a_mailed_code_finishes_the_sign_in(app, owner, cloud):
    cloud.login = "code"
    res = sign_in(owner)
    assert res.get_json()["step"] == "code" and res.get_json()["enabled"] is False and res.get_json()["waiting"] == "code"
    assert not any(url.endswith("/sendemail/code") for _, url, _, _ in cloud.calls)       # Bambu mailed it already: a second request would send two
    assert says(owner.post("/api/bambu-cloud/login/code", json={"code": "000000"}, headers=H), 400, "bambu.code_wrong")
    assert owner.post("/api/bambu-cloud/login/code", json={"code": "abc"}, headers=H).status_code == 400
    res = owner.post("/api/bambu-cloud/login/code", json={"code": " 123 456 "}, headers=H)
    assert res.status_code == 200 and res.get_json()["enabled"] is True and res.get_json()["waiting"] is None
    assert stored(app)[0][4] is None                                                     # the waiting step is gone


def test_a_wrong_code_says_so_and_a_new_code_can_be_asked_for(owner, cloud):
    cloud.login = "code"
    sign_in(owner)
    res = owner.post("/api/bambu-cloud/login/code", json={"code": "999999"}, headers={**H, **NL})
    assert res.status_code == 400 and "klopt niet" in res.get_json()["error"]
    assert owner.post("/api/bambu-cloud/login/resend", json={}, headers=H).status_code == 200
    assert cloud.calls[-1][1] == API + "/v1/user-service/user/sendemail/code" and cloud.calls[-1][3] == {"email": EMAIL, "type": "codeLogin"}


def test_a_code_waits_ten_minutes_at_most(app, owner, cloud):
    cloud.login = "code"
    sign_in(owner)
    sql(app, "UPDATE bambu_cloud_settings SET pending_until = %s", (datetime.now(timezone.utc) - timedelta(seconds=1),))
    res = owner.post("/api/bambu-cloud/login/code", json={"code": "123456"}, headers=H)
    assert says(res, 400, "bambu.no_login")


def test_a_code_without_a_sign_in_waiting_is_refused(owner, cloud):
    assert says(owner.post("/api/bambu-cloud/login/code", json={"code": "123456"}, headers=H), 400, "bambu.no_login")
    assert says(owner.post("/api/bambu-cloud/login/resend", json={}, headers=H), 400, "bambu.no_login")


def test_an_authenticator_app_finishes_the_sign_in_through_the_web_site(app, owner, cloud):
    cloud.login = "tfa"
    assert sign_in(owner).get_json()["step"] == "tfa"
    assert "tfa-key-1" not in json.dumps(stored(app), default=str)                                     # sealed while it waits
    assert says(owner.post("/api/bambu-cloud/login/code", json={"code": "111111"}, headers=H), 400, "bambu.code_wrong")
    res = owner.post("/api/bambu-cloud/login/code", json={"code": "654321"}, headers=H)
    assert res.status_code == 200 and res.get_json()["enabled"] is True
    assert owner.post("/api/bambu-cloud/login/resend", json={}, headers=H).status_code == 400      # nothing waits any more


def test_a_wrong_password_is_a_400_and_never_a_401(owner, cloud):
    res = sign_in(owner, password="wrong")
    assert says(res, 400, "bambu.login_failed")       # the screens read a 401 as "signed out"
    assert owner.get("/api/bambu-cloud").get_json()["enabled"] is False


@pytest.mark.parametrize("body", [{"account": ""}, {"account": "a b@c.d"}, {"account": None}, {"password": ""}, {"password": 5}, {"region": "mars"},
                                  {"region": ["global"]}])
def test_what_is_typed_is_checked_before_bambu_is_asked(owner, cloud, body):
    assert sign_in(owner, **body).status_code == 400
    assert cloud.calls == []


def test_the_bot_protection_and_a_redirect_are_errors_of_their_own(owner, cloud):
    cloud.blocked = True
    assert says(sign_in(owner), 502, "bambu.blocked")
    cloud.blocked, cloud.answer = False, bambu_cloud.Reply(302, b"")
    assert says(sign_in(owner), 502, "bambu.redirect")


def test_the_china_region_signs_in_at_its_own_cloud(owner, cloud, monkeypatch):
    seen = []
    monkeypatch.setattr(bambu_cloud, "transport", lambda method, url, **kw: seen.append(url) or bambu_cloud.Reply(400, b"{}"))
    sign_in(owner, region="china")
    assert seen == ["https://api.bambulab.cn" + bambu_cloud.LOGIN]


def test_signing_out_forgets_the_token_but_not_what_waits_to_be_written_back(app, owner, signed_in):
    sql(app, "INSERT INTO bambu_cloud_pending_use (bambu_id, grams) VALUES (1, 5)")
    res = owner.delete("/api/bambu-cloud/login", headers=H)
    assert res.status_code == 200 and res.get_json()["enabled"] is False
    assert stored(app)[0][2] is None and waiting(app) == 1                                # signed in again, the next sync sends it
    assert res.get_json()["account"] == EMAIL                                             # kept, to fill in the next sign-in


def test_a_token_that_cannot_be_read_any_more_asks_to_sign_in_again(app, owner, signed_in):
    sealed_elsewhere = passwords.seal("another-session-secret-" + "x" * 40, b"some-token-value", bambu_cloud.TOKEN_INFO).decode()
    sql(app, "UPDATE bambu_cloud_settings SET token_enc = %s", (sealed_elsewhere,))      # as after SESSION_SECRET changed
    res = sync(owner)
    assert says(res, 502, "bambu.token_unreadable")
    assert owner.get("/api/bambu-cloud").get_json()["token_readable"] is False


# --- the sync -----------------------------------------------------------------------------------------------------------------

def test_a_sync_makes_a_roll_of_every_spool(owner, signed_in):
    signed_in.spools = [spool(11, colour="#FF6A13FF", net=731, total=1000, note="op de plank"),
                        spool(12, name="PETG HF", material="PETG", colour="#1F79E5", net=250, total=500)]
    res = sync(owner)
    assert res.status_code == 200, res.get_json()
    assert res.get_json() == {"created": 2, "linked": 0, "updated": 0, "archived": 0, "skipped": 0, "total": 2, "sent": 0, "dropped": 0}
    found = rolls(owner)
    orange, blue = found[11], found[12]
    assert (orange["brand"], orange["material"], orange["product_type"], orange["colour_hex"]) == ("Bambu Lab", "PLA", "Basic", "#ff6a13")
    assert (orange["roll_weight_g"], orange["remaining_g"], orange["notes"], orange["archived"]) == ("1000.0", "731.0", "op de plank", False)
    assert (blue["product_type"], blue["roll_weight_g"], blue["remaining_g"]) == ("HF", "500.0", "250.0")


def test_the_colour_name_comes_from_spoolmandb_by_its_code(owner, signed_in):
    signed_in.spools = [spool(1, colour="#000000FF"), spool(2, name="PETG HF", material="PETG", colour="#000000"), spool(3, colour="#123456")]
    sync(owner)
    found = rolls(owner)
    assert found[1]["colour"] == "Black" and found[1]["spoolmandb_id"]                    # not "HF Black": the standard line has no prefix there
    assert found[2]["colour"] == "Black" and found[2]["spoolmandb_id"].startswith("bambulab_petg")
    assert found[3]["colour"] == "#123456" and found[3]["spoolmandb_id"] == ""            # unknown: the code, so two colours never become one kind
    assert found[1]["price"] == "0.00"


def test_an_rfid_spool_takes_name_price_and_barcode_from_the_library_entry_it_is(owner, signed_in):
    make(owner, "/api/filament-library", {"brand": "Bambu Lab", "product_type": "Basic", "material": "PLA", "colour": "Zwart", "sku": "A00-K0-1.75-1000-SPL",
                                          "barcode": "6975337030015", "roll_weight_g": 1000, "diameter_mm": 1.75, "price": "21.84"})
    signed_in.spools = [spool(5, tray="A00-K0", colour="#000000FF")]
    sync(owner)
    roll = rolls(owner)[5]
    assert (roll["colour"], roll["price"], roll["barcode"]) == ("Zwart", "21.84", "6975337030015")


def test_every_page_is_read(owner, signed_in):
    signed_in.spools = [spool(n, colour=f"#{n:06x}") for n in range(1, 151)]
    assert sync(owner).get_json()["created"] == 150
    assert sum(1 for _, url, _, _ in signed_in.calls if "offset=" in url) == 2


def test_a_malformed_spool_is_skipped_and_counted_never_fatal(owner, signed_in):
    signed_in.spools = [spool(1), {"id": "x"}, {"id": True}, "nonsense", {"id": 2, "netWeight": "lots", "totalNetWeight": -5, "colors": [9], "color": None}]
    res = sync(owner).get_json()
    assert (res["created"], res["skipped"]) == (2, 3)
    odd = rolls(owner)[2]
    assert (odd["remaining_g"], odd["roll_weight_g"], odd["colour_hex"]) == ("0.0", "1000.0", "")


def test_a_later_sync_updates_and_a_spool_that_is_gone_is_archived_not_deleted(owner, signed_in):
    signed_in.spools = [spool(1), spool(2, colour="#FFFFFF")]
    sync(owner)
    signed_in.spools = [spool(1, net=500)]
    res = sync(owner).get_json()
    assert (res["updated"], res["archived"], res["created"]) == (1, 1, 0)
    found = {r["bambu_id"]: r for r in owner.get("/api/spools").get_json()}
    assert found[1]["remaining_g"] == "500.0" and found[2]["archived"] is True
    signed_in.spools.append(spool(2, colour="#FFFFFF"))
    sync(owner)
    assert rolls(owner)[2]["archived"] is False                                           # back in the cloud, back on the shelf


def test_a_sync_never_overwrites_what_the_app_keeps(owner, signed_in):
    signed_in.spools = [spool(1)]
    sync(owner)
    roll = rolls(owner)[1]
    assert owner.patch(f"/api/spools/{roll['id']}", json={"price": "24.50", "colour": "Zwart", "notes": "eigen notitie"}, headers=H).status_code == 200
    signed_in.spools[0]["note"] = "a note in Studio"
    sync(owner)
    roll = rolls(owner)[1]
    assert (roll["price"], roll["colour"], roll["notes"]) == ("24.50", "Zwart", "eigen notitie")


def test_an_expired_sign_in_says_so(owner, signed_in, monkeypatch):
    signed_in.token = "another-token-the-app-does-not-have"
    res = sync(owner)
    assert says(res, 502, "bambu.expired")
    state = owner.get("/api/bambu-cloud/connection", headers=NL).get_json()
    assert state["state"] == "offline" and "verlopen" in state["message"]


def test_a_sync_without_a_sign_in_is_refused(owner, cloud):
    assert sync(owner).status_code == 400


# --- one roll, one row ----------------------------------------------------------------------------------------------------

def test_a_roll_typed_in_before_is_linked_and_not_added_a_second_time(owner, signed_in):
    mine = make(owner, "/api/spools", {"brand": "Bambu Lab", "product_type": "Basic", "material": "PLA", "colour": "Zwart", "colour_hex": "#000000",
                                       "roll_weight_g": 1000, "price": "19.95", "remaining_g": 700, "notes": "mijn rol", "notify_low": True})
    other = make(owner, "/api/spools", {"brand": "Bambu Lab", "material": "PLA", "colour": "Wit", "roll_weight_g": 1000, "price": "19", "remaining_g": 1000})
    signed_in.spools = [spool(1, colour="#000000FF", net=650)]
    assert sync(owner).get_json()["linked"] == 1
    roll = rolls(owner)[1]
    assert roll["id"] == mine["id"]                                                       # the same row, so calculations still point at it
    assert (roll["remaining_g"], roll["price"], roll["notes"], roll["notify_low"], roll["colour"]) == ("650.0", "19.95", "mijn rol", True, "Zwart")
    assert len(owner.get("/api/spools").get_json()) == 2
    assert [r for r in owner.get("/api/spools").get_json() if r["id"] == other["id"]][0]["bambu_id"] is None


def test_a_colour_name_in_either_language_finds_the_roll(owner, signed_in):
    mine = make(owner, "/api/spools", {"brand": "Bambu Lab", "material": "PLA", "colour": "Zwart", "roll_weight_g": 1000, "price": "19", "remaining_g": 900})
    signed_in.spools = [spool(1, colour="#000000FF")]                                     # "Black" in SpoolmanDB
    sync(owner)
    assert rolls(owner)[1]["id"] == mine["id"]


def test_one_roll_is_never_two_spools_and_the_nearest_weight_goes_first(owner, signed_in):
    roll = {"brand": "Bambu Lab", "material": "PLA", "colour": "Zwart", "colour_hex": "#000000", "roll_weight_g": 1000, "price": "19"}
    near = make(owner, "/api/spools", {**roll, "remaining_g": 300})
    signed_in.spools = [spool(1, net=900), spool(2, net=320)]
    res = sync(owner).get_json()
    assert (res["linked"], res["created"]) == (1, 1)
    assert rolls(owner)[2]["id"] == near["id"]


def test_another_material_or_line_is_not_the_same_roll(owner, signed_in):
    make(owner, "/api/spools", {"brand": "Bambu Lab", "product_type": "Matte", "material": "PLA", "colour_hex": "#000000", "colour": "Zwart",
                                "roll_weight_g": 1000, "price": "19", "remaining_g": 900})
    make(owner, "/api/spools", {"brand": "Bambu Lab", "material": "PETG", "colour_hex": "#000000", "colour": "Zwart", "roll_weight_g": 1000, "price": "19",
                                "remaining_g": 900})
    signed_in.spools = [spool(1, colour="#000000FF")]
    assert sync(owner).get_json()["linked"] == 0


# --- what the cloud keeps and what the app keeps --------------------------------------------------------------------------------

def test_what_the_cloud_keeps_cannot_be_changed_here_while_signed_in(owner, signed_in):
    signed_in.spools = [spool(1)]
    sync(owner)
    roll = rolls(owner)[1]
    for change in ({"remaining_g": 10}, {"brand": "Elegoo"}, {"material": "PETG"}, {"colour_hex": "#ffffff"}, {"roll_weight_g": 750}, {"archived": True}):
        res = owner.patch(f"/api/spools/{roll['id']}", json=change, headers=H)
        assert says(res, 409, "bambu.managed"), change
    assert owner.delete(f"/api/spools/{roll['id']}", headers=H).status_code == 409


def test_the_whole_form_may_be_sent_as_long_as_what_the_cloud_keeps_is_unchanged(owner, signed_in):
    signed_in.spools = [spool(1)]
    sync(owner)
    roll = rolls(owner)[1]
    form = {k: roll[k] for k in ("brand", "product_type", "material", "colour", "colour_hex", "roll_weight_g", "remaining_g", "barcode", "diameter_mm",
                                 "print_temp_c", "bed_temp_c", "notes", "notify_low", "archived", "spoolmandb_id")}
    res = owner.patch(f"/api/spools/{roll['id']}", json={**form, "price": "22.00", "colour": "Diepzwart", "diameter_mm": "1.75", "barcode": "123"}, headers=H)
    assert res.status_code == 200, res.get_json()
    assert (res.get_json()["price"], res.get_json()["colour"], res.get_json()["barcode"]) == ("22.00", "Diepzwart", "123")


def test_after_signing_out_a_roll_of_the_cloud_is_a_roll_like_any_other(owner, signed_in):
    signed_in.spools = [spool(1)]
    sync(owner)
    roll = rolls(owner)[1]
    owner.delete("/api/bambu-cloud/login", headers=H)
    assert owner.patch(f"/api/spools/{roll['id']}", json={"remaining_g": 10}, headers=H).status_code == 200
    assert rolls(owner)[1]["bambu_id"] == 1                                               # still linked: signing in again updates it


def test_a_roll_of_the_cloud_is_not_changed_by_copying_details_from_a_roll_with_its_barcode(owner, signed_in):
    signed_in.spools = [spool(1)]
    sync(owner)
    cloud_roll = rolls(owner)[1]
    owner.patch(f"/api/spools/{cloud_roll['id']}", json={"barcode": "B-1"}, headers=H)
    typed = make(owner, "/api/spools", {"brand": "Elegoo", "material": "PETG", "colour": "Rood", "barcode": "B-1", "roll_weight_g": 1000, "price": "15",
                                        "remaining_g": 1000})
    assert owner.get(f"/api/spools/{typed['id']}/siblings").get_json()["count"] == 0
    assert post(owner, f"/api/spools/{typed['id']}/propagate", {"fields": ["brand", "material"]}).get_json()["updated"] == 0


# --- writing back what was used -----------------------------------------------------------------------------------------------

def book(owner, roll_id):
    project = make(owner, "/api/projects", sheet_payload(roll_id))                       # 70 g
    return post(owner, f"/api/projects/{project['id']}/book-stock")


def test_a_booking_takes_it_off_here_and_writes_it_back_to_the_cloud(app, owner, signed_in):
    signed_in.spools = [spool(1, net=800)]
    sync(owner)
    res = book(owner, rolls(owner)[1]["id"])
    assert res.status_code == 200 and res.get_json()["cloud_waiting"] == 0
    assert rolls(owner)[1]["remaining_g"] == "730.0"
    assert signed_in.puts == [{"id": 1, "filamentName": "PLA Basic", "netWeight": 730}]
    assert waiting(app) == 0
    assert sync(owner).get_json()["updated"] == 0                                         # the cloud says what the shelf says


def test_what_the_cloud_does_not_take_waits_and_the_shelf_does_not_jump_back(app, owner, signed_in):
    signed_in.spools = [spool(1, net=800)]
    sync(owner)
    signed_in.refuse_puts = True
    res = book(owner, rolls(owner)[1]["id"])
    assert res.status_code == 200 and res.get_json()["cloud_waiting"] == 1                # the booking itself went through
    assert sync(owner).status_code == 502                                                 # the cloud still refuses: nothing read is trusted over the shelf
    assert rolls(owner)[1]["remaining_g"] == "730.0"
    signed_in.refuse_puts = False
    res = sync(owner).get_json()
    assert (res["sent"], res["updated"]) == (1, 0) and signed_in.puts[-1]["netWeight"] == 730
    assert rolls(owner)[1]["remaining_g"] == "730.0"


def test_a_sync_subtracts_what_still_waits_from_what_the_cloud_reports(app, owner, signed_in):
    signed_in.spools = [spool(1, net=800)]
    sync(owner)
    sql(app, "INSERT INTO bambu_cloud_pending_use (bambu_id, grams, claimed_until) VALUES (1, 70, %s)",
        (datetime.now(timezone.utc) + timedelta(minutes=5),))                              # another worker is sending it
    with app.app_context(), app.test_request_context():
        with app.extensions["pool"].connection() as conn:
            assert bambu_cloud.sync(conn, signed_in.spools, 0)["updated"] == 1
    assert rolls(owner)[1]["remaining_g"] == "730.0"


def test_two_uses_of_one_spool_both_count(owner, signed_in):
    signed_in.spools = [spool(1, net=800)]
    sync(owner)
    book(owner, rolls(owner)[1]["id"])
    book(owner, rolls(owner)[1]["id"])
    assert [p["netWeight"] for p in signed_in.puts] == [730, 660]


def test_a_use_of_a_spool_that_left_the_cloud_is_dropped(app, owner, signed_in):
    signed_in.spools = [spool(1)]
    sql(app, "INSERT INTO bambu_cloud_pending_use (bambu_id, grams) VALUES (99, 5)")
    res = sync(owner).get_json()
    assert (res["sent"], res["dropped"]) == (0, 1)
    assert waiting(app) == 0


def test_a_roll_typed_in_here_is_booked_here_only(app, owner, signed_in):
    typed = make(owner, "/api/spools", {"brand": "Elegoo", "material": "PLA", "colour": "Rood", "roll_weight_g": 1000, "price": "15", "remaining_g": 500})
    assert book(owner, typed["id"]).get_json()["cloud_waiting"] == 0
    assert signed_in.puts == [] and waiting(app) == 0


# --- one source at a time ------------------------------------------------------------------------------------------------------

def test_with_spoolman_chosen_the_sign_in_rests(app, owner, signed_in):
    signed_in.spools = [spool(1)]
    sync(owner)
    roll = rolls(owner)[1]
    assert owner.put("/api/spoolman/settings", json={"url": "http://spoolman:8000"}, headers=H).status_code == 200      # no longer refused
    status = owner.get("/api/bambu-cloud").get_json()
    assert (status["enabled"], status["active"]) == (True, False)                     # still signed in, not in use
    assert says(sync(owner), 409, "bambu.not_chosen")
    assert owner.get("/api/bambu-cloud/connection").get_json()["state"] == "resting"
    assert owner.patch(f"/api/spools/{roll['id']}", json={"remaining_g": 10}, headers=H).status_code == 200            # a roll like any other now
    assert sign_in(owner).status_code == 200                                           # signing in is not refused: it only rests


# --- backup -------------------------------------------------------------------------------------------------------------------

def test_a_backup_keeps_a_restored_roll_linked_and_never_holds_the_sign_in(owner, signed_in):
    signed_in.spools = [spool(1), spool(2, colour="#FFFFFF")]
    sync(owner)
    doc = owner.get("/api/backup").get_json()
    assert sorted(s["bambu_id"] for s in doc["spools"]) == [1, 2]
    text = json.dumps(doc)
    assert signed_in.token not in text and "bambu_cloud" not in text and EMAIL not in text and "bambu_synced_at" not in text
    assert post(owner, "/api/backup/restore", doc).status_code == 200
    assert sorted(rolls(owner)) == [1, 2]
    assert sync(owner).get_json()["created"] == 0


@pytest.mark.parametrize("bad", ["1", 0, -3, True, 2 ** 63])
def test_a_backup_with_a_bad_bambu_number_is_refused(owner, signed_in, bad):
    signed_in.spools = [spool(1)]
    sync(owner)
    doc = owner.get("/api/backup").get_json()
    doc["spools"][0]["bambu_id"] = bad
    assert post(owner, "/api/backup/restore", doc).status_code == 400


def test_two_rolls_cannot_share_a_bambu_number_in_a_backup(owner, signed_in):
    signed_in.spools = [spool(1), spool(2, colour="#FFFFFF")]
    sync(owner)
    doc = owner.get("/api/backup").get_json()
    doc["spools"][1]["bambu_id"] = doc["spools"][0]["bambu_id"]
    assert post(owner, "/api/backup/restore", doc).status_code == 400


# --- who may, and the badge -----------------------------------------------------------------------------------------------------

def test_everybody_may_read_the_status_but_only_an_administrator_signs_in_or_syncs(app, owner, signed_in):
    member = join_with_passkey(app, owner)
    status = member.get("/api/bambu-cloud").get_json()
    assert status["enabled"] is True and status["can_configure"] is False and "account" not in status and "region" not in status
    assert member.post("/api/bambu-cloud/sync", json={}, headers=H).status_code == 403
    assert sign_in(member).status_code == 403
    assert member.delete("/api/bambu-cloud/login", headers=H).status_code == 403
    assert member.get("/api/bambu-cloud/connection").get_json()["state"] == "active"
    assert app.test_client().get("/api/bambu-cloud").status_code == 401


def test_the_connection_is_off_until_signed_in_and_active_while_the_cloud_answers(owner, cloud):
    assert owner.get("/api/bambu-cloud/connection").get_json() == {"state": "off", "message": None}
    sign_in(owner)
    assert owner.get("/api/bambu-cloud/connection").get_json() == {"state": "active", "message": None}
    cloud.down = True
    state = owner.get("/api/bambu-cloud/connection", headers={"X-Lang": "en"}).get_json()
    assert state["state"] == "offline" and "cannot be reached" in state["message"]


# --- the one way out ---------------------------------------------------------------------------------------------------------------

class Streamed:
    def __init__(self, status, chunks, cookies=None):
        self.status_code, self.chunks, self.cookies, self.closed = status, chunks, cookies or {}, False

    def iter_content(self, chunk_size):
        yield from self.chunks

    def close(self):
        self.closed = True


def test_the_transport_follows_no_redirect_caps_the_answer_and_keeps_only_two_cookies(monkeypatch):
    seen = {}

    def fake(method, url, **kwargs):
        seen.update(kwargs)
        seen["reply"] = Streamed(200, [b'{"a":', b"1}"], {"token": "t", "session": "s", "bbl_csrf_token": "c"})
        return seen["reply"]

    monkeypatch.setattr(bambu_cloud.curl, "request", fake)
    reply = bambu_cloud.transport("GET", API + "/x", headers={}, body=None)
    assert seen["allow_redirects"] is False and seen["timeout"] == bambu_cloud.TIMEOUT and seen["impersonate"] and seen["stream"] is True
    assert (reply.status, reply.body, reply.cookies) == (200, b'{"a":1}', {"token": "t", "bbl_csrf_token": "c"}) and seen["reply"].closed
    monkeypatch.setattr(bambu_cloud.curl, "request", lambda *a, **k: Streamed(200, [b"x" * (bambu_cloud.MAX_BYTES + 1)]))
    with pytest.raises(bambu_cloud.BambuCloudError) as caught:
        bambu_cloud.transport("GET", API + "/x", headers={}, body=None)
    assert caught.value.key == "bambu.bad_reply"


def test_a_network_failure_is_an_error_of_its_own_and_names_no_address_with_its_query(monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise bambu_cloud.curl.exceptions.ConnectionError("refused")

    monkeypatch.setattr(bambu_cloud.curl, "request", fail)
    with pytest.raises(bambu_cloud.BambuCloudError) as caught:
        bambu_cloud.transport("GET", API + bambu_cloud.SPOOLS + "?offset=0&limit=1", headers={"Authorization": "Bearer secret"}, body=None)
    assert caught.value.key == "bambu.unreachable" and "secret" not in caplog.text and "offset" not in caplog.text
