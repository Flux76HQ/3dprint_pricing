"""The Bambu Lab products and colours for the new-roll form."""
import pytest
import requests

from app import bambu_store
from tests.bambu_invoices import Reply, Shop
from tests.test_auth_api import H
from tests.test_domain_api import owner  # noqa: F401  (fixture)

EU = "https://eu.store.bambulab.com/nl/products/"


@pytest.fixture(autouse=True)
def shop(monkeypatch):
    bambu_store._cache.clear()
    fake = Shop()
    monkeypatch.setattr(requests, "get", fake.get)
    return fake


def test_the_catalog_needs_a_session(client):
    assert client.get("/api/bambu/products").status_code == 401
    assert client.get("/api/bambu/products/pla-matte").status_code == 401


def test_the_products_are_the_fixed_list(owner, shop):
    products = owner.get("/api/bambu/products").get_json()
    assert {"slug": "pla-matte", "name": "PLA Matte"} in products and len(products) == len(bambu_store.CATALOG)
    assert shop.calls == []                                                       # the list is ours: the shop is not asked


def test_the_colours_of_a_product_come_from_the_shop_with_their_store_id(owner):
    res = owner.get("/api/bambu/products/pla-matte", headers=H).get_json()
    assert [(c["colour"], c["filament_id"], c["refill"], c["id"], c["roll_weight_g"], c["diameter_mm"]) for c in res["colours"]] == [
        ("Plum", "11204", True, "43992833229019", 1000, 1.75), ("Plum", "11204", False, "43992833229020", 1000, 1.75)]


@pytest.mark.parametrize("slug", ["not-a-product", "..%2F..%2Fetc", "PLA-MATTE"])
def test_a_product_that_is_not_in_the_list_is_never_looked_up(owner, shop, slug):
    assert owner.get(f"/api/bambu/products/{slug}", headers=H).status_code == 404
    assert shop.calls == []


def test_a_listed_product_the_shop_no_longer_has_is_a_404(owner, shop):
    shop.pages.pop(EU + "pla-matte")
    res = owner.get("/api/bambu/products/pla-matte", headers={**H, "X-Lang": "nl"})
    assert res.status_code == 404 and "niet (meer)" in res.get_json()["error"]


@pytest.mark.parametrize("reply", [Reply(status=500), Reply(status=302, headers={"Location": "https://us.store.bambulab.com/products/pla-matte"})])
def test_a_shop_that_cannot_be_used_is_a_502_with_a_message(owner, shop, reply):
    shop.pages[EU + "pla-matte"] = reply
    res = owner.get("/api/bambu/products/pla-matte", headers={**H, "X-Lang": "nl"})
    assert res.status_code == 502 and "kon niet worden geraadpleegd" in res.get_json()["error"]
