"""Looking up the web shop's ID of a filament: found by filament ID, refill and weight, and only ever on the EU shop."""
import re

import pytest
import requests

from app import bambu_store
from tests.bambu_invoices import STORE_PAGES, Reply, Shop, store_page

EU = "https://eu.store.bambulab.com/nl/products/"
PLUM = {"name": "PLA Matte", "filament_id": "11204", "refill": True, "roll_weight_g": "1000"}


@pytest.fixture(autouse=True)
def shop(monkeypatch):
    bambu_store._cache.clear()
    fake = Shop()
    monkeypatch.setattr(requests, "get", fake.get)
    return fake


def test_the_store_id_is_found_by_filament_id_and_refill(shop):
    result = bambu_store.lookup([PLUM, {**PLUM, "refill": False}])
    assert result == {"ids": {0: "43992833229019", 1: "43992833229020"}, "reachable": True}      # the refill and the roll with spool have an ID each


def test_a_product_page_may_be_called_with_or_without_filament(shop):
    grey = {"name": "PLA Basic", "filament_id": "10103", "refill": True, "roll_weight_g": "1000"}
    assert bambu_store.lookup([grey])["ids"] == {0: "43000000000001"}
    assert [url for url, _ in shop.calls] == [f"{EU}pla-basic", f"{EU}pla-basic-filament"]       # the plain name is a 404, the next one is the page


def test_a_line_the_shop_does_not_list_is_left_without_an_id(shop):
    assert bambu_store.lookup([{**PLUM, "filament_id": "99999"}, {**PLUM, "roll_weight_g": "500"}, {**PLUM, "filament_id": ""},
                               {"name": "PETG HF", "filament_id": "1", "refill": False, "roll_weight_g": "1000"}]) == {"ids": {}, "reachable": True}


def test_a_page_is_fetched_once_for_all_the_lines_of_a_product(shop):
    bambu_store.lookup([PLUM, PLUM, {**PLUM, "refill": False}])
    bambu_store.lookup([PLUM])
    assert [url for url, _ in shop.calls] == [f"{EU}pla-matte"]


def test_only_the_eu_shop_is_contacted_without_following_redirects_on_its_own(shop):
    bambu_store.lookup([PLUM])
    [(url, kwargs)] = shop.calls
    assert url.startswith("https://eu.store.bambulab.com/") and kwargs["allow_redirects"] is False and kwargs["timeout"] <= 15


def test_a_redirect_within_the_eu_shop_is_followed(shop):
    shop.pages[f"{EU}pla-matte"] = Reply(status=301, headers={"Location": "/nl/products/pla-matte-new"})
    shop.pages[f"{EU}pla-matte-new"] = Reply(store_page(STORE_PAGES["pla-matte"]))
    assert bambu_store.lookup([PLUM])["ids"] == {0: "43992833229019"}


@pytest.mark.parametrize("location", ["https://us.store.bambulab.com/products/pla-matte", "https://eu.store.bambulab.com.evil.example/x",
                                      "http://eu.store.bambulab.com/nl/products/pla-matte"])
def test_a_redirect_to_another_shop_ends_the_lookup_because_its_ids_are_not_ours(shop, location):
    shop.pages[f"{EU}pla-matte"] = Reply(status=302, headers={"Location": location})
    assert bambu_store.lookup([PLUM]) == {"ids": {}, "reachable": False}
    assert len(shop.calls) == 1                                                  # and the other address was not even asked


@pytest.mark.parametrize("reply", [Reply(status=500), Reply(b"x" * (bambu_store.MAX_PAGE_BYTES + 1)), requests.ConnectionError("down"),
                                   Reply(status=302, headers={"Location": "/nl/products/pla-matte"})])
def test_a_shop_that_fails_is_reported_not_raised(shop, reply):
    shop.pages[f"{EU}pla-matte"] = reply
    if isinstance(reply, Exception):
        shop.get = lambda *a, **k: (_ for _ in ()).throw(reply)
        requests.get = shop.get
    assert bambu_store.lookup([PLUM]) == {"ids": {}, "reachable": False}


def test_a_page_without_variants_gives_nothing(shop):
    shop.pages[f"{EU}pla-matte"] = Reply(b"<html>no json here</html>")
    assert bambu_store.lookup([PLUM]) == {"ids": {}, "reachable": True}


def test_the_number_of_products_looked_up_for_one_invoice_is_limited(shop):
    lines = [{**PLUM, "name": f"Kind {n}"} for n in range(bambu_store.MAX_PRODUCTS + 5)]
    bambu_store.lookup(lines)
    assert len({url for url, _ in shop.calls}) <= bambu_store.MAX_PRODUCTS * 2


def test_slugs():
    assert bambu_store.slugs("PLA Matte") == ["pla-matte", "pla-matte-filament"]
    assert bambu_store.slugs("PETG HF") == ["petg-hf", "petg-hf-filament"]
    assert bambu_store.slugs("../../etc") == ["etc", "etc-filament"] and bambu_store.slugs("") == []


# --- the colours of a product, as filaments ------------------------------------------------------------------------------

def variant(name, product, sku="1"):
    return bambu_store.parse_variant({"sku": sku, "name": name, "product": product})


def test_a_variant_is_read_as_a_filament():
    assert variant("PLA Matte - Plum (11204) / Refill / 1kg", "PLA Matte", "43992833229019") == {
        "id": "43992833229019", "product": "PLA Matte", "material": "PLA", "product_type": "Matte", "colour": "Plum", "filament_id": "11204",
        "refill": True, "roll_weight_g": 1000, "diameter_mm": 1.75}
    spool = variant("PLA Matte - Plum (11204) / Filament with spool / 1 kg", "PLA Matte")
    assert spool["refill"] is False and spool["roll_weight_g"] == 1000


@pytest.mark.parametrize("name, product, expected", [
    ("PETG Basic - Black(30105) / Refill / 1kg", "PETG Basic", ("PETG", "Basic", "Black", "30105", True, 1000)),            # no space before the bracket
    ("PA6-CF - Black (72100) / Filament with spool / 0.5kg", "PA6-CF", ("PA6-CF", "", "Black", "72100", False, 500)),
    ("PPA-CF - Black (73100) / Filament with spool / 0.75 kg", "PPA-CF", ("PPA-CF", "", "Black", "73100", False, 750)),
    ("PLA Tough+ - White (12107) / Filament with Spool / 1kg", "PLA Tough+", ("PLA", "Tough+", "White", "12107", False, 1000)),
    ("PLA Silk Multi-Color - Gilded Rose (13901) / Filament with spool / 1 kg", "PLA Silk Multi-Color", ("PLA", "Silk Multi-Color", "Gilded Rose", "13901", False, 1000)),
    ("TPU 85A / TPU 90A - TPU 85A / Light Cyan (51500) / 1 kg", "TPU 85A / TPU 90A", ("TPU", "85A / TPU 90A", "TPU 85A / Light Cyan", "51500", False, 1000)),
    ("Support for PLA/PETG - Nature (65102) / Filament with spool / 0.5 kg", "Support for PLA/PETG", ("", "Support for PLA/PETG", "Nature", "65102", False, 500)),
    ("PLA Basic - Grijs (10103) / Bijvullen / 1kg", "PLA Basic", ("PLA", "Basic", "Grijs", "10103", True, 1000)),                # the Dutch shop
])
def test_the_shapes_the_shop_uses_are_all_read(name, product, expected):
    got = variant(name, product)
    assert (got["material"], got["product_type"], got["colour"], got["filament_id"], got["refill"], got["roll_weight_g"]) == expected


def test_a_name_without_a_filament_id_is_no_variant():
    assert variant("PLA Matte - Plum / Refill / 1kg", "PLA Matte") is None
    assert variant("Spool holder", "") is None


def test_the_catalog_of_a_product_is_its_colours_and_only_listed_products_are_fetched(shop):
    colours = bambu_store.catalog("pla-matte")
    assert [(c["colour"], c["refill"], c["id"]) for c in colours] == [("Plum", True, "43992833229019"), ("Plum", False, "43992833229020")]
    assert bambu_store.catalog("not-a-product") is None and bambu_store.catalog("../../etc/passwd") is None
    assert [url for url, _ in shop.calls] == [f"{EU}pla-matte"]                 # nothing else was asked for


def test_every_product_of_the_list_has_a_name_and_a_unique_page():
    slugs = [slug for slug, _ in bambu_store.CATALOG]
    assert len(slugs) == len(set(slugs)) and all(name for _, name in bambu_store.CATALOG)
    assert all(re.fullmatch(r"[a-z0-9-]+", slug) for slug in slugs)
