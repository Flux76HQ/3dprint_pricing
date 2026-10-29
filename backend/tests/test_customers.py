
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
