
import pytest

from tests.test_auth_api import H, post
from tests.test_domain_api import owner  # noqa: F401  (fixture)
from tests.test_orders import customer, line, new_order


def make_customer(owner, **extra):
    res = owner.post("/api/customers", json={"name": "Anna de Vries", **extra}, headers=H)
    return res


def test_every_customer_endpoint_needs_a_session(client):
    zero = "0" * 8 + "-0000-0000-0000-" + "0" * 12
    for method, path in (("get", "/api/customers"), ("post", "/api/customers"), ("get", f"/api/customers/{zero}"),
                         ("put", f"/api/customers/{zero}"), ("delete", f"/api/customers/{zero}")):
        assert getattr(client, method)(path).status_code == 401, (method, path)


def test_a_customer_gets_the_next_free_number_unless_one_is_given(owner):
    first = make_customer(owner).get_json()
    assert first["number"] == "1" and first["name"] == "Anna de Vries" and first["orders"] == 0
    assert make_customer(owner, name="Bram").get_json()["number"] == "2"
    assert make_customer(owner, name="Claus", number="K9999").get_json()["number"] == "K9999"
    assert make_customer(owner, name="Dirk").get_json()["number"] == "3"          # a number that is not a whole number is not counted
    assert make_customer(owner, name="Eef", number="50").get_json()["number"] == "50"
    assert make_customer(owner, name="Fien").get_json()["number"] == "51"


def test_a_customer_number_is_unique_whatever_the_case(owner):
    make_customer(owner, number="K1")
    taken = make_customer(owner, name="Ander", number="k1")
    assert taken.status_code == 409 and "k1" in taken.get_json()["error"]
    other = make_customer(owner, name="Ander", number="K2").get_json()
    clash = owner.put(f"/api/customers/{other['id']}", json={"name": "Ander", "number": "K1"}, headers=H)
    assert clash.status_code == 409
    assert owner.get(f"/api/customers/{other['id']}").get_json()["number"] == "K2"


@pytest.mark.parametrize("change", [{"name": ""}, {"name": "x" * 121}, {"email": "geen-adres"}, {"number": "x" * 41}, {"city": "x" * 101},
                                    {"notes": "x" * 2001}, {"phone": "x" * 41}])
def test_a_customer_that_makes_no_sense_is_refused(owner, change):
    assert make_customer(owner, **change).status_code == 400
    assert owner.get("/api/customers").get_json() == []


def test_customers_can_be_found_and_are_listed_by_name(owner):
    make_customer(owner, name="bram bakker", city="Utrecht", email="bram@example.nl")
    make_customer(owner, name="Anna de Vries", city="Zwolle", number="A7")
    names = lambda q="": [c["name"] for c in owner.get("/api/customers" + q).get_json()]      # noqa: E731
    assert names() == ["Anna de Vries", "bram bakker"]
    assert names("?q=vries") == ["Anna de Vries"] and names("?q=utrecht") == ["bram bakker"] and names("?q=A7") == ["Anna de Vries"]
    assert names("?q=bram@") == ["bram bakker"] and names("?q=%25") == names() and names("?q=niemand") == []


def test_an_order_needs_a_customer_and_copies_its_details(owner):
    jan = customer(owner)
    order = new_order(owner, customer_id=jan["id"])
    assert order["customer_id"] == jan["id"] and order["customer_name"] == "Jan Jansen" and order["customer_number"] == "K9999"
    assert (order["address"], order["city"], order["email"]) == ("Kerkstraat 1", "Utrecht", "jan@example.nl")
    sent_ignored = owner.post("/api/orders", json={"customer_id": jan["id"], "customer_name": "Iemand anders", "city": "Elders"}, headers=H).get_json()
    assert sent_ignored["customer_name"] == "Jan Jansen" and sent_ignored["city"] == "Utrecht"      # the details come from the customer
    assert owner.get(f"/api/customers/{jan['id']}").get_json()["orders"] == 2
    listed = owner.get("/api/orders").get_json()[0]
    assert listed["customer_id"] == jan["id"] and listed["customer_number"] == "K9999"
    assert [o["number"] for o in owner.get("/api/orders?q=k9999").get_json()] == [o["number"] for o in owner.get("/api/orders").get_json()]


def test_editing_a_customer_updates_the_orders_without_an_invoice_only(owner):
    anna = make_customer(owner, city="Zwolle", number="A1").get_json()
    open_order = new_order(owner, customer_id=anna["id"])
    sent = new_order(owner, customer_id=anna["id"])
    assert post(owner, f"/api/orders/{sent['id']}/invoice").status_code == 200
    res = owner.put(f"/api/customers/{anna['id']}", json={"name": "Anna Smit", "city": "Meppel", "number": "A1"}, headers=H)
    assert res.status_code == 200 and res.get_json()["orders"] == 2
    after_open = owner.get(f"/api/orders/{open_order['id']}").get_json()
    after_sent = owner.get(f"/api/orders/{sent['id']}").get_json()
    assert (after_open["customer_name"], after_open["city"]) == ("Anna Smit", "Meppel")
    assert (after_sent["customer_name"], after_sent["city"]) == ("Anna de Vries", "Zwolle")         # an invoice that went out stays as it was
    owner.put(f"/api/orders/{sent['id']}", json={**after_sent, "lines": [line()]}, headers=H)       # saving the order copies the details again
    assert owner.get(f"/api/orders/{sent['id']}").get_json()["customer_name"] == "Anna Smit"


def test_changing_the_customer_of_an_order(owner):
    anna, bram = make_customer(owner).get_json(), make_customer(owner, name="Bram").get_json()
    order = new_order(owner, customer_id=anna["id"])
    moved = owner.put(f"/api/orders/{order['id']}", json={**order, "customer_id": bram["id"]}, headers=H).get_json()
    assert moved["customer_id"] == bram["id"] and moved["customer_name"] == "Bram"
    assert owner.put(f"/api/orders/{order['id']}", json={**order, "customer_id": None}, headers=H).status_code == 400


def test_a_customer_with_orders_cannot_be_deleted_one_without_can(owner):
    anna, bram = make_customer(owner).get_json(), make_customer(owner, name="Bram").get_json()
    order = new_order(owner, customer_id=anna["id"])
    refused = owner.delete(f"/api/customers/{anna['id']}", headers=H)
    assert refused.status_code == 409 and "1" in refused.get_json()["error"]
    assert owner.delete(f"/api/customers/{bram['id']}", headers=H).status_code == 200
    assert owner.get(f"/api/customers/{bram['id']}").status_code == 404 and owner.delete(f"/api/customers/{bram['id']}", headers=H).status_code == 404
    owner.delete(f"/api/orders/{order['id']}", headers=H)
    assert owner.delete(f"/api/customers/{anna['id']}", headers=H).status_code == 200


def test_the_customer_number_can_be_left_empty_when_editing_to_keep_it(owner):
    anna = make_customer(owner, number="A1").get_json()
    kept = owner.put(f"/api/customers/{anna['id']}", json={"name": "Anna", "number": ""}, headers=H).get_json()
    assert kept["number"] == "A1" and kept["name"] == "Anna"


def test_two_customers_made_at_the_same_moment_do_not_share_a_number(app):
    import threading
    from app import customers as module
    numbers, errors = [], []

    def make():
        try:
            with app.extensions["pool"].connection() as conn:
                numbers.append(module.insert(conn, {**{k: "" for k in module.FIELDS}, "name": "x"})["number"])
        except Exception as exc:                                         # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=make) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and sorted(numbers, key=int) == [str(n) for n in range(1, 7)]


# --- where a customer came from (migration 0025) ------------------------------------------------------------------------------------------

PROFILE = "https://www.marktplaats.nl/u/anna/123456/"
CHAT = "https://www.marktplaats.nl/messages/conversation/abc-123"


def test_a_customer_has_no_origin_until_it_is_given(owner):
    made = make_customer(owner).get_json()
    assert (made["origin"], made["marktplaats_profile_url"], made["marktplaats_chat_url"]) == ("", "", "")
    assert make_customer(owner, name="Bram", origin="").get_json()["origin"] == ""


def test_a_marktplaats_customer_keeps_a_link_to_the_profile_and_the_chat(owner):
    made = make_customer(owner, origin="marktplaats", marktplaats_profile_url=f" {PROFILE} ", marktplaats_chat_url=CHAT)
    assert made.status_code == 201
    one = owner.get(f"/api/customers/{made.get_json()['id']}").get_json()
    assert (one["origin"], one["marktplaats_profile_url"], one["marktplaats_chat_url"]) == ("marktplaats", PROFILE, CHAT)     # the spaces around an address are not kept
    listed = owner.get("/api/customers").get_json()[0]
    assert (listed["origin"], listed["marktplaats_profile_url"], listed["marktplaats_chat_url"]) == ("marktplaats", PROFILE, CHAT)
    only_profile = make_customer(owner, name="Bram", origin="marktplaats", marktplaats_profile_url=PROFILE).get_json()
    assert only_profile["marktplaats_profile_url"] == PROFILE and only_profile["marktplaats_chat_url"] == ""         # either may be left empty


@pytest.mark.parametrize("origin", ["webshop", "other", ""])
def test_the_marktplaats_links_are_only_kept_for_an_origin_of_marktplaats(owner, origin):
    made = make_customer(owner, origin=origin, marktplaats_profile_url=PROFILE, marktplaats_chat_url=CHAT).get_json()
    assert (made["origin"], made["marktplaats_profile_url"], made["marktplaats_chat_url"]) == (origin, "", "")
    mp = make_customer(owner, name="Bram", origin="marktplaats", marktplaats_profile_url=PROFILE, marktplaats_chat_url=CHAT).get_json()
    moved = owner.put(f"/api/customers/{mp['id']}", json={"name": "Bram", "origin": origin, "marktplaats_profile_url": PROFILE}, headers=H).get_json()
    assert (moved["origin"], moved["marktplaats_profile_url"], moved["marktplaats_chat_url"]) == (origin, "", "")
    assert owner.get(f"/api/customers/{mp['id']}").get_json()["marktplaats_chat_url"] == ""


@pytest.mark.parametrize("change", [
    {"origin": "vinted"}, {"origin": "Marktplaats"}, {"origin": ["marktplaats"]},
    {"origin": "marktplaats", "marktplaats_profile_url": "www.marktplaats.nl/u/anna"},
    {"origin": "marktplaats", "marktplaats_chat_url": "javascript:alert(1)"},
    {"origin": "marktplaats", "marktplaats_chat_url": "data:text/html,x"},
    {"origin": "marktplaats", "marktplaats_profile_url": "https://marktplaats.nl/a b"},
    {"origin": "marktplaats", "marktplaats_profile_url": "https://marktplaats.nl/" + "a" * 500}])
def test_an_origin_or_link_that_makes_no_sense_is_refused(owner, change):
    assert make_customer(owner, **change).status_code == 400
    assert owner.get("/api/customers").get_json() == []


def test_a_link_that_is_refused_says_which_one(owner):
    res = make_customer(owner, origin="marktplaats", marktplaats_chat_url="ftp://x")
    assert res.status_code == 400 and "Marktplaats-chat" in res.get_json()["error"]


def test_an_update_that_does_not_mention_the_origin_leaves_it_as_it_is(owner):
    """A screen that was open while the app was updated knows no origin and sends none: that must not empty what is there."""
    anna = make_customer(owner, origin="marktplaats", marktplaats_profile_url=PROFILE, marktplaats_chat_url=CHAT).get_json()
    old_screen = owner.put(f"/api/customers/{anna['id']}", json={"name": "Anna Smit", "number": anna["number"], "city": "Meppel"}, headers=H).get_json()
    assert old_screen["name"] == "Anna Smit" and old_screen["city"] == "Meppel"
    assert (old_screen["origin"], old_screen["marktplaats_profile_url"], old_screen["marktplaats_chat_url"]) == ("marktplaats", PROFILE, CHAT)
    cleared = owner.put(f"/api/customers/{anna['id']}", json={"name": "Anna Smit", "origin": "", "marktplaats_profile_url": "", "marktplaats_chat_url": ""}, headers=H).get_json()
    assert (cleared["origin"], cleared["marktplaats_profile_url"], cleared["marktplaats_chat_url"]) == ("", "", "")      # sent and empty is a choice
    assert owner.put(f"/api/customers/{anna['id']}", json={"name": "Anna", "origin": "vinted"}, headers=H).status_code == 400
    assert owner.get(f"/api/customers/{anna['id']}").get_json()["origin"] == ""


def test_a_copy_of_a_customer_has_the_same_origin_and_links(owner):
    anna = make_customer(owner, origin="marktplaats", marktplaats_profile_url=PROFILE, marktplaats_chat_url=CHAT).get_json()
    copy = owner.post(f"/api/customers/{anna['id']}/duplicate", headers=H).get_json()
    assert copy["id"] != anna["id"] and (copy["origin"], copy["marktplaats_profile_url"], copy["marktplaats_chat_url"]) == ("marktplaats", PROFILE, CHAT)


def test_the_origin_is_not_copied_to_an_order(owner):
    """It is the owner's own bookkeeping, like the note: an order copies what is on an invoice (`customers.snapshot`) and nothing else."""
    anna = make_customer(owner, origin="marktplaats", marktplaats_profile_url=PROFILE, marktplaats_chat_url=CHAT).get_json()
    order = new_order(owner, customer_id=anna["id"])
    assert not {"origin", "marktplaats_profile_url", "marktplaats_chat_url"} & set(order)
    assert not {"origin", "marktplaats_profile_url", "marktplaats_chat_url"} & set(owner.get("/api/orders").get_json()[0])


def test_the_screen_offers_the_origins_the_server_accepts():
    """No browser here, so the wiring is checked in the sources: the screen's list is the server's (plus 'not said'), each with its text in both languages."""
    import json
    import re
    from pathlib import Path
    from app import customers
    front = Path(__file__).resolve().parents[2] / "frontend"
    source = (front / "js/customers.js").read_text()
    offered = re.search(r"export const ORIGINS = \[(.*?)\];", source, re.S).group(1)
    pairs = re.findall(r"\['(\w*)', '(customers\.origin_\w+)'\]", offered)
    assert [value for value, _ in pairs] == ["", *customers.ORIGINS]
    for lang in ("nl", "en"):
        texts = json.loads((front / f"lang/{lang}.json").read_text())
        assert all(key in texts for _, key in pairs), lang
