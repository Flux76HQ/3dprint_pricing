"""The filament library: entries, the JSON file in and out, the Bambu Lab invoice and the sync from GitHub."""
import dataclasses
import io
import json
from pathlib import Path

import pytest
import requests

from app import bambu_store
from tests.bambu_invoices import FILAMENT, Reply as ShopReply, Shop, invoice_pdf
from tests.test_auth_api import H
from tests.test_domain_api import make, owner  # noqa: F401  (fixture)

NL = {"X-Lang": "nl"}
GREY = {"brand": "Bambu Lab", "product_type": "Basic", "material": "PLA", "colour": "Grijs", "filament_id": "10103",
        "sku": "A00-D0-1.75-1000-SPLFREE", "refill": True, "roll_weight_g": 1000, "diameter_mm": "1.75", "price": "19.32"}


@pytest.fixture(autouse=True)
def shop(monkeypatch):
    """The Bambu Lab web shop is never reached from a test: this is a stand-in with the variants of the synthetic invoice."""
    bambu_store._cache.clear()
    fake = Shop()
    monkeypatch.setattr(requests, "get", fake.get)
    return fake


def library(owner):
    return owner.get("/api/filament-library").get_json()


def upload(owner, content, name="factuur.pdf"):
    return owner.post("/api/filament-library/invoice", data={"file": (io.BytesIO(content), name)}, headers=H, content_type="multipart/form-data")


def lines_of(owner):
    return upload(owner, invoice_pdf()).get_json()["lines"]


# --- entries -----------------------------------------------------------------------------------------------------

def test_an_entry_keeps_its_specs_and_its_filament_id(owner):
    entry = make(owner, "/api/filament-library", {**GREY, "print_temp_c": 220, "bed_temp_c": 55, "colour_hex": " #9E9E9E ", "notes": "koel bed"})
    assert (entry["filament_id"], entry["sku"], entry["refill"], entry["price"], entry["colour_hex"]) == ("10103", GREY["sku"], True, "19.32", "#9e9e9e")
    assert (entry["print_temp_c"], entry["bed_temp_c"], entry["diameter_mm"]) == (220, 55, "1.75")
    changed = owner.patch(f"/api/filament-library/{entry['id']}", json={"filament_id": "10104", "price": ""}, headers=H).get_json()
    assert changed["filament_id"] == "10104" and changed["price"] is None            # an empty price is "not known", not zero
    assert owner.delete(f"/api/filament-library/{entry['id']}", headers=H).status_code == 200
    assert library(owner) == []


def test_a_price_and_a_weight_are_checked(owner):
    assert owner.post("/api/filament-library", json={"brand": "x", "roll_weight_g": 0}, headers=H).status_code == 400
    assert owner.post("/api/filament-library", json={"brand": "x", "roll_weight_g": 1000, "price": "-1"}, headers=H).status_code == 400
    assert owner.post("/api/filament-library", json={"roll_weight_g": 1000}, headers=H).status_code == 400
    bare = make(owner, "/api/filament-library", {"brand": "Sunlu", "roll_weight_g": 1000})
    assert bare["price"] is None and bare["diameter_mm"] == "1.75" and bare["refill"] is False


def test_the_library_needs_a_session(client):
    for method, path in (("get", "/api/filament-library"), ("get", "/api/filament-library/export"), ("post", "/api/filament-library/sync"),
                         ("post", "/api/filament-library/import"), ("post", "/api/filament-library/invoice"),
                         ("post", "/api/filament-library/from-rolls"), ("post", "/api/filament-library/contribution")):
        assert getattr(client, method)(path, headers=H).status_code == 401


# --- the JSON file -----------------------------------------------------------------------------------------------

def test_the_export_is_a_json_file_with_numbers_and_no_ids(owner):
    make(owner, "/api/filament-library", {**GREY, "print_temp_c": 220})
    res = owner.get("/api/filament-library/export")
    assert "attachment" in res.headers["Content-Disposition"] and res.headers["Content-Disposition"].endswith('.json"')
    doc = res.get_json()
    assert doc["format"] == "printpricing-filament-library" and doc["format_version"] == 1
    [entry] = doc["filaments"]
    assert "id" not in entry and "created_at" not in entry
    assert (entry["roll_weight_g"], entry["diameter_mm"], entry["price"], entry["print_temp_c"], entry["filament_id"]) == (1000.0, 1.75, 19.32, 220, "10103")


def test_what_is_exported_can_be_imported_elsewhere_and_again_changes_nothing(owner):
    make(owner, "/api/filament-library", GREY)
    make(owner, "/api/filament-library", {"brand": "Sunlu", "material": "PETG", "colour": "Zwart", "roll_weight_g": 1000})
    doc = owner.get("/api/filament-library/export").get_json()
    for row in library(owner):
        owner.delete(f"/api/filament-library/{row['id']}", headers=H)
    first = owner.post("/api/filament-library/import", json=doc, headers=H).get_json()
    assert (first["added"], first["updated"], first["unchanged"]) == (2, 0, 0)
    again = owner.post("/api/filament-library/import", json=doc, headers=H).get_json()
    assert (again["added"], again["updated"], again["unchanged"]) == (0, 0, 2) and len(library(owner)) == 2


def test_an_import_updates_a_known_filament_keeps_the_rest_and_a_dry_run_changes_nothing(owner):
    mine = make(owner, "/api/filament-library", {**GREY, "print_temp_c": 220, "notes": "mijn"})
    other = make(owner, "/api/filament-library", {"brand": "Sunlu", "roll_weight_g": 1000})
    doc = {"format": "printpricing-filament-library", "format_version": 1, "filaments": [{**GREY, "price": "20.00"}]}   # same SKU, newer price
    dry = owner.post("/api/filament-library/import?dry_run=1", json=doc, headers=H).get_json()
    assert dry["dry_run"] is True and dry["updated"] == 1 and library(owner)[0]["price"] != "20.00"
    done = owner.post("/api/filament-library/import", json=doc, headers=H).get_json()
    assert (done["added"], done["updated"]) == (0, 1)
    rows = {r["id"]: r for r in library(owner)}
    assert rows[mine["id"]]["price"] == "20.00" and rows[mine["id"]]["print_temp_c"] == 220 and rows[mine["id"]]["notes"] == "mijn"   # what the file leaves out stays
    assert other["id"] in rows                                                          # nothing is ever deleted by an import


def test_two_entries_of_one_file_that_are_the_same_filament_are_one(owner):
    doc = {"format": "printpricing-filament-library", "format_version": 1,
           "filaments": [{**GREY, "price": "10"}, {**GREY, "price": "11"}]}
    assert owner.post("/api/filament-library/import", json=doc, headers=H).get_json()["added"] == 1
    [row] = library(owner)
    assert row["price"] == "11.00"


@pytest.mark.parametrize("change, status, fragment", [
    ({"format": "something-else"}, 400, "geen filamentbibliotheek"),
    ({"format_version": 2}, 400, "nieuwere versie"),
    ({"filaments": "no"}, 400, "klopt niet"),
    ({"filaments": [GREY, {"brand": "x", "roll_weight_g": 0}]}, 400, "Regel 2"),
    ({"filaments": [GREY, "text"]}, 400, "Regel 2"),
])
def test_a_file_that_is_not_a_valid_library_is_refused_and_nothing_changes(owner, change, status, fragment):
    doc = {"format": "printpricing-filament-library", "format_version": 1, "filaments": [GREY], **change}
    res = owner.post("/api/filament-library/import", json=doc, headers=NL)
    assert res.status_code == status and fragment in res.get_json()["error"]
    assert library(owner) == []


# --- the invoice -------------------------------------------------------------------------------------------------

def test_an_invoice_is_read_and_checked_against_the_library_without_writing_anything(owner):
    make(owner, "/api/filament-library", GREY)
    res = upload(owner, invoice_pdf())
    assert res.status_code == 200
    invoice = res.get_json()
    assert [bool(line["library_id"]) for line in invoice["lines"]] == [True, False, False]       # the grey one is known by its SKU
    assert invoice["order_number"] == "EN000000000000000001" and invoice["warnings"] == []
    assert len(library(owner)) == 1 and owner.get("/api/spools").get_json() == []


def test_an_invoice_whose_lines_do_not_add_up_carries_a_warning(owner):
    invoice = upload(owner, invoice_pdf(total="99.00")).get_json()
    assert len(invoice["warnings"]) == 1 and "99.00" in invoice["warnings"][0]


@pytest.mark.parametrize("content, fragment", [(b"nope", "geen PDF"), (invoice_pdf(bambu=False), "geen Bambu Lab-factuur")])
def test_a_file_that_is_no_bambu_invoice_is_refused_with_a_reason(owner, content, fragment):
    res = owner.post("/api/filament-library/invoice", data={"file": (io.BytesIO(content), "x.pdf")}, headers={**H, **NL}, content_type="multipart/form-data")
    assert res.status_code == 422 and fragment in res.get_json()["error"]
    assert owner.post("/api/filament-library/invoice", headers=H).status_code == 400            # no file at all


def test_applying_an_invoice_fills_the_library_and_leaves_the_shelf_alone(owner):
    owner.post("/api/spools", json={"brand": "Mijn", "roll_weight_g": 1000, "price": 5, "remaining_g": 300}, headers=H)
    lines = lines_of(owner)
    for line in lines:
        line["rolls"], line["paid_price"] = 5, "1.00"                 # what an older screen may still send: never acted on
    res = owner.post("/api/filament-library/invoice/apply", json={"order_number": "EN000000000000000001", "lines": lines}, headers=H).get_json()
    assert (res["added"], res["updated"], res["unchanged"]) == (3, 0, 0) and "rolls" not in res
    entries = {e["colour"]: e for e in library(owner)}
    assert entries["Rood"]["price"] == "21.84" and entries["Rood"]["filament_id"] == "10200" and entries["Grijs"]["refill"] is True
    assert [r["brand"] for r in owner.get("/api/spools").get_json()] == ["Mijn"]            # not one roll was made from the invoice
    assert owner.get("/api/spools/stock").get_json()["groups"][0]["remaining_g"] == "300.0"



def test_applying_to_a_known_filament_only_brings_the_new_price_and_keeps_what_you_entered(owner):
    mine = make(owner, "/api/filament-library", {**GREY, "price": "15", "print_temp_c": 215, "colour_hex": "#aaaaaa", "notes": "mijn"})
    grey = lines_of(owner)[0]
    grey["colour"], grey["colour_hex"] = "Gris", "#000000"                                        # the invoice must not rename or recolour it
    res = owner.post("/api/filament-library/invoice/apply", json={"lines": [grey]}, headers=H).get_json()
    assert (res["added"], res["updated"], res["unchanged"]) == (0, 1, 0)
    [row] = library(owner)
    assert row["id"] == mine["id"] and row["price"] == "19.32"
    assert (row["colour"], row["colour_hex"], row["print_temp_c"], row["notes"]) == ("Grijs", "#aaaaaa", 215, "mijn")


@pytest.mark.parametrize("body", [{}, {"lines": []}, {"lines": ["x"]}, {"lines": [{"brand": "x", "roll_weight_g": 0}]}])
def test_a_bad_apply_is_refused_and_changes_nothing(owner, body):
    assert owner.post("/api/filament-library/invoice/apply", json=body, headers=H).status_code == 400
    assert library(owner) == [] and owner.get("/api/spools").get_json() == []


# --- sync from GitHub --------------------------------------------------------------------------------------------

class Reply:
    def __init__(self, body=b"", status=200):
        self.body, self.status_code = body, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, size):
        yield self.body


@pytest.fixture
def remote(monkeypatch):
    """Stands in for GitHub: whatever `.reply` is gets served, and every call is remembered. The real network is never touched."""
    class Remote:
        reply = Reply()
        calls = []
    def get(url, **kwargs):
        Remote.calls.append((url, kwargs))
        if isinstance(Remote.reply, Exception):
            raise Remote.reply
        return Remote.reply
    monkeypatch.setattr(requests, "get", get)
    return Remote


def shared(*entries):
    return Reply(json.dumps({"format": "printpricing-filament-library", "format_version": 1, "filaments": list(entries)}).encode())


def test_sync_reads_the_shared_file_from_the_configured_address_and_merges_it(owner, remote, app):
    remote.reply = shared(GREY, {"brand": "Bambu Lab", "material": "PLA", "colour": "Rood", "filament_id": "10200", "roll_weight_g": 1000})
    assert owner.get("/api/filament-library/source").get_json()["url"].startswith("https://raw.githubusercontent.com/")
    dry = owner.post("/api/filament-library/sync?dry_run=1", headers=H).get_json()
    assert (dry["dry_run"], dry["added"]) == (True, 2) and library(owner) == []
    done = owner.post("/api/filament-library/sync", headers=H).get_json()
    assert done["added"] == 2 and len(library(owner)) == 2
    url, kwargs = remote.calls[-1]
    assert url == app.config["APP_CONFIG"].filament_library_url and kwargs["allow_redirects"] is False and kwargs["timeout"] <= 30
    assert owner.post("/api/filament-library/sync", headers=H).get_json()["unchanged"] == 2


@pytest.mark.parametrize("reply, status, fragment", [
    (Reply(status=404), 502, "fout 404"),
    (Reply(status=302), 502, "fout 302"),                                         # a redirect is not followed
    (Reply(b"<html>"), 502, "geen geldige JSON"),
    (Reply(b"x" * (2 * 1024 * 1024 + 1)), 502, "te groot"),
    (requests.ConnectionError("down"), 502, "niet bereikbaar"),
    (Reply(b'{"format": "printpricing-backup"}'), 400, "geen filamentbibliotheek"),
])
def test_a_source_that_fails_or_is_not_a_library_changes_nothing(owner, remote, reply, status, fragment):
    remote.reply = reply
    res = owner.post("/api/filament-library/sync", headers={**H, **NL})
    assert res.status_code == status and fragment in res.get_json()["error"] and library(owner) == []


def test_sync_is_off_without_an_address_and_the_address_is_never_taken_from_the_request(owner, remote, app):
    app.config["APP_CONFIG"] = dataclasses.replace(app.config["APP_CONFIG"], filament_library_url="")
    assert owner.get("/api/filament-library/source").get_json() == {"url": "", "contribute_url": ""}
    assert owner.post("/api/filament-library/sync", json={"url": "https://evil.example/x.json"}, headers=H).status_code == 404
    assert remote.calls == []


@pytest.mark.parametrize("url", ["http://raw.githubusercontent.com/x.json", "https://evil.example/x.json", "https://raw.githubusercontent.com.evil.example/x.json", "ftp://x"])
def test_only_an_https_github_raw_address_is_accepted_in_the_configuration(monkeypatch, url):
    from app.config import ConfigError, _library_url
    monkeypatch.setenv("FILAMENT_LIBRARY_URL", url)
    with pytest.raises(ConfigError):
        _library_url()
    monkeypatch.setenv("FILAMENT_LIBRARY_URL", "")
    assert _library_url() == ""


def test_the_shared_library_file_in_the_repository_is_a_valid_library(owner):
    path = Path(__file__).resolve().parents[2] / "library" / "filaments.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    res = owner.post("/api/filament-library/import", json=doc, headers=H).get_json()
    assert res["added"] == len(doc["filaments"]) > 0 and res["updated"] == 0


# --- the web shop's ID as barcode ----------------------------------------------------------------------------------

def test_the_preview_carries_the_shops_id_of_each_line_as_its_barcode(owner, shop):
    lines = upload(owner, invoice_pdf()).get_json()["lines"]
    assert [line["barcode"] for line in lines] == ["43000000000001", "43000000000004", "43992833229019"]    # refill, with spool, matte refill
    assert {url.split("/")[2] for url, _ in shop.calls} == {"eu.store.bambulab.com"}


def test_applying_stores_the_barcode_on_the_filament(owner):
    owner.post("/api/filament-library/invoice/apply", json={"lines": lines_of(owner)}, headers=H)
    assert {e["colour"]: e["barcode"] for e in library(owner)} == {"Grijs": "43000000000001", "Rood": "43000000000004", "Pruim": "43992833229019"}
    assert owner.get("/api/spools").get_json() == []



def test_a_known_filament_without_a_barcode_gets_one_but_one_that_has_one_keeps_it(owner):  # noqa: E501
    make(owner, "/api/filament-library", GREY)
    make(owner, "/api/filament-library", {**GREY, "sku": "A00-R0-1.75-1000-SPL", "colour": "Rood", "refill": False, "filament_id": "10200", "barcode": "mine"})
    lines = lines_of(owner)
    owner.post("/api/filament-library/invoice/apply", json={"lines": lines}, headers=H)
    assert {e["colour"]: e["barcode"] for e in library(owner)}["Grijs"] == "43000000000001"
    assert {e["colour"]: e["barcode"] for e in library(owner)}["Rood"] == "mine"


def test_without_the_shop_the_import_still_works_and_says_so(owner, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")))
    invoice = upload(owner, invoice_pdf()).get_json()
    assert [line["barcode"] for line in invoice["lines"]] == ["", "", ""] and "Bambu Lab" in invoice["warnings"][0]
    lines = invoice["lines"]
    assert owner.post("/api/filament-library/invoice/apply", json={"lines": lines}, headers=H).get_json()["added"] == 3


def test_a_line_the_shop_does_not_know_is_counted_in_a_warning(owner, shop):
    shop.pages.pop("https://eu.store.bambulab.com/nl/products/pla-matte")
    invoice = upload(owner, invoice_pdf()).get_json()
    assert invoice["lines"][2]["barcode"] == "" and "1 regel" in invoice["warnings"][0]


# --- a roll typed in by hand may go in the library too ------------------------------------------------------------------

ROLL = {"brand": "Bambu Lab", "product_type": "Basic", "material": "PLA", "colour": "Grijs", "colour_hex": "#9e9e9e", "roll_weight_g": 1000, "price": "9.08",
        "remaining_g": 640, "barcode": "555", "diameter_mm": "1.75", "print_temp_c": 220, "bed_temp_c": 55, "notes": "kast"}


def test_a_new_roll_can_be_put_in_the_library_at_the_same_time_without_its_price_or_what_is_left(owner):
    make(owner, "/api/spools", {**ROLL, "add_to_library": True})
    [entry] = library(owner)
    assert (entry["brand"], entry["material"], entry["product_type"], entry["colour"], entry["colour_hex"], entry["barcode"]) == \
        ("Bambu Lab", "PLA", "Basic", "Grijs", "#9e9e9e", "555")
    assert (entry["roll_weight_g"], entry["diameter_mm"], entry["print_temp_c"], entry["bed_temp_c"]) == ("1000.0", "1.75", 220, 55)
    assert entry["price"] is None and entry["notes"] == ""                      # the price is the roll's, and so are the notes


def test_a_roll_is_not_put_in_the_library_unless_it_says_so(owner):
    make(owner, "/api/spools", ROLL)
    make(owner, "/api/spools", {**ROLL, "colour": "Rood", "barcode": "", "add_to_library": False})
    make(owner, "/api/spools", {**ROLL, "colour": "Blauw", "barcode": "", "add_to_library": "yes"})
    assert library(owner) == []


def test_a_roll_of_a_filament_that_is_already_in_the_library_does_not_add_it_again(owner):
    make(owner, "/api/filament-library", GREY)                                       # has a SKU; the roll has not, but is the same filament
    make(owner, "/api/spools", {**ROLL, "barcode": "", "add_to_library": True})
    make(owner, "/api/spools", {**ROLL, "colour": "GRIJS", "brand": "bambu lab", "barcode": "", "add_to_library": True})
    assert len(library(owner)) == 1
    make(owner, "/api/spools", {**ROLL, "colour": "Zwart", "barcode": "777", "add_to_library": True})
    make(owner, "/api/spools", {**ROLL, "colour": "Zwart (nieuw)", "barcode": "777", "add_to_library": True})     # the same barcode is the same filament
    assert sorted(e["colour"] for e in library(owner)) == ["Grijs", "Zwart"]


def test_a_roll_that_is_refused_puts_nothing_in_the_library(owner):
    assert owner.post("/api/spools", json={**ROLL, "price": "-1", "add_to_library": True}, headers=H).status_code == 400
    assert library(owner) == []


def test_changing_a_roll_never_touches_the_library(owner):
    roll = make(owner, "/api/spools", ROLL)
    assert owner.patch(f"/api/spools/{roll['id']}", json={"colour": "Rood", "add_to_library": True}, headers=H).status_code == 200
    assert library(owner) == []


# --- a contribution to the shared library -----------------------------------------------------------------------------

def test_a_contribution_is_what_the_shared_library_lacks_without_the_notes(owner, remote):
    remote.reply = shared(GREY)
    make(owner, "/api/filament-library", {**GREY, "notes": "kast 2"})                                  # in the shared library already
    make(owner, "/api/filament-library", {"brand": "Sunlu", "material": "PETG", "colour": "Zwart", "roll_weight_g": 1000, "price": "14.5",
                                          "barcode": "123", "notes": "mijn eigen tekst"})
    before = library(owner)
    res = owner.post("/api/filament-library/contribution", headers=H).get_json()
    assert res["already_there"] == 1 and len(res["entries"]) == 1
    [entry] = res["entries"]
    assert (entry["brand"], entry["colour"], entry["barcode"], entry["price"]) == ("Sunlu", "Zwart", "123", 14.5)
    assert "notes" not in entry and "id" not in entry and "created_at" not in entry
    assert library(owner) == before                                                                        # nothing is written


def test_a_filament_the_shared_library_knows_under_another_name_is_not_offered_again(owner, remote):
    remote.reply = shared({**GREY, "colour": "Gray"})                                                      # the same SKU, however it is named
    make(owner, "/api/filament-library", GREY)
    assert owner.post("/api/filament-library/contribution", headers=H).get_json() == {"entries": [], "completions": [], "already_there": 1}


def test_a_contribution_is_not_offered_when_the_source_is_the_owners_own(owner, remote, app):
    assert owner.get("/api/filament-library/source").get_json()["contribute_url"].startswith("https://github.com/Flux76HQ/3dprint_pricing/issues/new")
    app.config["APP_CONFIG"] = dataclasses.replace(app.config["APP_CONFIG"], filament_library_url="https://gist.githubusercontent.com/me/x/raw/f.json")
    assert owner.get("/api/filament-library/source").get_json()["contribute_url"] == ""
    assert owner.post("/api/filament-library/contribution", headers=H).status_code == 404 and remote.calls == []


def test_a_contribution_with_an_unreachable_source_fails_cleanly(owner, remote):
    remote.reply = requests.ConnectionError("down")
    res = owner.post("/api/filament-library/contribution", headers={**H, **NL})
    assert res.status_code == 502 and "niet bereikbaar" in res.get_json()["error"]


def contribution(owner, **headers):
    return owner.post("/api/filament-library/contribution", headers={**H, **headers}).get_json()


def test_a_roll_the_library_lacks_is_offered_as_new_and_nothing_is_written(owner, remote):
    remote.reply = shared(GREY)
    make(owner, "/api/spools", {**ROLL, "colour": "Roze", "barcode": "9001", "price": "12.5", "notes": "kast"})            # no add_to_library: not in the library
    make(owner, "/api/spools", {**ROLL, "colour": "Roze", "barcode": "9001", "remaining_g": 10})                             # a second roll of the same filament
    before = (library(owner), owner.get("/api/spools").get_json())
    res = contribution(owner)
    [entry] = res["entries"]
    assert (entry["colour"], entry["barcode"], entry["source"]) == ("Roze", "9001", "roll")
    assert entry["price"] is None and "notes" not in entry and "remaining_g" not in entry          # the price and the rest are the roll's
    assert (library(owner), owner.get("/api/spools").get_json()) == before


def test_an_archived_roll_and_a_roll_that_fits_two_entries_are_not_offered(owner, remote):
    remote.reply = shared()
    make(owner, "/api/spools", {**ROLL, "colour": "Blauw", "barcode": "", "archived": True})
    make(owner, "/api/filament-library", GREY)
    make(owner, "/api/filament-library", {**GREY, "sku": "A00-D0-1.75-1000-SPL", "refill": False, "filament_id": "10104"})
    make(owner, "/api/spools", {**ROLL, "barcode": ""})                                            # the same filament as both entries: unclear which
    assert sorted(e["colour"] for e in contribution(owner)["entries"]) == ["Grijs", "Grijs"]        # only the two library entries, no roll


def test_a_filament_the_shared_library_lacks_fields_of_is_offered_as_a_completion_that_only_fills_blanks(owner, remote):
    remote.reply = shared({**GREY, "colour_hex": "#111111"})                                       # the shared entry has a colour code but no temperatures
    make(owner, "/api/filament-library", {**GREY, "print_temp_c": 220, "bed_temp_c": 55, "colour_hex": "#999999", "price": "25"})
    res = contribution(owner)
    assert res["entries"] == [] and res["already_there"] == 0
    [item] = res["completions"]
    assert item["fills"] == ["print_temp_c", "bed_temp_c"]                                          # colour code and price are filled in already
    assert item["entry"]["print_temp_c"] == 220 and "notes" not in item["entry"]


def test_an_entry_that_adds_nothing_to_the_shared_one_is_already_there(owner, remote):
    remote.reply = shared({**GREY, "print_temp_c": 220, "bed_temp_c": 55, "colour_hex": "#9e9e9e"})
    make(owner, "/api/filament-library", {**GREY, "print_temp_c": 220, "bed_temp_c": 55, "colour_hex": "#9e9e9e"})
    assert contribution(owner) == {"entries": [], "completions": [], "already_there": 1}


def test_saving_a_roll_tells_what_happened_to_the_library(owner):
    assert "library" not in make(owner, "/api/spools", ROLL)                                       # not asked for
    assert make(owner, "/api/spools", {**ROLL, "colour": "Rood", "barcode": "", "add_to_library": True})["library"] == "added"
    make(owner, "/api/filament-library", GREY)
    make(owner, "/api/filament-library", {**GREY, "sku": "A00-D0-1.75-1000-SPL", "refill": False, "filament_id": "10104"})
    assert make(owner, "/api/spools", {**ROLL, "barcode": "", "add_to_library": True})["library"] == "unclear"


# --- the rolls in the filament list go to the library in one go ----------------------------------------------------------

def from_rolls(owner, query=""):
    return owner.post(f"/api/filament-library/from-rolls{query}", headers=H).get_json()


def test_syncing_the_rolls_adds_each_missing_filament_once_and_leaves_the_rolls_alone(owner):
    first = make(owner, "/api/spools", ROLL)
    make(owner, "/api/spools", {**ROLL, "remaining_g": 100})                                      # a second roll of the same filament
    make(owner, "/api/spools", {**ROLL, "colour": "Rood", "barcode": "", "colour_hex": "#ff0000"})
    before = owner.get("/api/spools").get_json()
    dry = from_rolls(owner, "?dry_run=1")
    assert (dry["dry_run"], dry["added"], dry["unchanged"]) == (True, 2, 1) and library(owner) == []      # a dry run writes nothing
    done = from_rolls(owner)
    assert (done["added"], done["updated"], done["unchanged"], done["unclear"]) == (2, 0, 1, 0)
    assert sorted(e["colour"] for e in library(owner)) == ["Grijs", "Rood"]
    assert all(e["price"] is None and e["notes"] == "" for e in library(owner))                   # the price and notes are the roll's
    assert owner.get("/api/spools").get_json() == before and any(r["id"] == first["id"] for r in before)
    again = from_rolls(owner)
    assert (again["added"], again["updated"], again["unchanged"]) == (0, 0, 3)


def test_syncing_the_rolls_skips_archived_ones_and_completes_known_entries(owner):
    make(owner, "/api/spools", {**ROLL, "colour": "Blauw", "barcode": "", "archived": True})
    mine = make(owner, "/api/filament-library", {**GREY, "print_temp_c": None, "bed_temp_c": None, "colour_hex": ""})
    make(owner, "/api/spools", {**ROLL, "barcode": ""})                                           # the same filament as GREY, which lacks the temperatures
    done = from_rolls(owner)
    assert (done["added"], done["updated"]) == (0, 1)
    [entry] = library(owner)
    assert entry["id"] == mine["id"] and (entry["print_temp_c"], entry["bed_temp_c"], entry["colour_hex"]) == (220, 55, "#9e9e9e")
    assert entry["sku"] == GREY["sku"] and entry["price"] == mine["price"]                        # nothing that was filled in is overwritten


def test_a_roll_that_fits_two_entries_is_counted_as_unclear_and_touches_nothing(owner):
    make(owner, "/api/filament-library", GREY)
    make(owner, "/api/filament-library", {**GREY, "sku": "A00-D0-1.75-1000-SPL", "refill": False, "filament_id": "10104"})
    make(owner, "/api/spools", {**ROLL, "barcode": ""})
    assert from_rolls(owner)["unclear"] == 1 and len(library(owner)) == 2


# --- no filament twice ------------------------------------------------------------------------------------------------

PLUM = {"brand": "Bambu Lab", "product_type": "Matte", "material": "PLA", "colour": "Pruim", "roll_weight_g": 1000, "diameter_mm": "1.75"}


def refused(res, fragment="al in de bibliotheek"):
    assert res.status_code == 409 and fragment in res.get_json()["error"], res.get_json()


@pytest.mark.parametrize("change", [
    {"sku": " a00-d0-1.75-1000-splfree "},                                         # the same SKU, however it is typed
    {"sku": "", "barcode": "", "filament_id": "10103", "colour": "anders"},         # the same supplier ID of the same kind
    {"sku": "", "filament_id": "", "brand": "BAMBU LAB", "colour": " grijs "},      # the same name, weight and diameter
])
def test_typing_in_a_filament_that_is_already_there_is_refused(owner, change):
    make(owner, "/api/filament-library", GREY)
    refused(owner.post("/api/filament-library", json={**GREY, **change}, headers={**H, **NL}))
    assert len(library(owner)) == 1


def test_the_same_barcode_is_the_same_filament_even_under_another_name(owner):
    make(owner, "/api/filament-library", {**PLUM, "barcode": "4300"})
    refused(owner.post("/api/filament-library", json={**PLUM, "colour": "Plum", "barcode": " 4300 "}, headers={**H, **NL}))


def test_what_differs_in_refill_weight_or_diameter_is_another_filament(owner):
    make(owner, "/api/filament-library", PLUM)
    for change in ({"refill": True}, {"roll_weight_g": 500}, {"diameter_mm": "2.85"}, {"colour": "Ivoor"}, {"brand": "Sunlu"}):
        make(owner, "/api/filament-library", {**PLUM, **change})
    assert len(library(owner)) == 6


def test_a_change_that_makes_an_entry_a_copy_of_another_is_refused_but_other_changes_are_fine(owner):
    a = make(owner, "/api/filament-library", PLUM)
    b = make(owner, "/api/filament-library", {**PLUM, "colour": "Ivoor"})
    assert owner.patch(f"/api/filament-library/{b['id']}", json={"notes": "x", "price": "9"}, headers=H).status_code == 200
    refused(owner.patch(f"/api/filament-library/{b['id']}", json={"colour": "pruim"}, headers={**H, **NL}))
    assert owner.patch(f"/api/filament-library/{a['id']}", json={"colour": "Pruim", "notes": "own"}, headers=H).status_code == 200      # itself is no clash
    assert {e["colour"] for e in library(owner)} == {"Pruim", "Ivoor"}


def test_an_entry_that_was_already_a_copy_before_can_still_be_edited(owner, app):
    import psycopg
    a = make(owner, "/api/filament-library", PLUM)
    with psycopg.connect(app.config["APP_CONFIG"].database_url, autocommit=True) as conn:       # as an older release may have left it
        conn.execute("INSERT INTO filament_library (brand, product_type, material, colour, roll_weight_g, diameter_mm) VALUES ('Bambu Lab', 'Matte', 'PLA', 'Pruim', 1000, 1.75)")
    assert owner.patch(f"/api/filament-library/{a['id']}", json={"notes": "fine"}, headers=H).status_code == 200


def test_two_requests_at_once_for_the_same_filament_make_one_entry(owner, app):
    from concurrent.futures import ThreadPoolExecutor

    def post(_):
        client = app.test_client()
        client.set_cookie("pp_session", owner.get_cookie("pp_session").value)
        return client.post("/api/filament-library", json=PLUM, headers=H).status_code
    with ThreadPoolExecutor(8) as pool:
        statuses = sorted(pool.map(post, range(8)))
    assert statuses == [201] + [409] * 7 and len(library(owner)) == 1


def test_an_import_or_sync_cannot_add_a_filament_twice_nor_turn_one_into_a_copy(owner, remote):
    make(owner, "/api/filament-library", PLUM)
    make(owner, "/api/filament-library", {**PLUM, "colour": "Ivoor", "barcode": "9"})
    doc = {"format": "printpricing-filament-library", "format_version": 1, "filaments": [{**PLUM, "price": "5"}, {**PLUM, "colour": "pruim", "price": "6"}]}
    done = owner.post("/api/filament-library/import", json=doc, headers=H).get_json()
    assert (done["added"], done["updated"]) == (0, 2) and len(library(owner)) == 2           # both lines are the one existing entry
    assert {e["price"] for e in library(owner)} == {"6.00", None}
    bad = {**doc, "filaments": [{**PLUM, "barcode": "9"}]}                                    # would give the first entry the barcode of the second
    for path in ("/api/filament-library/import?dry_run=1", "/api/filament-library/import"):
        res = owner.post(path, json=bad, headers={**H, **NL})
        assert res.status_code == 400 and "Regel 1" in res.get_json()["error"] and "al in de bibliotheek" in res.get_json()["error"]
    remote.reply = shared(*bad["filaments"])
    assert owner.post("/api/filament-library/sync", headers=H).status_code == 400
    assert {e["barcode"] for e in library(owner)} == {"", "9"}


def test_an_invoice_line_that_is_a_filament_typed_in_before_completes_it_instead_of_adding_it_again(owner):
    mine = make(owner, "/api/filament-library", {"brand": "Bambu Lab", "product_type": "Basic", "material": "PLA", "colour": "Grijs", "refill": True,
                                                 "roll_weight_g": 1000, "diameter_mm": "1.75", "print_temp_c": 215, "notes": "mijn"})
    lines = lines_of(owner)
    res = owner.post("/api/filament-library/invoice/apply", json={"lines": [lines[0], lines[0]]}, headers=H).get_json()
    assert (res["added"], res["updated"], res["unchanged"]) == (0, 1, 1)
    [row] = library(owner)
    assert row["id"] == mine["id"] and (row["sku"], row["filament_id"], row["barcode"], row["price"]) == ("A00-D0-1.75-1000-SPLFREE", "10103", "43000000000001", "19.32")
    assert (row["print_temp_c"], row["notes"]) == (215, "mijn")                                # what was entered stays


def test_a_backup_with_the_same_filament_twice_is_refused(owner):
    make(owner, "/api/filament-library", PLUM)
    doc = owner.get("/api/backup", headers=H).get_json()
    doc["filament_library"].append({**doc["filament_library"][0], "colour": "PRUIM"})
    res = owner.post("/api/backup/restore", json=doc, headers={**H, **NL})
    assert res.status_code == 400 and "al in de bibliotheek" in res.get_json()["error"]
    assert len(library(owner)) == 1


# --- an entry already there is completed, not overwritten, by a roll ----------------------------------------------------

def test_a_roll_completes_the_entry_it_belongs_to_with_what_that_lacks(owner):
    make(owner, "/api/filament-library", {**GREY, "colour_hex": "#111111", "print_temp_c": 200})        # refill, with SKU, no barcode, no bed temperature
    make(owner, "/api/spools", {**ROLL, "refill": True, "add_to_library": True})                         # same name, weight and diameter
    [row] = library(owner)
    assert (row["barcode"], row["bed_temp_c"]) == ("555", 55)                                            # filled in
    assert (row["colour_hex"], row["print_temp_c"], row["price"], row["sku"]) == ("#111111", 200, "19.32", GREY["sku"])   # not overwritten


def test_a_roll_with_a_known_barcode_completes_that_entry(owner):
    make(owner, "/api/filament-library", {**PLUM, "barcode": "555"})
    make(owner, "/api/spools", {**ROLL, "colour": "Anders", "colour_hex": "#abcdef", "add_to_library": True})
    [row] = library(owner)
    assert (row["colour"], row["colour_hex"], row["print_temp_c"]) == ("Pruim", "#abcdef", 220)


def test_a_roll_that_could_be_a_refill_or_a_spool_changes_neither(owner):
    make(owner, "/api/filament-library", {**GREY, "refill": True, "sku": "A"})
    make(owner, "/api/filament-library", {**GREY, "refill": False, "sku": "B", "filament_id": "10103"})
    make(owner, "/api/spools", {**ROLL, "add_to_library": True})
    assert len(library(owner)) == 2 and {e["barcode"] for e in library(owner)} == {""}


def test_a_roll_from_the_shop_brings_its_filament_id_and_refill_to_the_library(owner):
    make(owner, "/api/spools", {**ROLL, "barcode": "43992833229019", "add_to_library": True, "library": {"filament_id": "10103", "refill": True}})
    [entry] = library(owner)
    assert (entry["filament_id"], entry["refill"], entry["barcode"]) == ("10103", True, "43992833229019")


def test_with_a_known_refill_the_roll_is_matched_exactly_and_completes_only_that_one(owner):
    make(owner, "/api/filament-library", {**GREY, "refill": True, "sku": "A", "filament_id": ""})
    spool = make(owner, "/api/filament-library", {**GREY, "refill": False, "sku": "B", "filament_id": ""})
    make(owner, "/api/spools", {**ROLL, "add_to_library": True, "library": {"filament_id": "10103", "refill": False}})
    assert {e["sku"]: (e["barcode"], e["filament_id"]) for e in library(owner)} == {"A": ("", ""), "B": ("555", "10103")} and spool


@pytest.mark.parametrize("extra", ["text", 5, ["x"], {"refill": "yes", "filament_id": 5}])
def test_what_the_form_adds_about_the_filament_is_never_trusted(owner, extra):
    make(owner, "/api/spools", {**ROLL, "add_to_library": True, "library": extra})
    [entry] = library(owner)
    assert entry["refill"] is False and entry["colour"] == "Grijs"
