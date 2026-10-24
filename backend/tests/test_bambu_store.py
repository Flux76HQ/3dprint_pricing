"""Looking up the web shop's ID of a filament: found by filament ID, refill and weight, and only ever on the EU shop."""
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
