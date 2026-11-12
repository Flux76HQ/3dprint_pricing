"""Other applications: API keys, the read-only API under /api/v1, and webhooks.

A key is not a session and a session is not a key; a key reads what is on an invoice and never what it cost; a webhook is written with the
change it reports, signed, sent at least once and tried again; and none of it is in a backup. No test reaches a network: `Net` stands in."""
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from standardwebhooks.webhooks import Webhook, WebhookVerificationError

from app import api_keys, passwords, webhooks
from app.http import RateLimiter
from tests.conftest import SECRET
from tests.test_auth_api import H, post
from tests.test_backup import backup
from tests.test_orders import business, line, new_order
from tests.test_users import _reset_limits, join_with_passkey, owner, proof, sql      # noqa: F401  (fixtures)

# "Now" for the worker in these tests: a whole minute a little after the real clock. What the app queues gets the real time, and
# the worker only takes what is due, so a fixed date here made every one of these tests fail from the moment that date had passed.
T0 = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(hours=1)
URL = "https://finance.example.test/hooks/printpricing"


@pytest.fixture(autouse=True)
def _fresh_limiters():
    api_keys.per_key.hits.clear()
    api_keys.wrong_key.hits.clear()


def new_key(admin, name="Finance"):
    res = post(admin, "/api/integrations/keys", {"name": name, **proof(admin, "api-key-create", None)})
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


class Net:
    """What stands in for the network: every request is kept, and answered with `status` (or the exception put in `fail`)."""

    def __init__(self, monkeypatch, status=200, resolves_to="203.0.113.10"):
        self.calls, self.status, self.fail, self.resolves_to = [], status, None, resolves_to
        monkeypatch.setattr(webhooks.requests, "request", self.request)
        monkeypatch.setattr(webhooks, "_resolve", lambda host, port: [self.resolves_to])

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.fail:
            raise self.fail
        response = requests.Response()
        response.status_code = self.status
        response.raw = io.BytesIO(b"INTERNAL-ANSWER-OF-THE-RECEIVER")          # there to read, and never read
        return response


def new_endpoint(admin, events=("invoice.created",), url=URL, name="Finance"):
    res = post(admin, "/api/integrations/webhooks", {"name": name, "url": url, "events": list(events), **proof(admin, "webhook-create", None)})
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def run(app, now=T0):
    return webhooks.run_once(app.extensions["pool"], app.config["APP_CONFIG"], now)


def deliveries(app, endpoint_id=None):
    rows = sql(app, "SELECT * FROM webhook_deliveries ORDER BY created_at, rowid")      # as they were written
    return [r for r in rows if endpoint_id is None or str(r["endpoint_id"]) == endpoint_id]


def invoiced_order(admin, **extra):
    business(admin)
    order = new_order(admin, **extra)
    assert post(admin, f"/api/orders/{order['id']}/invoice").status_code == 200
    return admin.get(f"/api/orders/{order['id']}").get_json()


# --- API keys ----------------------------------------------------------------------------------------------------------

def test_a_key_is_shown_once_and_only_its_hash_is_kept(owner, app):
    made = new_key(owner)
    key = made["key"]
    assert key.startswith("ppk_") and len(key) > 40 and made["item"]["shown"] == key[:10]
    listed = owner.get("/api/integrations/keys")
    assert key not in listed.get_data(as_text=True) and [k["name"] for k in listed.get_json()["keys"]] == ["Finance"]
    stored = json.dumps([dict(r) for r in sql(app, "SELECT * FROM api_keys")], default=str)
    assert key not in stored and key[10:] not in stored


def test_making_and_revoking_a_key_need_a_fresh_confirmation_for_exactly_that(owner):
    assert post(owner, "/api/integrations/keys", {"name": "Finance"}).status_code == 400                                    # no confirmation at all
    assert post(owner, "/api/integrations/keys", {"name": "Finance", **proof(owner, "webhook-create", None)}).status_code == 403   # one for something else
    assert owner.get("/api/integrations/keys").get_json()["keys"] == []
    one, two = new_key(owner, "Een"), new_key(owner, "Twee")
    wrong = owner.delete(f"/api/integrations/keys/{one['item']['id']}", json=proof(owner, "api-key-revoke", two["item"]["id"]), headers=H)
    assert wrong.status_code == 403 and len(owner.get("/api/integrations/keys").get_json()["keys"]) == 2
    assert owner.delete(f"/api/integrations/keys/{one['item']['id']}", json=proof(owner, "api-key-revoke", one["item"]["id"]), headers=H).status_code == 200
    assert owner.get("/api/v1", headers=bearer(one["key"])).status_code == 401                                             # at once
    assert owner.get("/api/v1", headers=bearer(two["key"])).status_code == 200


def test_a_key_is_not_a_session_and_a_session_is_not_a_key(owner, app):
    key = new_key(owner)["key"]
    stranger = app.test_client()                                     # no cookie: only the key
    assert stranger.get("/api/v1", headers=bearer(key)).get_json()["key"] == "Finance"
    for path in ("/api/orders", "/api/customers", "/api/projects", "/api/preferences", "/api/backup", "/api/integrations/keys", "/api/auth/status"):
        res = stranger.get(path, headers=bearer(key))
        assert res.status_code == 401 or (path == "/api/auth/status" and res.get_json()["authenticated"] is False), path
    assert stranger.post("/api/orders", json={}, headers=bearer(key)).status_code == 401
    assert owner.get("/api/v1").status_code == 401                   # the owner's session, without a key
    assert owner.get("/api/v1/orders").status_code == 401
    assert stranger.get("/api/v1").status_code == 401
    for wrong in ("Bearer ppk_" + "a" * 43, "Bearer something-else", "Basic abc", "ppk_x"):
        assert stranger.get("/api/v1", headers={"Authorization": wrong}).status_code == 401, wrong


def test_the_api_only_reads(owner, app):
    key = new_key(owner)["key"]
    order = new_order(owner)
    stranger = app.test_client()
    for method in ("post", "put", "patch", "delete"):
        for path in ("/api/v1/orders", f"/api/v1/orders/{order['id']}", f"/api/v1/orders/{order['id']}/invoice", "/api/v1/customers"):
            assert getattr(stranger, method)(path, json={}, headers=bearer(key)).status_code == 405, (method, path)
    assert owner.get(f"/api/orders/{order['id']}").status_code == 200


def test_keys_that_do_not_exist_are_slowed_down_and_a_key_has_a_limit(owner, app, monkeypatch):
    monkeypatch.setattr(api_keys, "wrong_key", RateLimiter(2, 900))
    stranger = app.test_client()
    guess = bearer("ppk_" + "b" * 43)
    assert [stranger.get("/api/v1", headers=guess).status_code for _ in range(3)] == [401, 401, 429]
    key = new_key(owner)["key"]
    assert stranger.get("/api/v1", headers=bearer(key)).status_code == 200            # a real key is not held up by someone else's guesses
    monkeypatch.setattr(api_keys, "per_key", RateLimiter(2, 60))
    answers = [stranger.get("/api/v1", headers=bearer(key)) for _ in range(3)]
    assert [a.status_code for a in answers] == [200, 200, 429]
    assert answers[2].headers["Retry-After"] == "60" and answers[2].get_json()["code"] == "err.rate_limited"


def test_there_is_a_most_and_last_use_is_written_down(owner, app, monkeypatch):
    monkeypatch.setattr(api_keys, "MAX_KEYS", 1)
    key = new_key(owner)
    assert owner.get("/api/integrations/keys").get_json()["keys"][0]["last_used_at"] is None
    assert post(owner, "/api/integrations/keys", {"name": "Nog een", **proof(owner, "api-key-create", None)}).status_code == 409
    assert app.test_client().get("/api/v1", headers=bearer(key["key"])).status_code == 200
    assert owner.get("/api/integrations/keys").get_json()["keys"][0]["last_used_at"] is not None


def test_a_key_stays_when_the_person_who_made_it_leaves(owner, app):
    other = join_with_passkey(app, owner, role="admin")
    key = new_key(other)["key"]
    assert owner.delete(f"/api/users/{other.user_id}", headers=H).status_code == 200
    assert app.test_client().get("/api/v1", headers=bearer(key)).status_code == 200


# --- the API: what is on an invoice, never what it cost ----------------------------------------------------------------

def test_an_order_is_what_is_on_the_invoice_and_never_what_it_cost(owner, app):
    key = new_key(owner)["key"]
    order = invoiced_order(owner, lines=[line("Vaas", 2, "12.10", "21", cost_price="3.50", margin_pct="150"), line("Kabel", 1, "4.00", "9", optional=True)],
                           notes="Alleen voor onszelf: haast")
    reader = app.test_client()
    got = reader.get(f"/api/v1/orders/{order['id']}", headers=bearer(key))
    assert got.status_code == 200
    seen, text = got.get_json(), got.get_data(as_text=True)
    for hidden in ("cost_price", "margin", "notes", "Alleen voor onszelf", "3.50", "project_id", "price_rounding"):
        assert hidden not in text, hidden
    assert seen["number"] == order["number"] and seen["customer"]["name"] == "Jan Jansen" and seen["customer"]["number"] == "K9999"
    assert seen["invoice"] == {"number": order["invoice_number"], "date": order["invoice_date"], "has_pdf": True}
    assert [(row["description"], row["quantity"], row["unit_price"], row["vat_pct"], row["optional"]) for row in seen["lines"]] == \
        [(l["description"], l["quantity"], l["unit_price"], l["vat_pct"], l["optional"]) for l in order["lines"]]
    assert seen["totals"]["incl"] == order["totals"]["total"] and seen["totals"]["excl"] == order["totals"]["total_excl"]
    assert [rate["pct"] for rate in seen["totals"]["by_vat_rate"]] == ["9", "21"]
    pdf = reader.get(f"/api/v1/orders/{order['id']}/invoice", headers=bearer(key))
    assert pdf.mimetype == "application/pdf" and pdf.data.startswith(b"%PDF")
    listed = reader.get("/api/v1/orders", headers=bearer(key)).get_data(as_text=True)
    assert "cost_price" not in listed and "margin" not in listed and "Alleen voor onszelf" not in listed


def test_an_order_without_an_invoice_says_so(owner, app):
    key = new_key(owner)["key"]
    order = new_order(owner)
    reader = app.test_client()
    assert reader.get(f"/api/v1/orders/{order['id']}", headers=bearer(key)).get_json()["invoice"] is None
    missing = reader.get(f"/api/v1/orders/{order['id']}/invoice", headers=bearer(key))
    assert missing.status_code == 404 and missing.get_json()["code"] == "invoice.err_no_pdf"
    unknown = reader.get(f"/api/v1/orders/{uuid.uuid4()}", headers=bearer(key))
    assert unknown.status_code == 404 and unknown.get_json()["code"] == "err.order_not_found" and unknown.get_json()["error"]


def test_lists_are_paged_oldest_change_first_and_can_start_from_a_moment(owner, app):
    key = new_key(owner)["key"]
    business(owner)
    made = [new_order(owner, subject=f"Bestelling {n}") for n in range(3)]
    for n, order in enumerate(made):                                 # three known moments of change
        sql(app, "UPDATE orders SET updated_at = %s WHERE id = %s", (T0 + timedelta(minutes=n), order["id"]))
    reader = app.test_client()
    first = reader.get("/api/v1/orders?limit=2", headers=bearer(key)).get_json()
    assert [o["id"] for o in first["data"]] == [made[0]["id"], made[1]["id"]] and first["next_cursor"]
    second = reader.get(f"/api/v1/orders?limit=2&cursor={first['next_cursor']}", headers=bearer(key)).get_json()
    assert [o["id"] for o in second["data"]] == [made[2]["id"]] and second["next_cursor"] is None
    since = reader.get(f"/api/v1/orders?updated_since={(T0 + timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}", headers=bearer(key)).get_json()
    assert [o["id"] for o in since["data"]] == [made[1]["id"], made[2]["id"]]
    assert post(owner, f"/api/orders/{made[1]['id']}/invoice").status_code == 200
    assert [o["id"] for o in reader.get("/api/v1/orders?invoiced=true", headers=bearer(key)).get_json()["data"]] == [made[1]["id"]]
    assert len(reader.get("/api/v1/orders?invoiced=false", headers=bearer(key)).get_json()["data"]) == 2
    assert len(reader.get("/api/v1/orders?status=nieuw", headers=bearer(key)).get_json()["data"]) == 3
    for bad, code in (("limit=0", "v1.err_limit"), ("limit=500", "v1.err_limit"), ("limit=x", "v1.err_limit"), ("cursor=nope", "v1.err_cursor"),
                      ("updated_since=gisteren", "v1.err_moment"), ("invoiced=ja", "v1.err_invoiced"), ("status=weg", "err.order_status")):
        res = reader.get(f"/api/v1/orders?{bad}", headers=bearer(key))
        assert res.status_code == 400 and res.get_json()["code"] == code, bad


def test_customers_are_listed_without_the_notes_of_the_business(owner, app):
    key = new_key(owner)["key"]
    order = new_order(owner, name="Studio Bloem", notes="")
    owner.put(f"/api/customers/{order['customer_id']}", json={"name": "Studio Bloem", "number": "K77", "notes": "Betaalt altijd laat", "city": "Arnhem"}, headers=H)
    reader = app.test_client()
    listed = reader.get("/api/v1/customers", headers=bearer(key))
    assert "Betaalt altijd laat" not in listed.get_data(as_text=True) and "notes" not in listed.get_data(as_text=True)
    assert [(c["name"], c["number"], c["city"]) for c in listed.get_json()["data"]] == [("Studio Bloem", "K77", "Arnhem")]
    one = reader.get(f"/api/v1/customers/{order['customer_id']}", headers=bearer(key))
    assert one.get_json()["name"] == "Studio Bloem" and "notes" not in one.get_json()
    assert reader.get(f"/api/v1/customers/{uuid.uuid4()}", headers=bearer(key)).status_code == 404


# --- webhooks: endpoints and their key ---------------------------------------------------------------------------------------

def test_the_signing_key_is_shown_once_and_kept_sealed(owner, app):
    made = new_endpoint(owner)
    key = made["signing_key"]
    assert key.startswith("whsec_") and made["endpoint"]["readable"] is True and made["endpoint"]["url"] == URL
    assert key not in owner.get("/api/integrations/webhooks").get_data(as_text=True)
    stored = sql(app, "SELECT signing_key_enc FROM webhook_endpoints")[0]["signing_key_enc"]
    assert key not in stored and stored.startswith("gAAAA")


def test_an_endpoint_needs_a_confirmation_an_address_and_something_to_tell(owner):
    good = {"name": "Finance", "url": URL, "events": ["invoice.created"]}
    assert post(owner, "/api/integrations/webhooks", good).status_code == 400                                              # no confirmation
    assert post(owner, "/api/integrations/webhooks", {**good, **proof(owner, "api-key-create", None)}).status_code == 403    # one for something else
    for bad in ({"url": "ftp://finance.example.test/x"}, {"url": "finance.example.test/hooks"}, {"url": "https://user:pw@finance.example.test/"},
                {"url": "https://finance.example.test/#deel"}, {"url": "https://"}, {"url": "http://169.254.169.254/latest/meta-data"},
                {"url": "http://[fe80::1]/"}, {"url": "http://0.0.0.0/"}, {"url": "https://finance.example.test/" + "x" * 500},
                {"events": []}, {"events": ["order.exploded"]}, {"events": "invoice.created"}, {"name": ""}):
        res = post(owner, "/api/integrations/webhooks", {**good, **bad, **proof(owner, "webhook-create", None)})
        assert res.status_code == 400, bad
    assert owner.get("/api/integrations/webhooks").get_json()["endpoints"] == []
    # The owner's other applications are often on the own network: a private address, a name without dots and plain http are all fine.
    for n, url in enumerate(("http://192.168.1.20:8080/hooks", "http://finance:8000/hooks?from=printpricing", "http://localhost:9000/hooks")):
        assert new_endpoint(owner, url=url, name=f"Intern {n}")["endpoint"]["url"] == url


def test_taking_an_endpoint_away_or_giving_it_a_new_key_is_confirmed_for_that_endpoint(owner, app, monkeypatch):
    net = Net(monkeypatch)
    one, two = new_endpoint(owner, name="Een"), new_endpoint(owner, name="Twee", url=URL + "/2")
    first, second = one["endpoint"]["id"], two["endpoint"]["id"]
    assert owner.delete(f"/api/integrations/webhooks/{first}", json=proof(owner, "webhook-delete", second), headers=H).status_code == 403
    assert post(owner, f"/api/integrations/webhooks/{first}/rotate", proof(owner, "webhook-delete", first)).status_code == 403
    rotated = post(owner, f"/api/integrations/webhooks/{first}/rotate", proof(owner, "webhook-rotate", first))
    assert rotated.status_code == 200 and rotated.get_json()["signing_key"] not in (one["signing_key"], two["signing_key"])
    invoiced_order(owner)
    run(app)
    sent = next(c for c in net.calls if c["url"] == URL)
    assert signed_by(rotated.get_json()["signing_key"], sent) and not signed_by(one["signing_key"], sent)      # the old key stopped at once
    assert owner.delete(f"/api/integrations/webhooks/{first}", json=proof(owner, "webhook-delete", first), headers=H).status_code == 200
    assert [e["name"] for e in owner.get("/api/integrations/webhooks").get_json()["endpoints"]] == ["Twee"]
    assert deliveries(app, first) == []                               # its messages went with it


# --- webhooks: written with the change, signed, sent ---------------------------------------------------------------------------

def signed_by(key, call, at=T0):
    """Whether this request carries a Standard Webhooks signature made with `key` (checked by hand: the package's own check reads the clock)."""
    headers = call["headers"]
    expected = Webhook(key).sign(headers["webhook-id"], at, call["data"].decode("utf-8"))
    return headers["webhook-signature"] == expected and headers["webhook-timestamp"] == str(int(at.timestamp()))


def test_an_invoice_is_reported_signed_and_without_customer_details(owner, app, monkeypatch):
    net = Net(monkeypatch)
    made = new_endpoint(owner, events=("invoice.created", "invoice.updated"))
    order = invoiced_order(owner)
    waiting = deliveries(app)
    assert [(d["event"], d["state"], d["attempts"]) for d in waiting] == [("invoice.created", "pending", 0)] and net.calls == []     # written, not yet sent
    assert run(app) == 1
    call = net.calls[0]
    assert call["method"] == "POST" and call["url"] == URL and call["allow_redirects"] is False and call["timeout"] == webhooks.TIMEOUT
    assert call["headers"]["webhook-id"] == str(waiting[0]["id"]) and call["headers"]["Content-Type"] == "application/json"
    assert signed_by(made["signing_key"], call) and not signed_by(webhooks.new_signing_key(), call)
    body = json.loads(call["data"])
    assert body["type"] == "invoice.created" and body["timestamp"].endswith("Z")
    assert body["data"] == {"order_id": order["id"], "order_number": order["number"], "status": "nieuw", "invoice_number": order["invoice_number"],
                            "invoice_date": order["invoice_date"], "total": order["totals"]["total"], "url": f"/api/v1/orders/{order['id']}"}
    assert "Jansen" not in call["data"].decode() and "Kerkstraat" not in call["data"].decode()
    done = deliveries(app)[0]
    assert (done["state"], done["attempts"], done["last_status"], done["next_attempt_at"]) == ("delivered", 1, 200, None)
    # The receiver's own check, with the package and a clock at the moment of sending, accepts it and refuses a changed body.
    monkeypatch.setattr("standardwebhooks.webhooks.datetime", type("At", (datetime,), {"now": classmethod(lambda cls, tz=None: T0)}))
    assert Webhook(made["signing_key"]).verify(call["data"], call["headers"])["type"] == "invoice.created"
    with pytest.raises(WebhookVerificationError):
        Webhook(made["signing_key"]).verify(call["data"].replace(b"nieuw", b"betaald"), call["headers"])
    # Making the same invoice again is reported as the same invoice, made again.
    assert post(owner, f"/api/orders/{order['id']}/invoice").status_code == 200
    assert [d["event"] for d in deliveries(app)] == ["invoice.created", "invoice.updated"]


def test_a_message_is_only_written_when_the_change_is_kept_and_only_for_who_asked(owner, app, monkeypatch):
    Net(monkeypatch)
    invoices = new_endpoint(owner, events=("invoice.created",), name="Facturen")["endpoint"]["id"]
    orders = new_endpoint(owner, events=("order.created", "order.status_changed", "order.updated", "order.deleted"), url=URL + "/orders", name="Bestellingen")["endpoint"]["id"]
    off = new_endpoint(owner, events=webhooks.EVENTS, url=URL + "/off", name="Uit")["endpoint"]["id"]
    assert owner.patch(f"/api/integrations/webhooks/{off}", json={"enabled": False}, headers=H).status_code == 200
    business(owner)
    empty = new_order(owner, lines=[])
    assert post(owner, f"/api/orders/{empty['id']}/invoice").status_code == 409            # no lines: no invoice, no number, no message
    assert [d["event"] for d in deliveries(app, invoices)] == [] and deliveries(app, off) == []
    assert [d["event"] for d in deliveries(app, orders)] == ["order.created"]
    # The status set to what it was is not a change; a real change says what it was before.
    assert owner.patch(f"/api/orders/{empty['id']}/status", json={"status": "nieuw"}, headers=H).status_code == 200
    assert owner.patch(f"/api/orders/{empty['id']}/status", json={"status": "verstuurd"}, headers=H).status_code == 200
    changed = deliveries(app, orders)[-1]
    assert changed["event"] == "order.status_changed" and json.loads(changed["body"])["data"]["previous_status"] == "nieuw"
    assert len(deliveries(app, orders)) == 2
    # Saving the whole order with another status reports both; taking it away reports what was removed.
    full = owner.get(f"/api/orders/{empty['id']}").get_json()
    saved = owner.put(f"/api/orders/{empty['id']}", json={**{k: full[k] for k in ("customer_id", "subject", "order_date", "delivery_date")}, "status": "afgehandeld", "lines": [line()]}, headers=H)
    assert saved.status_code == 200, saved.get_json()
    assert [d["event"] for d in deliveries(app, orders)][2:] == ["order.updated", "order.status_changed"]
    log = owner.get(f"/api/integrations/webhooks/{orders}/deliveries").get_json()["deliveries"]       # newest first, also within one moment
    assert [d["event"] for d in log] == ["order.status_changed", "order.updated", "order.status_changed", "order.created"]
    assert owner.delete(f"/api/orders/{empty['id']}", headers=H).status_code == 200
    gone = json.loads(deliveries(app, orders)[-1]["body"])
    assert gone["type"] == "order.deleted" and gone["data"]["order_id"] == empty["id"] and "url" not in gone["data"]
    assert deliveries(app, invoices) == [] and deliveries(app, off) == []


def test_a_failure_is_tried_again_later_with_the_same_message_and_given_up_in_the_end(owner, app, monkeypatch):
    net = Net(monkeypatch, status=500)
    endpoint = new_endpoint(owner)["endpoint"]["id"]
    invoiced_order(owner)
    assert run(app, T0) == 1
    row = deliveries(app)[0]
    assert (row["state"], row["attempts"], row["last_status"], row["last_error"]) == ("pending", 1, 500, "webhook.err_status")
    assert timedelta(seconds=50) < row["next_attempt_at"] - T0 < timedelta(seconds=70)               # about a minute, not on the second
    assert run(app, T0 + timedelta(seconds=30)) == 0 and len(net.calls) == 1                        # not before its time
    moment = T0
    for minutes in webhooks.BACKOFF:
        moment += timedelta(minutes=minutes * 1.2)
        assert run(app, moment) == 1
    assert len({c["headers"]["webhook-id"] for c in net.calls}) == 1 and len({c["data"] for c in net.calls}) == 1      # the same message every time
    dead = deliveries(app)[0]
    assert (dead["state"], dead["attempts"], dead["next_attempt_at"]) == ("dead", len(webhooks.BACKOFF) + 1, None)
    assert run(app, moment + timedelta(days=1)) == 0
    shown = owner.get("/api/integrations/webhooks").get_json()["endpoints"][0]
    assert shown["dead"] == 1 and shown["waiting"] == 0 and shown["failing_since"] is not None
    log = owner.get(f"/api/integrations/webhooks/{endpoint}/deliveries").get_json()["deliveries"]
    assert [(d["event"], d["state"], d["last_error"]) for d in log] == [("invoice.created", "dead", "webhook.err_status")]
    # Sent again by hand, once the receiver is back.
    net.status = 204
    assert post(owner, f"/api/integrations/webhooks/{endpoint}/deliveries/{log[0]['id']}/retry").status_code == 200
    assert post(owner, f"/api/integrations/webhooks/{endpoint}/deliveries/{log[0]['id']}/retry").status_code == 404      # it is not dead any more
    assert run(app, datetime.now(timezone.utc) + timedelta(seconds=5)) == 1
    assert deliveries(app)[0]["state"] == "delivered" and owner.get("/api/integrations/webhooks").get_json()["endpoints"][0]["failing_since"] is None


def test_two_workers_do_not_send_the_same_message(owner, app, monkeypatch):
    net = Net(monkeypatch)
    new_endpoint(owner)
    invoiced_order(owner)
    claimed = []
    real_send = webhooks.send
    def slow_send(*args, **kwargs):
        claimed.append(run(app, T0))                                  # the other worker comes by while this one is still sending
        return real_send(*args, **kwargs)
    monkeypatch.setattr(webhooks, "send", slow_send)
    assert run(app, T0) == 1 and claimed == [0] and len(net.calls) == 1


def test_an_address_that_takes_nothing_for_days_or_says_it_is_gone_is_switched_off(owner, app, monkeypatch):
    net = Net(monkeypatch, status=503)
    endpoint = new_endpoint(owner, events=("order.created",))["endpoint"]["id"]
    new_order(owner)
    run(app, T0)
    assert owner.get("/api/integrations/webhooks").get_json()["endpoints"][0]["enabled"] is True
    new_order(owner, name="Tweede klant")
    sql(app, "UPDATE webhook_deliveries SET next_attempt_at = %s", (T0 + webhooks.GIVE_UP_AFTER,))
    run(app, T0 + webhooks.GIVE_UP_AFTER + timedelta(minutes=1))
    off = owner.get("/api/integrations/webhooks").get_json()["endpoints"][0]
    assert off["enabled"] is False and off["disabled_reason"] == "failing"
    calls = len(net.calls)
    new_order(owner, name="Derde klant")                              # nothing is written for an address that is off, and nothing sent
    assert run(app, T0 + timedelta(days=10)) == 0 and len(net.calls) == calls and len(deliveries(app)) == 2
    # Switched on again by hand it starts clean, and what was waiting goes out.
    net.status = 200
    on = owner.patch(f"/api/integrations/webhooks/{endpoint}", json={"enabled": True}, headers=H).get_json()["endpoint"]
    assert on["enabled"] is True and on["disabled_reason"] == "" and on["failing_since"] is None
    assert run(app, T0 + timedelta(days=10)) == 2
    net.status = 410
    new_order(owner, name="Vierde klant")
    run(app, T0 + timedelta(days=11))
    gone = owner.get("/api/integrations/webhooks").get_json()["endpoints"][0]
    assert gone["enabled"] is False and gone["disabled_reason"] == "gone"


def test_what_goes_wrong_on_the_way_is_a_reason_not_the_other_sides_words(owner, app, monkeypatch):
    net = Net(monkeypatch)
    endpoint = new_endpoint(owner, events=("order.created",))["endpoint"]["id"]
    def reason_after(change, minutes):
        change()
        new_order(owner, name=f"Klant {minutes}")
        sql(app, "UPDATE webhook_deliveries SET next_attempt_at = %s WHERE state = 'pending'", (T0,))
        run(app, T0 + timedelta(minutes=minutes))
        return deliveries(app)[-1]["last_error"]
    assert reason_after(lambda: setattr(net, "status", 302), 1) == "webhook.err_redirect"            # not followed
    assert reason_after(lambda: setattr(net, "fail", requests.Timeout("slow")), 2) == "webhook.err_timeout"
    assert reason_after(lambda: setattr(net, "fail", requests.ConnectionError("no route to 10.0.0.7")), 3) == "webhook.err_unreachable"
    net.fail = None
    before = len(net.calls)
    assert reason_after(lambda: setattr(net, "resolves_to", "169.254.169.254"), 4) == "webhook.err_address"      # a name that points at link-local
    assert len(net.calls) == before                                   # nothing was sent there: not the new message, not the ones still waiting
    text = json.dumps([dict(d) for d in deliveries(app)], default=str) + owner.get(f"/api/integrations/webhooks/{endpoint}/deliveries").get_data(as_text=True)
    assert "INTERNAL-ANSWER" not in text and "10.0.0.7" not in text and "slow" not in text


def test_a_key_that_cannot_be_read_any_more_sends_nothing_until_a_new_one_is_made(owner, app, monkeypatch):
    net = Net(monkeypatch)
    endpoint = new_endpoint(owner)["endpoint"]["id"]
    resealed = passwords.seal("y" * 40, b"whsec_c29tZXRoaW5n", webhooks.KEY_INFO).decode()            # as after SESSION_SECRET changed
    sql(app, "UPDATE webhook_endpoints SET signing_key_enc = %s", (resealed,))
    assert owner.get("/api/integrations/webhooks").get_json()["endpoints"][0]["readable"] is False
    invoiced_order(owner)
    run(app, T0)
    assert net.calls == [] and deliveries(app)[0]["last_error"] == "webhook.err_key_unreadable"
    fresh = post(owner, f"/api/integrations/webhooks/{endpoint}/rotate", proof(owner, "webhook-rotate", endpoint)).get_json()["signing_key"]
    sql(app, "UPDATE webhook_deliveries SET next_attempt_at = %s", (T0,))
    run(app, T0 + timedelta(minutes=1))
    assert len(net.calls) == 1 and signed_by(fresh, net.calls[0], T0 + timedelta(minutes=1))
    assert owner.get("/api/integrations/webhooks").get_json()["endpoints"][0]["readable"] is True


def test_the_test_button_gives_a_verdict_and_nothing_of_the_answer(owner, app, monkeypatch):
    net = Net(monkeypatch)
    made = new_endpoint(owner)
    endpoint = made["endpoint"]["id"]
    ok = post(owner, f"/api/integrations/webhooks/{endpoint}/test")
    assert ok.status_code == 200 and ok.get_json() == {"ok": True, "status": 200} and "INTERNAL-ANSWER" not in ok.get_data(as_text=True)
    assert json.loads(net.calls[0]["data"])["type"] == "ping"
    net.status = 401
    refused = post(owner, f"/api/integrations/webhooks/{endpoint}/test", headers={**H, "X-Lang": "nl"})
    assert refused.status_code == 502 and "401" in refused.get_json()["error"] and "INTERNAL-ANSWER" not in refused.get_data(as_text=True)
    log = owner.get(f"/api/integrations/webhooks/{endpoint}/deliveries").get_json()["deliveries"]
    assert sorted((d["event"], d["state"]) for d in log) == [("ping", "dead"), ("ping", "delivered")]
    assert post(owner, f"/api/integrations/webhooks/{uuid.uuid4()}/test").status_code == 404


def test_the_log_forgets_what_is_old_and_keeps_what_still_waits(owner, app, monkeypatch):
    Net(monkeypatch)
    new_endpoint(owner, events=("order.created",))
    new_order(owner)
    run(app, T0)
    new_order(owner, name="Later")
    sql(app, "UPDATE webhook_deliveries SET created_at = %s", (T0 - webhooks.KEEP - timedelta(days=1),))
    sql(app, "UPDATE webhook_deliveries SET next_attempt_at = %s WHERE state = 'pending'", (T0 + timedelta(days=400),))
    run(app, T0 + timedelta(minutes=1))
    assert [d["state"] for d in deliveries(app)] == ["pending"]


def test_the_worker_sends_what_is_due_and_stops_when_told(owner, app, monkeypatch):
    import threading
    net = Net(monkeypatch)
    new_endpoint(owner, events=("order.created",))
    new_order(owner)
    stop = threading.Event()
    thread = webhooks.start_worker(app, every_seconds=0.05, stop=stop)
    for _ in range(100):
        if net.calls:
            break
        stop.wait(0.05)
    stop.set()
    thread.join(5)
    assert len(net.calls) == 1 and not thread.is_alive() and deliveries(app)[0]["state"] == "delivered"
    assert webhooks.worker_wanted(app) is False                       # switched off for the tests, and never in a test app


# --- neither is in a backup ---------------------------------------------------------------------------------------------------

def test_keys_and_endpoints_are_in_no_backup_and_a_restore_leaves_them_alone(owner, app, monkeypatch):
    Net(monkeypatch)
    key, hook = new_key(owner), new_endpoint(owner, events=("order.created",))
    new_order(owner)
    doc = backup(owner)
    text = doc.get_data(as_text=True)
    for word in (key["key"], key["key"][:10], "ppk_", "api_keys", "key_hash", hook["signing_key"], "whsec_", "finance.example.test", "webhook", "signing"):
        assert word not in text, word
    assert post(owner, "/api/backup/restore", doc.get_json()).status_code == 200
    assert app.test_client().get("/api/v1", headers=bearer(key["key"])).status_code == 200
    assert [e["url"] for e in owner.get("/api/integrations/webhooks").get_json()["endpoints"]] == [URL]


def test_every_reason_a_delivery_can_fail_with_has_words_on_the_screen():
    """The log keeps a reason as a key and the screen words it (`t(reason)`, a key the catalogue test cannot see): each needs a text there."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    reasons = set(re.findall(r'"(webhook\.err_(?:address|gone|key_unreadable|redirect|status|timeout|unreachable))"', (root / "backend/app/webhooks.py").read_text(encoding="utf-8")))
    assert len(reasons) == 7
    for language in ("nl", "en"):
        texts = json.loads((root / "frontend/lang" / f"{language}.json").read_text(encoding="utf-8"))
        assert reasons <= set(texts), sorted(reasons - set(texts))
        assert "{code}" in texts["webhook.err_status"]
