"""The filament library: entries, the JSON file in and out, the Bambu Lab invoice and the sync from GitHub."""
import dataclasses
import io
import json
from pathlib import Path

import pytest
import requests

from tests.bambu_invoices import FILAMENT, invoice_pdf
from tests.test_auth_api import H
from tests.test_domain_api import make, owner  # noqa: F401  (fixture)

NL = {"X-Lang": "nl"}
GREY = {"brand": "Bambu Lab", "product_type": "Basic", "material": "PLA", "colour": "Grijs", "filament_id": "10103",
        "sku": "A00-D0-1.75-1000-SPLFREE", "refill": True, "roll_weight_g": 1000, "diameter_mm": "1.75", "price": "19.32"}


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
                         ("post", "/api/filament-library/import"), ("post", "/api/filament-library/invoice")):
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
    assert invoice["order_number"] == "EN000000000000000001" and invoice["rolls_on_shelf"] == 0 and "warning" not in invoice
    assert len(library(owner)) == 1 and owner.get("/api/spools").get_json() == []


def test_an_invoice_whose_lines_do_not_add_up_carries_a_warning(owner):
    invoice = upload(owner, invoice_pdf(total="99.00")).get_json()
    assert "99.00" in invoice["warning"]


@pytest.mark.parametrize("content, fragment", [(b"nope", "geen PDF"), (invoice_pdf(bambu=False), "geen Bambu Lab-factuur")])
def test_a_file_that_is_no_bambu_invoice_is_refused_with_a_reason(owner, content, fragment):
    res = owner.post("/api/filament-library/invoice", data={"file": (io.BytesIO(content), "x.pdf")}, headers={**H, **NL}, content_type="multipart/form-data")
    assert res.status_code == 422 and fragment in res.get_json()["error"]
    assert owner.post("/api/filament-library/invoice", headers=H).status_code == 400            # no file at all


def test_applying_an_invoice_adds_the_filaments_and_the_rolls_at_the_price_that_was_paid(owner):
    lines = lines_of(owner)
    for line in lines:
        line["rolls"] = line["quantity"]
    res = owner.post("/api/filament-library/invoice/apply", json={"order_number": "EN000000000000000001", "lines": lines}, headers=H).get_json()
    assert (res["added"], res["updated"], res["rolls"]) == (3, 0, 4)
    entries = {e["colour"]: e for e in library(owner)}
    assert entries["Rood"]["price"] == "21.84" and entries["Rood"]["filament_id"] == "10200" and entries["Grijs"]["refill"] is True
    rolls = [r for r in owner.get("/api/spools").get_json() if r["colour"] == "Rood"]
    assert len(rolls) == 2 and {r["price"] for r in rolls} == {"10.26"} and {r["remaining_g"] for r in rolls} == {"1000.0"}
    assert all("EN000000000000000001" in r["notes"] for r in rolls)
    assert upload(owner, invoice_pdf()).get_json()["rolls_on_shelf"] == 4                         # the invoice is known to be on the shelf now


def test_applying_to_a_known_filament_only_brings_the_new_price_and_keeps_what_you_entered(owner):
    mine = make(owner, "/api/filament-library", {**GREY, "price": "15", "print_temp_c": 215, "colour_hex": "#aaaaaa", "notes": "mijn"})
    grey = lines_of(owner)[0]
    grey["colour"], grey["colour_hex"] = "Gris", "#000000"                                        # the invoice must not rename or recolour it
    res = owner.post("/api/filament-library/invoice/apply", json={"lines": [grey]}, headers=H).get_json()
    assert (res["added"], res["updated"], res["rolls"]) == (0, 1, 0)
    [row] = library(owner)
    assert row["id"] == mine["id"] and row["price"] == "19.32"
    assert (row["colour"], row["colour_hex"], row["print_temp_c"], row["notes"]) == ("Grijs", "#aaaaaa", 215, "mijn")


def test_rolls_can_be_added_without_adding_the_filament_to_the_library(owner):
    red = lines_of(owner)[1]
    red.update(add_to_library=False, rolls=1)
    assert owner.post("/api/filament-library/invoice/apply", json={"lines": [red]}, headers=H).get_json()["rolls"] == 1
    assert library(owner) == [] and len(owner.get("/api/spools").get_json()) == 1


def test_a_roll_from_an_invoice_takes_over_the_notification_of_its_kind(owner):
    owner.post("/api/spools", json={"brand": "Bambu Lab", "product_type": "Basic", "material": "PLA", "colour": "Rood", "roll_weight_g": 1000,
                                    "price": 1, "remaining_g": 100, "notify_low": True}, headers=H)
    red = lines_of(owner)[1]
    red["rolls"] = 1
    owner.post("/api/filament-library/invoice/apply", json={"lines": [red]}, headers=H)
    assert [r["notify_low"] for r in owner.get("/api/spools").get_json()] == [True, True]


@pytest.mark.parametrize("body", [{}, {"lines": []}, {"lines": ["x"]}, {"lines": [{"brand": "x", "roll_weight_g": 0}]},
                                  {"lines": [{"brand": "x", "roll_weight_g": 1000, "rolls": 100, "paid_price": 1}]},
                                  {"lines": [{"brand": "x", "roll_weight_g": 1000, "rolls": 1, "paid_price": "-1"}]}])
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
    assert owner.get("/api/filament-library/source").get_json() == {"url": ""}
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


def test_the_shared_library_file_in_the_repository_is_a_valid_library_without_prices(owner):
    path = Path(__file__).resolve().parents[2] / "library" / "filaments.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert all("price" not in row for row in doc["filaments"])               # prices differ per shop and per day
    res = owner.post("/api/filament-library/import", json=doc, headers=H).get_json()
    assert res["added"] == len(doc["filaments"]) > 0 and res["updated"] == 0
