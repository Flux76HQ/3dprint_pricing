"""Copying a calculation, an order or a customer takes along what belongs to it, and giving orders to another customer in one go.

A copy of a calculation brings its pictures (the photos, the saved views of the 3D model, the pictures that were made, the choices behind them) so nothing is
made or linked again; a copy of an order is a new order with the same lines and no invoice; a copy of a customer has its details and the next klantnummer. Orders
are given to another customer all together or not at all, and never when they have an invoice."""
import json
import uuid
from datetime import date
from io import BytesIO

import pytest

from tests import printfiles as pf
from tests.test_auth_api import H, post
from tests.test_ai_images import ai, photo, png, state, view         # noqa: F401  (fixture)
from tests.test_domain_api import make, sheet_payload
from tests.test_integrations import Net, deliveries, new_endpoint
from tests.test_orders import business, customer, line, new_order, pdf_text
from tests.test_users import _reset_limits, owner      # noqa: F401  (fixtures: the owner has a passkey, which a webhook is made with)

ZERO = "0" * 8 + "-0000-0000-0000-" + "0" * 12


def rows(app, sql, params=()):
    with app.extensions["pool"].connection() as conn:
        return conn.execute(sql, params).fetchall()


def picture_of(owner, image):
    return owner.get(f"/api/project-images/{image['id']}/file").data


def comparable(images):
    """What a picture is, apart from its id: the same list, in the same order, says the copy is the same set."""
    return [(i["kind"], i["origin"], i["model_ref"], i["variant"], i["purpose"], i["width_px"], i["height_px"], i["is_cover"], i["created_at"]) for i in images]


# --- a calculation ------------------------------------------------------------------------------------------------------

def a_model_with_everything(app, ai):
    """A calculation with a 3D model linked, an uploaded photo, a saved view of that model, pictures that were made (one is the cover), the choices behind
    them and a listing: everything that can be kept with one."""
    uploaded = ai.post("/api/print-files", data={"file": (BytesIO(pf.stl_binary()), "kubus.stl")}, headers=H, content_type="multipart/form-data")
    assert uploaded.status_code in (200, 201), uploaded.get_json()
    file_id = uploaded.get_json()["id"]
    project = make(ai, "/api/projects", {**sheet_payload(), "object_description": "plantenbak", "models": [{"file_id": file_id, "label": "Bak"}], "calc_files": [file_id]})
    assert photo(ai, project["id"]).status_code == 201
    assert view(ai, project["id"], png((420, 420), (30, 60, 200)), model=file_id).status_code == 201
    with app.extensions["pool"].connection() as conn:
        for number, (variant, purpose) in enumerate((("landscape", "marktplaats"), ("studio", "marktplaats"), ("square", "social")), 1):
            # at moments of their own, as pictures that were made are (a picture takes seconds): the order of pictures that were made at the very same millisecond is not defined
            conn.execute("INSERT INTO project_images (project_id, kind, variant, purpose, mime, content, width_px, height_px, is_cover, created_at) VALUES (%s, 'generated', %s, %s, "
                         "'image/jpeg', %s, 300, 200, %s, %s)", (project["id"], variant, purpose, png((300, 200), (number * 40, 90, 120)), number == 1, f"2099-01-01 10:00:0{number}.000"))
    assert ai.put(f"/api/projects/{project['id']}/images/settings", json={"purpose": "marktplaats", "colour": "#aa3311", "scene": "op een houten bureau", "product_name": "Plantenbak",
                                                                           "specs": ["30 cm"], "extra_text": "Op maat", "logo": False}, headers=H).status_code == 200
    assert ai.put(f"/api/projects/{project['id']}/listing", json={"title": "Plantenbak", "description": "Mooi.", "price": "14.95"}, headers=H).status_code == 200
    return project, file_id


def the_copy(ai, project, file_id, **extra):
    body = {**sheet_payload(), "name": "Plantenbak (kopie)", "models": [{"file_id": file_id, "label": "Bak"}], "calc_files": [file_id], "duplicate_of": project["id"], **extra}
    res = ai.post("/api/projects", json=body, headers=H)
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def test_a_copy_of_a_calculation_takes_its_pictures_the_views_of_the_model_and_the_choices_behind_them(app, ai):
    project, file_id = a_model_with_everything(app, ai)
    before = state(ai, project)
    pick = next(i for i in before["images"] if i["kind"] == "source" and i["origin"] == "model")
    assert ai.put(f"/api/project-images/{pick['id']}/selected", json={"selected": True}, headers=H).status_code == 200
    before = state(ai, project)
    copy = the_copy(ai, project, file_id)
    after = state(ai, copy)
    assert len(after["images"]) == len(before["images"]) == 5
    assert comparable(after["images"]) == comparable(before["images"])                            # photo, view, three made: same kinds, models, purposes, cover, order
    assert {i["id"] for i in after["images"]}.isdisjoint({i["id"] for i in before["images"]})    # copies, not the same rows
    assert [picture_of(ai, i) for i in after["images"]] == [picture_of(ai, i) for i in before["images"]]       # the very same bytes
    assert after["text"] == before["text"] and after["text"]["scene"] == "op een houten bureau" and after["text"]["purpose"] == "marktplaats"
    assert len(after["sent"]) == len(before["sent"]) == 2                                          # the photo (the first one) and the view that was ticked
    assert sum(i["is_cover"] for i in after["images"]) == 1


def test_the_3d_models_of_a_copy_are_the_same_files_and_the_saved_views_still_point_at_them(app, ai):
    project, file_id = a_model_with_everything(app, ai)
    copy = the_copy(ai, project, file_id)
    shown = ai.get(f"/api/projects/{copy['id']}").get_json()
    assert shown["models"] == [{"file_id": file_id, "label": "Bak"}] and shown["calc_files"] == [file_id] and shown["file_id"] == file_id
    assert [i["model_ref"] for i in state(ai, copy)["images"] if i["origin"] == "model"] == [file_id]
    assert ai.get(f"/api/print-files/{file_id}/mesh").status_code == 200                           # the viewer reads it for the copy as for the original
    # The file stays while either names it: removing the original does not take the copy's model or its pictures away.
    assert ai.delete(f"/api/projects/{project['id']}", headers=H).status_code == 200
    assert ai.get(f"/api/print-files/{file_id}/mesh").status_code == 200
    assert len(state(ai, copy)["images"]) == 5


def test_a_copy_does_not_take_what_was_spent_on_the_original_nor_what_it_is_for_sale_as(app, ai):
    project, file_id = a_model_with_everything(app, ai)
    spent = rows(app, "SELECT count(*) AS n FROM ai_image_usage")[0]["n"]
    copy = the_copy(ai, project, file_id)
    assert rows(app, "SELECT count(*) AS n FROM ai_image_usage")[0]["n"] == spent
    assert rows(app, "SELECT count(*) AS n FROM ai_image_jobs WHERE project_id = %s", (copy["id"],))[0]["n"] == 0
    listed = {p["id"]: p for p in ai.get("/api/projects").get_json()}
    assert listed[project["id"]]["for_sale"] is True and listed[copy["id"]]["for_sale"] is False


def test_a_copy_without_duplicate_of_has_no_pictures_and_a_wrong_original_is_refused_without_making_anything(app, ai):
    project, file_id = a_model_with_everything(app, ai)
    plain = make(ai, "/api/projects", {**sheet_payload(), "name": "Los"})
    assert state(ai, plain)["images"] == []
    count = len(ai.get("/api/projects").get_json())
    for wrong in (str(uuid.uuid4()), "geen-id", 12):
        res = ai.post("/api/projects", json={**sheet_payload(), "name": "X", "duplicate_of": wrong}, headers=H)
        assert res.status_code == 404 and "niet gevonden" in res.get_json()["error"], wrong
    assert len(ai.get("/api/projects").get_json()) == count                                       # nothing was made: no copy without its pictures
    assert ai.post("/api/projects", json={**sheet_payload(), "name": "Y", "duplicate_of": ""}, headers=H).status_code == 201     # an empty one is no original


def test_the_pictures_of_a_copy_are_its_own_and_survive_removing_the_original(app, ai):
    project, file_id = a_model_with_everything(app, ai)
    copy = the_copy(ai, project, file_id)
    gone = next(i for i in state(ai, copy)["images"] if i["kind"] == "generated")
    assert ai.delete(f"/api/project-images/{gone['id']}", headers=H).status_code == 200            # removing one from the copy leaves the original's
    assert len(state(ai, project)["images"]) == 5 and len(state(ai, copy)["images"]) == 4
    assert ai.delete(f"/api/projects/{project['id']}", headers=H).status_code == 200
    assert len(state(ai, copy)["images"]) == 4


# --- an order -----------------------------------------------------------------------------------------------------------

def the_order(owner, calculation=None):
    lines = [line("Vaas", 2, "12.10", "21", project_id=calculation, cost_price="5.00", margin_pct="100"),
             line("Houder", 1, "3.50", "9"), line("Handleiding", 1, "0.00", "0", optional=True)]
    return new_order(owner, lines=lines, status="verstuurd", notes="Bellen voor aankomst", price_rounding="0.05")


def test_a_copy_of_an_order_has_the_same_lines_for_the_same_customer_and_is_a_new_order(owner):
    calculation = make(owner, "/api/projects", {**sheet_payload(), "name": "Vaas"})["id"]
    original = the_order(owner, calculation)
    res = post(owner, f"/api/orders/{original['id']}/duplicate")
    assert res.status_code == 201, res.get_json()
    copy = res.get_json()
    assert copy["id"] != original["id"] and copy["number"] == original["number"] + 1
    assert copy["customer_id"] == original["customer_id"] and copy["subject"] == original["subject"] and copy["notes"] == "Bellen voor aankomst"
    assert copy["price_rounding"] == "0.05"
    keep = ("project_id", "project_number", "description", "quantity", "unit_price", "vat_pct", "cost_price", "margin_pct", "margin_pct_effective", "optional", "line_total", "position")
    assert [{k: l[k] for k in keep} for l in copy["lines"]] == [{k: l[k] for k in keep} for l in original["lines"]] and len(copy["lines"]) == 3
    assert {l["id"] for l in copy["lines"]}.isdisjoint({l["id"] for l in original["lines"]})
    assert copy["totals"] == original["totals"]
    assert [l["optional"] for l in copy["lines"]] == [False, False, True] and copy["lines"][0]["cost_price"] is not None
    assert owner.get(f"/api/orders/{original['id']}").get_json()["lines"] == original["lines"]    # the original was not touched


def test_what_belongs_to_the_moment_is_not_copied_with_an_order_and_there_is_never_an_invoice(owner):
    business(owner)
    original = the_order(owner)
    assert post(owner, f"/api/orders/{original['id']}/invoice").status_code == 200
    original = owner.get(f"/api/orders/{original['id']}").get_json()
    assert original["invoice_number"] and original["has_invoice_pdf"] and original["status"] == "verstuurd" and original["delivery_date"] == "2026-10-15"
    copy = post(owner, f"/api/orders/{original['id']}/duplicate").get_json()
    assert copy["status"] == "nieuw" and copy["order_date"] == date.today().isoformat() and copy["delivery_date"] is None
    assert copy["invoice_number"] is None and copy["invoice_date"] is None
    assert owner.get(f"/api/orders/{copy['id']}/invoice").status_code == 404                        # no PDF of the original's
    assert owner.get(f"/api/orders/{copy['id']}").get_json()["has_invoice_pdf"] is False
    again = post(owner, f"/api/orders/{copy['id']}/invoice")
    assert again.status_code == 200 and f"{date.today().year}-0002" in pdf_text(again.data)         # its own number, the next one
    assert owner.get(f"/api/orders/{original['id']}").get_json()["invoice_number"] == original["invoice_number"]


def test_a_copy_of_an_order_takes_the_details_the_customer_has_now_not_the_ones_an_invoice_kept(owner):
    business(owner)
    original = the_order(owner)
    post(owner, f"/api/orders/{original['id']}/invoice")
    owner.put(f"/api/customers/{original['customer_id']}", json={**customer(owner), "name": "Piet Pietersen", "city": "Zeist"}, headers=H)
    kept = owner.get(f"/api/orders/{original['id']}").get_json()
    assert kept["customer_name"] == "Jan Jansen" and kept["city"] == "Utrecht"                      # an invoice that went out is not rewritten
    copy = post(owner, f"/api/orders/{original['id']}/duplicate").get_json()
    assert copy["customer_name"] == "Piet Pietersen" and copy["city"] == "Zeist" and copy["customer_number"] == "K9999"


def test_copying_an_order_reports_a_new_order_and_nothing_else(owner, app, monkeypatch):
    Net(monkeypatch)
    hook = new_endpoint(owner, events=("order.created", "order.updated"), name="Bestellingen")["endpoint"]["id"]
    original = new_order(owner)
    copy = post(owner, f"/api/orders/{original['id']}/duplicate").get_json()
    sent = deliveries(app, hook)
    assert [d["event"] for d in sent] == ["order.created", "order.created"]
    assert json.loads(sent[-1]["body"])["data"]["order_id"] == copy["id"] and "lines" not in json.loads(sent[-1]["body"])["data"]


def test_an_order_that_is_not_there_cannot_be_copied(owner):
    assert post(owner, f"/api/orders/{ZERO}/duplicate").status_code == 404


# --- a customer ---------------------------------------------------------------------------------------------------------

def test_a_copy_of_a_customer_has_all_its_details_and_the_next_klantnummer(owner):
    original = customer(owner, name="Anna de Vries", address="Dorpsstraat 3", postal_code="1111 AA", city="Zeist", country="Nederland", email="anna@example.nl",
                        phone="06 1234", notes="Betaalt altijd na een week")
    other = customer(owner, name="Bram")
    new_order(owner, customer_id=original["id"])
    res = post(owner, f"/api/customers/{original['id']}/duplicate")
    assert res.status_code == 201, res.get_json()
    copy = res.get_json()
    assert copy["id"] != original["id"] and copy["name"] == "Anna de Vries (kopie)"
    assert copy["number"] == str(int(other["number"]) + 1) and copy["number"] != original["number"]
    for key in ("address", "postal_code", "city", "country", "email", "phone", "notes"):
        assert copy[key] == original[key], key
    assert copy["orders"] == 0 and owner.get(f"/api/customers/{original['id']}").get_json()["orders"] == 1       # the history stays where it was
    assert owner.get(f"/api/customers/{original['id']}").get_json()["name"] == "Anna de Vries"
    twice = post(owner, f"/api/customers/{original['id']}/duplicate").get_json()
    assert twice["number"] == str(int(copy["number"]) + 1)                                         # a klantnummer is never given twice


def test_the_name_of_a_copy_says_copy_in_english_and_never_outgrows_the_limit(owner):
    long = customer(owner, name="N" * 120)
    copy = post(owner, f"/api/customers/{long['id']}/duplicate").get_json()
    assert len(copy["name"]) <= 120 and copy["name"].endswith(" (kopie)")
    english = owner.post(f"/api/customers/{long['id']}/duplicate", headers={**H, "X-Lang": "en"}).get_json()
    assert english["name"].endswith(" (copy)") and len(english["name"]) <= 120


def test_a_customer_that_is_not_there_cannot_be_copied(owner):
    assert post(owner, f"/api/customers/{ZERO}/duplicate").status_code == 404


# --- giving orders to another customer ----------------------------------------------------------------------------------

def assign(owner, orders, to, **extra):
    return post(owner, "/api/orders/assign-customer", {"order_ids": [o["id"] if isinstance(o, dict) else o for o in orders], "customer_id": to["id"], **extra})


def customer_of(owner, order):
    return owner.get(f"/api/orders/{order['id']}").get_json()


def test_orders_are_given_to_another_customer_in_one_go_with_that_customers_details(owner):
    anna = customer(owner, name="Anna", city="Zeist", email="anna@example.nl")
    bram = customer(owner, name="Bram", city="Breda", email="bram@example.nl")
    orders = [new_order(owner, customer_id=anna["id"]) for _ in range(3)]
    stays = new_order(owner, customer_id=anna["id"])
    res = assign(owner, orders, bram)
    assert res.status_code == 200 and res.get_json() == {"ok": True, "updated": 3}
    for order in orders:
        now = customer_of(owner, order)
        assert now["customer_id"] == bram["id"] and now["customer_name"] == "Bram" and now["city"] == "Breda" and now["email"] == "bram@example.nl"
        assert now["customer_number"] == bram["number"] and now["lines"] == order["lines"] and now["status"] == order["status"] and now["number"] == order["number"]
    assert customer_of(owner, stays)["customer_id"] == anna["id"]
    assert owner.get(f"/api/customers/{bram['id']}").get_json()["orders"] == 3 and owner.get(f"/api/customers/{anna['id']}").get_json()["orders"] == 1


def test_an_order_that_already_has_the_customer_is_left_alone_and_a_list_with_doubles_counts_once(owner):
    anna, bram = customer(owner, name="Anna"), customer(owner, name="Bram")
    mine, moving = new_order(owner, customer_id=bram["id"]), new_order(owner, customer_id=anna["id"])
    res = assign(owner, [mine, moving, moving, mine], bram)
    assert res.get_json()["updated"] == 1
    assert assign(owner, [mine, moving], bram).get_json()["updated"] == 0 and assign(owner, [mine, moving], bram).status_code == 200


def test_nothing_changes_when_one_of_the_orders_has_an_invoice(owner):
    business(owner)
    anna, bram = customer(owner, name="Anna"), customer(owner, name="Bram")
    free, invoiced = new_order(owner, customer_id=anna["id"]), new_order(owner, customer_id=anna["id"])
    post(owner, f"/api/orders/{invoiced['id']}/invoice")
    res = assign(owner, [free, invoiced], bram)
    assert res.status_code == 409 and "factuur" in res.get_json()["error"]
    assert customer_of(owner, free)["customer_id"] == anna["id"] and customer_of(owner, invoiced)["customer_id"] == anna["id"]         # not even the free one
    assert customer_of(owner, invoiced)["customer_name"] == "Anna"
    assert assign(owner, [invoiced], anna).get_json()["updated"] == 0                                   # but it may stay where it is


@pytest.mark.parametrize("body", [
    {}, {"order_ids": []}, {"order_ids": "x"}, {"order_ids": ["niet-een-id"]}, {"order_ids": [None]}, {"order_ids": [ZERO] * 501}])
def test_a_request_to_give_orders_away_needs_a_sensible_list(owner, body):
    bram = customer(owner, name="Bram")
    res = post(owner, "/api/orders/assign-customer", {"customer_id": bram["id"], **body})
    assert res.status_code == 400 and "bestellingen" in res.get_json()["error"], res.get_json()


def test_orders_need_an_existing_customer_and_existing_orders_or_nothing_changes(owner):
    anna, bram = customer(owner, name="Anna"), customer(owner, name="Bram")
    order = new_order(owner, customer_id=anna["id"])
    for wrong in (None, "geen-id", ZERO):
        assert post(owner, "/api/orders/assign-customer", {"order_ids": [order["id"]], "customer_id": wrong}).status_code == 400, wrong
    res = assign(owner, [order, ZERO], bram)
    assert res.status_code == 404
    assert customer_of(owner, order)["customer_id"] == anna["id"]                                       # the one that exists was not moved either


def test_giving_orders_away_reports_each_changed_order_and_only_those(owner, app, monkeypatch):
    Net(monkeypatch)
    hook = new_endpoint(owner, events=("order.updated",), name="Bestellingen")["endpoint"]["id"]
    anna, bram = customer(owner, name="Anna"), customer(owner, name="Bram")
    orders = [new_order(owner, customer_id=anna["id"]) for _ in range(2)]
    mine = new_order(owner, customer_id=bram["id"])
    assert deliveries(app, hook) == []                                                                  # making them said nothing about updates
    assign(owner, [*orders, mine], bram)
    sent = [json.loads(d["body"])["data"]["order_id"] for d in deliveries(app, hook)]
    assert sorted(sent) == sorted(o["id"] for o in orders)
    assign(owner, orders, bram)
    assert len(deliveries(app, hook)) == 2                                                              # nothing moved, nothing said


def test_copying_and_giving_away_need_a_session(client):
    for path in (f"/api/orders/{ZERO}/duplicate", f"/api/customers/{ZERO}/duplicate", "/api/orders/assign-customer"):
        assert client.post(path, json={"order_ids": [ZERO], "customer_id": ZERO}, headers=H).status_code == 401, path


# --- the screens ----------------------------------------------------------------------------------------------------------

def test_the_screens_are_wired_to_the_copies_the_filter_and_the_choosing_of_orders():
    """There is no browser in the tests, so the wiring is checked in the sources (the behaviour itself was checked in Chromium, on a desktop and on a phone): the copy of a
    calculation asks for the pictures of its original, an order and a customer have a *Dupliceren* that asks the server and refuses unsaved changes, the orders can be
    filtered on customer (also by address), and they can be chosen, but never one with an invoice, and given to another customer through the one route that does it."""
    from pathlib import Path
    front = Path(__file__).resolve().parents[2] / "frontend" / "js"
    projects, orders, customers, listview, main = ((front / f).read_text() for f in ("projects.js", "orders.js", "customers.js", "listview.js", "main.js"))
    assert "body.duplicate_of = state.id" in projects and "asCopy && state.id" in projects
    assert "`/api/orders/${state.id}/duplicate`" in orders and "if (dirty) { toast(t('orders.duplicate_save_first')" in orders
    assert "`/api/customers/${customer.id}/duplicate`" in customers and "if (dirty) { toast(t('customers.duplicate_save_first')" in customers
    assert "filters: [{ key: 'customer'" in orders and "value: (o) => o.customer_id" in orders
    assert "select: { id: (o) => o.id, can: (o) => !o.invoice_number" in orders and "'/api/orders/assign-customer'" in orders and "order_ids: rows.map((o) => o.id)" in orders
    assert "orderListView({ customer: extra })" in main and "`#/bestellingen/klant/${c.id}`" in customers and "view.setFilter('customer', customer)" in orders
    assert "const choosable = shown.filter(canChoose)" in listview and "chosen.delete(id)" in listview and "!canChoose(row)" in listview     # what is not shown or not allowed is not chosen
    assert "customerPicker(" in orders and orders.count("customerPicker(") == 2                      # the order's own picker and the assigning one share the list
