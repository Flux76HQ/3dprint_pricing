"""What a set of AI pictures cost: the tokens OpenAI counts are kept with every picture (never guessed), the prices and the rate they were worked out at are kept with them,
money is Decimal and a set is rounded to cents before sets are added, the ledger stays when the calculation goes, and it goes through a backup."""
import dataclasses
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app import ai_images
from tests.test_auth_api import H, post
from tests.test_ai_images import FakeOpenAI, KEY, _inline, ai, owner, photo, project, queue, ready, set_key, state  # noqa: F401  (fixtures)
from tests.test_users import join_with_passkey

# What a GPT image model reports for one picture. At OpenAI's list price for gpt-image-2 (5, 8 and 30 dollars per million) that is
# (300 * 5 + 1200 * 8 + 4160 * 30) / 1,000,000 = 0.1359 dollars, so 0.5436 for a set of four (0.54 on the screen).
USAGE = {"input_tokens": 1500, "input_tokens_details": {"text_tokens": 300, "image_tokens": 1200}, "output_tokens": 4160, "total_tokens": 5660}


def rows(app, query="SELECT * FROM ai_image_usage ORDER BY id", params=()):
    with app.extensions["pool"].connection() as conn:
        return conn.execute(query, params).fetchall()


def usage(client, lang="en"):
    res = client.get("/api/ai-images/usage", headers={"X-Lang": lang})
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def settings(client, **body):
    return client.put("/api/ai-images/settings", json=body, headers={**H, "X-Lang": "en"})


def make_set(owner, project, monkeypatch, *, purpose="webshop", **fake):
    """One set of four pictures, as OpenAI answers `fake`."""
    FakeOpenAI(monkeypatch, **fake)
    assert queue(owner, project, purpose=purpose).status_code == 202


# --- what OpenAI said --------------------------------------------------------------------------------------------------

def test_the_tokens_are_what_openai_counted_and_nothing_less():
    assert ai_images.usage_of({"data": [], "usage": USAGE}) == {"input_text": 300, "input_image": 1200, "output": 4160}
    assert ai_images.usage_of({"usage": {"input_tokens_details": {"text_tokens": 0, "image_tokens": 0}, "output_tokens": 0}}) == {"input_text": 0, "input_image": 0, "output": 0}


@pytest.mark.parametrize("answer", [
    None, [], "usage", {}, {"usage": None}, {"usage": []}, {"usage": {"output_tokens": 5}},                                       # nothing, or nothing like it
    {"usage": {"input_tokens_details": None, "output_tokens": 5}}, {"usage": {"input_tokens_details": [1, 2], "output_tokens": 5}},
    {"usage": {"input_tokens_details": {"text_tokens": 1, "image_tokens": 2}}},                                                 # no output
    {"usage": {"input_tokens_details": {"text_tokens": 1}, "output_tokens": 5}},                                                # the split is not all there
    {"usage": {"input_tokens_details": {"text_tokens": 1.0, "image_tokens": 2}, "output_tokens": 5}},                           # a count is a whole number
    {"usage": {"input_tokens_details": {"text_tokens": True, "image_tokens": 2}, "output_tokens": 5}},
    {"usage": {"input_tokens_details": {"text_tokens": "1", "image_tokens": 2}, "output_tokens": 5}},
    {"usage": {"input_tokens_details": {"text_tokens": -1, "image_tokens": 2}, "output_tokens": 5}},
    {"usage": {"input_tokens_details": {"text_tokens": 1, "image_tokens": 2}, "output_tokens": 10**9 + 1}},
])
def test_an_answer_that_does_not_say_it_completely_gives_no_tokens(answer):
    assert ai_images.usage_of(answer) is None


def row(**over):
    return {"reported": True, "input_text_tokens": 300, "input_image_tokens": 1200, "output_tokens": 4160, "price_text_in": Decimal("5"), "price_image_in": Decimal("8"),
            "price_image_out": Decimal("30"), "usd_eur": None, **over}


def test_the_cost_is_the_tokens_times_the_price_per_million_in_decimals():
    cost = ai_images.cost_usd(row())
    assert cost == Decimal("0.1359") and isinstance(cost, Decimal)
    assert ai_images.cost_usd(row(output_tokens=1)) == Decimal("0.01113")                  # (1500 + 9600 + 30) / 1,000,000: exact, not a float


def test_no_cost_is_worked_out_from_half_a_picture_of_information():
    assert ai_images.cost_usd(row(reported=False)) is None
    assert ai_images.cost_usd(row(price_image_in=None)) is None                           # a kind that was used, without a price
    assert ai_images.cost_usd(row(price_image_in=None, input_image_tokens=0)) == Decimal("0.1263")      # a kind that was not used does not need one: (1500 + 124800) / 1,000,000


def test_a_set_is_rounded_to_cents_before_sets_are_added_so_the_lines_add_up():
    one = {"batch_id": "b", "created_at": datetime(2026, 11, 12, tzinfo=timezone.utc), "project_id": None, "project_number": 1, "project_name": "x", "purpose": "social",
           **row(input_text_tokens=0, input_image_tokens=0, output_tokens=163)}               # 163 * 30 / 1e6 = 0.00489 dollars: nothing at all in cents
    rows_ = [{**one, "batch_id": f"b{n}"} for n in range(3)]
    report = ai_images.usage_report(rows_, {"usd_eur": None, "model": "gpt-image-2", "price_text_in": None, "price_image_in": None, "price_image_out": None},
                                    datetime(2026, 11, 20, tzinfo=timezone.utc))
    assert [s["cost_usd"] for s in report["sets"]] == ["0.00"] * 3 and report["totals"]["all"]["cost_usd"] == "0.00"      # not 0.01 from 0.01467 of dollars


# --- the ledger ----------------------------------------------------------------------------------------------------------

def test_every_picture_is_recorded_with_its_tokens_in_the_set_it_was_made_in(ai, project, monkeypatch, app):
    ready(ai, project, monkeypatch)
    make_set(ai, project, monkeypatch, usage=USAGE)
    ledger = rows(app)
    assert len(ledger) == 4 and len({str(r["batch_id"]) for r in ledger}) == 1
    assert {(r["input_text_tokens"], r["input_image_tokens"], r["output_tokens"], r["reported"]) for r in ledger} == {(300, 1200, 4160, True)}
    assert {(r["model"], r["quality"], r["purpose"], r["project_number"], r["project_name"]) for r in ledger} == {("gpt-image-2", "medium", "webshop", project["number"], project["name"])}
    assert sorted(r["variant"] for r in ledger) == sorted(ai_images.PURPOSES["webshop"][0])
    report = usage(ai)
    [one] = report["sets"]
    assert (one["pictures"], one["tokens"], one["reported"]) == (4, {"input_text": 1200, "input_image": 4800, "output": 16640, "total": 22640}, True)
    assert one["cost_usd"] == "0.54" and one["cost_eur"] is None and one["purpose"] == "webshop"                         # 0.5436 dollars; no rate, so no euros yet
    assert report["totals"]["all"] == {"sets": 1, "pictures": 4, "tokens": 22640, "cost_usd": "0.54", "cost_eur": None, "without_usd": 0, "without_eur": 1}
    assert report["totals"]["month"] == report["totals"]["all"]


def test_a_picture_that_failed_costs_nothing_and_an_answer_without_usage_is_not_guessed(ai, project, monkeypatch, app):
    ready(ai, project, monkeypatch)
    FakeOpenAI(monkeypatch, status=500)
    queue(ai, project, purpose="social")
    assert rows(app) == [] and usage(ai)["sets"] == []
    FakeOpenAI(monkeypatch)                                                                # made, and OpenAI did not say what it counted
    queue(ai, project, purpose="social")
    ledger = rows(app)
    assert len(ledger) == 4 and {(r["reported"], r["input_text_tokens"], r["input_image_tokens"], r["output_tokens"]) for r in ledger} == {(False, 0, 0, 0)}
    [one] = usage(ai)["sets"]
    assert one["reported"] is False and one["cost_usd"] is None and one["cost_eur"] is None and one["tokens"]["total"] == 0
    assert usage(ai)["totals"]["all"]["without_usd"] == 1


def test_the_euros_follow_the_rate_a_picture_was_made_at_else_the_current_one(ai, project, monkeypatch, app):
    ready(ai, project, monkeypatch)
    make_set(ai, project, monkeypatch, usage=USAGE, purpose="marktplaats")                  # made before there was a rate
    assert settings(ai, usd_eur="0,92").get_json()["usd_eur"] == "0.92"                    # a comma is as good as a point
    make_set(ai, project, monkeypatch, usage=USAGE, purpose="social")                      # made at 0.92
    first, second = sorted(usage(ai)["sets"], key=lambda s: s["purpose"] != "marktplaats")
    assert (first["cost_usd"], first["cost_eur"]) == ("0.54", "0.50")                         # 0.5436 * 0.92 = 0.500112: the current rate, since none was kept
    assert (second["cost_usd"], second["cost_eur"]) == ("0.54", "0.50")
    settings(ai, usd_eur="1")
    first, second = sorted(usage(ai)["sets"], key=lambda s: s["purpose"] != "marktplaats")
    assert (first["cost_eur"], second["cost_eur"]) == ("0.54", "0.50")                        # the first follows the rate; the second keeps the one it was made at
    assert usage(ai)["totals"]["all"]["cost_eur"] == "1.04" and usage(ai)["rate"] == "1"


def test_prices_are_the_list_price_unless_typed_and_a_change_does_not_rewrite_what_was_spent(ai, project, monkeypatch, app):
    ready(ai, project, monkeypatch)
    assert usage(ai)["prices"] == {"text_in": "5", "image_in": "8", "image_out": "30"}
    make_set(ai, project, monkeypatch, usage=USAGE, purpose="marktplaats")
    res = settings(ai, prices={"text_in": "10", "image_out": "20,5"}).get_json()
    assert res["prices"] == {"text_in": "10", "image_in": None, "image_out": "20.5"} and res["price_defaults"] == {"text_in": "5", "image_in": "8", "image_out": "30"}
    assert usage(ai)["prices"] == {"text_in": "10", "image_in": "8", "image_out": "20.5"}            # what was typed, else the list price
    make_set(ai, project, monkeypatch, usage=USAGE, purpose="social")
    old, new = sorted(usage(ai)["sets"], key=lambda s: s["purpose"] != "marktplaats")
    assert (old["cost_usd"], new["cost_usd"]) == ("0.54", "0.39")                              # the first is still at 5, 8 and 30; the second is 4 * (3000 + 9600 + 85280) / 1e6 = 0.39152
    ledger = rows(app)
    assert {str(r["price_text_in"]) for r in ledger[:4]} == {"5.0000"} and {str(r["price_text_in"]) for r in ledger[4:]} == {"10.0000"}


def test_a_model_without_a_known_price_has_no_cost_until_prices_are_typed_and_a_new_model_drops_the_old_prices(ai, project, monkeypatch, app):
    ready(ai, project, monkeypatch)
    settings(ai, prices={"text_in": "7"}, usd_eur="0.9")
    res = settings(ai, model="gpt-image-3-preview").get_json()
    assert res["prices"] == {"text_in": None, "image_in": None, "image_out": None} and res["price_defaults"] == {} and res["usd_eur"] == "0.9"      # the rate is the person's, the prices were the model's
    make_set(ai, project, monkeypatch, usage=USAGE, purpose="marktplaats")
    [unpriced] = usage(ai)["sets"]
    assert unpriced["cost_usd"] is None and unpriced["cost_eur"] is None and unpriced["tokens"]["total"] == 22640 and usage(ai)["prices"] == {"text_in": None, "image_in": None, "image_out": None}
    settings(ai, prices={"text_in": "1", "image_in": "2", "image_out": "3"})
    make_set(ai, project, monkeypatch, usage=USAGE, purpose="social")
    unknown, priced = sorted(usage(ai)["sets"], key=lambda s: s["purpose"] != "marktplaats")
    assert unknown["cost_usd"] is None and priced["cost_usd"] == "0.06"                         # 4 * (300 + 2400 + 12480) / 1e6 = 0.06072; the first stays what it was
    assert usage(ai)["totals"]["all"] == {"sets": 2, "pictures": 8, "tokens": 45280, "cost_usd": "0.06", "cost_eur": "0.05", "without_usd": 1, "without_eur": 1}


def test_the_key_is_never_in_what_the_costs_answer(ai, project, monkeypatch):
    ready(ai, project, monkeypatch)
    make_set(ai, project, monkeypatch, usage=USAGE)
    assert KEY not in json.dumps(usage(ai)) and KEY not in json.dumps(settings(ai, usd_eur="0.9").get_json())


# --- typed prices and rate -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"prices": {"text_in": "abc"}}, {"prices": {"image_in": -1}}, {"prices": {"image_out": "NaN"}}, {"prices": {"image_out": "inf"}}, {"prices": {"text_in": 10**9}},
    {"prices": {"text_in": True}}, {"prices": {"text_in": [5]}}, {"prices": {"text_in": {"a": 1}}}, {"prices": "5"}, {"prices": [5]},
    {"usd_eur": 0}, {"usd_eur": "-1"}, {"usd_eur": 1000}, {"usd_eur": "x"}, {"usd_eur": ["0.9"]}, {"usd_eur": True}, {"usd_eur": "0,0"},
])
def test_a_price_or_a_rate_that_is_not_one_is_refused_and_nothing_is_saved(ai, body):
    before = ai.get("/api/ai-images/settings").get_json()
    res = settings(ai, **body)
    assert res.status_code == 400 and ("price" in res.get_json()["error"].lower() or "rate" in res.get_json()["error"].lower())
    assert ai.get("/api/ai-images/settings").get_json() == before


def test_prices_stay_when_left_out_and_empty_takes_them_away(ai):
    settings(ai, prices={"text_in": "6", "image_in": "9"}, usd_eur="0.91")
    assert settings(ai, quality="high").get_json()["prices"] == {"text_in": "6", "image_in": "9", "image_out": None}            # a request that does not mention them leaves them
    assert settings(ai, prices={"text_in": ""}).get_json()["prices"] == {"text_in": None, "image_in": "9", "image_out": None}   # empty: the list price again
    res = settings(ai, usd_eur=None).get_json()
    assert res["usd_eur"] is None and res["prices"]["image_in"] == "9"


def test_a_change_of_prices_is_in_the_log_and_one_that_changes_nothing_is_not(ai):
    settings(ai, prices={"text_in": "6"})
    settings(ai, prices={"text_in": "6"})
    messages = [e["message"] for e in ai.get("/api/ai-images/log", headers={"X-Lang": "en"}).get_json()]
    assert messages.count("Prices or rate for the costs changed.") == 1


# --- who sees it -----------------------------------------------------------------------------------------------------------

def test_the_costs_are_for_administrators_and_do_not_exist_without_the_flag(app, ai):
    member = join_with_passkey(app, ai)
    assert member.get("/api/ai-images/usage").status_code == 403
    assert app.test_client().get("/api/ai-images/usage").status_code == 401
    app.config["APP_CONFIG"] = dataclasses.replace(app.config["APP_CONFIG"], ai_images_enabled=False)
    assert ai.get("/api/ai-images/usage").status_code == 404


# --- what the ledger keeps and shows -----------------------------------------------------------------------------------------

def test_the_costs_stay_when_the_calculation_goes(ai, project, monkeypatch, app):
    ready(ai, project, monkeypatch)
    make_set(ai, project, monkeypatch, usage=USAGE)
    before = usage(ai)
    [one] = before["sets"]
    assert one["project_id"] == project["id"] and one["project_number"] == project["number"]
    assert ai.delete(f"/api/projects/{project['id']}", headers=H).status_code == 200
    after = usage(ai)
    [kept] = after["sets"]
    assert kept["project_id"] is None and kept["project_name"] == project["name"] and kept["project_number"] == project["number"]      # what it was called is kept with the money
    assert after["totals"] == before["totals"]


def insert(app, n, at, **over):
    values = {"created_at": at, "batch_id": f"00000000-0000-4000-8000-{n:012d}", "variant": "square", "model": "gpt-image-2", "quality": "medium", "purpose": "social", "reported": True,
              "input_text_tokens": 100, "input_image_tokens": 100, "output_tokens": 100, "price_text_in": Decimal("5"), "price_image_in": Decimal("8"), "price_image_out": Decimal("30"),
              "usd_eur": Decimal("0.9"), **over}
    with app.extensions["pool"].connection() as conn:
        conn.execute(f"INSERT INTO ai_image_usage ({', '.join(values)}) VALUES ({', '.join(['%s'] * len(values))})", tuple(values.values()))


def test_the_list_is_the_newest_sets_and_the_totals_count_all_of_them_and_this_month_only_this_month(ai, app, monkeypatch):
    now = datetime.now(timezone.utc)
    for n in range(ai_images.MAX_SETS + 5):                                                    # more sets than the screen lists, all this month
        insert(app, n, now.replace(microsecond=0, second=n % 60, minute=(n // 60) % 60))
    insert(app, 900, datetime(2020, 1, 15, 12, tzinfo=timezone.utc))                         # long ago
    report = usage(ai)
    assert len(report["sets"]) == ai_images.MAX_SETS and report["totals"]["all"]["sets"] == ai_images.MAX_SETS + 6 and report["totals"]["month"]["sets"] == ai_images.MAX_SETS + 5
    assert [s["at"] for s in report["sets"]] == sorted((s["at"] for s in report["sets"]), reverse=True)                # newest first
    assert all(s["cost_usd"] == "0.00" for s in report["sets"])                                # 100 tokens of each kind: 0.0043 dollars, nothing in cents


# --- backup ------------------------------------------------------------------------------------------------------------------------

def backup(owner):
    res = owner.get("/api/backup", headers=H)
    assert res.status_code == 200
    return res.get_json()


def test_the_costs_the_prices_and_the_rate_go_through_a_backup_and_the_key_does_not(ai, project, monkeypatch, app):
    ready(ai, project, monkeypatch)
    settings(ai, prices={"text_in": "6", "image_in": "9", "image_out": "31"}, usd_eur="0.93")
    make_set(ai, project, monkeypatch, usage=USAGE)
    before = usage(ai)
    doc = backup(ai)
    assert KEY not in json.dumps(doc) and len(doc["ai_image_usage"]) == 4 and doc["ai_image_settings"]["usd_eur"] == "0.93"
    assert doc["ai_image_settings"]["prices"] == {"text_in": "6", "image_in": "9", "image_out": "31"}
    assert doc["ai_image_usage"][0]["price_text_in"] == "6" and doc["ai_image_usage"][0]["project_id"] == project["id"]
    settings(ai, prices={"text_in": "", "image_in": "", "image_out": ""}, usd_eur=None)             # something else is there now
    insert(app, 7, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert post(ai, "/api/backup/restore", doc).status_code == 200
    assert usage(ai) == before                                                                 # exactly what was backed up: the extra row is gone, the rate and prices are back
    assert ai.get("/api/ai-images/settings").get_json()["last4"] == KEY[-4:]                   # the key stayed where it was


def test_a_backup_from_before_the_costs_restores_and_leaves_what_is_there(ai, project, monkeypatch, app):
    ready(ai, project, monkeypatch)
    settings(ai, prices={"text_in": "6"}, usd_eur="0.93")
    doc = backup(ai)
    doc.pop("ai_image_usage")
    doc["ai_image_settings"] = {"model": "gpt-image-2", "quality": "high"}
    insert(app, 5, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert post(ai, "/api/backup/restore", doc).status_code == 200
    res = ai.get("/api/ai-images/settings").get_json()
    assert res["quality"] == "high" and res["prices"]["text_in"] == "6" and res["usd_eur"] == "0.93"       # not in the file: not touched
    assert len(rows(app)) == 0                                                                  # the ledger is replaced by the file's, which has none


@pytest.mark.parametrize("change", [
    {"input_text_tokens": -1}, {"input_image_tokens": 1.5}, {"output_tokens": "5"}, {"output_tokens": 10**9 + 1}, {"variant": "nope"}, {"purpose": "nope"}, {"quality": "ultra"},
    {"model": "../x"}, {"reported": 1}, {"reported": "yes"}, {"price_text_in": "abc"}, {"price_image_out": 10**9}, {"usd_eur": 0}, {"usd_eur": 1000}, {"batch_id": "not an id"},
    {"project_number": -1}, {"project_name": "x" * 201}, {"created_at": "yesterday"}, "not a row",
])
def test_a_row_of_costs_that_is_not_right_stops_the_restore_and_says_which(ai, project, monkeypatch, app, change):
    ready(ai, project, monkeypatch)
    make_set(ai, project, monkeypatch, usage=USAGE)
    doc = backup(ai)
    doc["ai_image_usage"][2] = change if isinstance(change, str) else {**doc["ai_image_usage"][2], **change}
    before = usage(ai)
    res = post(ai, "/api/backup/restore", doc, headers={**H, "X-Lang": "nl"})
    assert res.status_code == 400 and "AI-afbeeldingen (kosten)" in res.get_json()["error"] and "3" in res.get_json()["error"]
    assert usage(ai) == before                                                                 # nothing was changed


def test_a_row_of_costs_keeps_its_calculation_only_when_the_file_has_it(ai, project, monkeypatch, app):
    ready(ai, project, monkeypatch)
    make_set(ai, project, monkeypatch, usage=USAGE)
    doc = backup(ai)
    doc["ai_image_usage"][0]["project_id"] = "11111111-1111-4111-8111-111111111111"          # a calculation that is not in the file
    assert post(ai, "/api/backup/restore", doc).status_code == 200
    ledger = rows(app)
    assert sum(1 for r in ledger if r["project_id"] is None) == 1 and sum(1 for r in ledger if r["project_id"] is not None) == 3
    assert {r["project_number"] for r in ledger} == {project["number"]}                       # the number and the name stay either way


# --- what goes together -------------------------------------------------------------------------------------------------------

def test_typed_prices_are_for_the_model_they_were_typed_for_only():
    typed = {"model": "gpt-image-2", "price_text_in": Decimal("7"), "price_image_in": None, "price_image_out": Decimal("40")}
    assert ai_images.prices_for(typed, "gpt-image-2") == {"text_in": Decimal("7"), "image_in": Decimal("8"), "image_out": Decimal("40")}        # typed, else the list price
    assert ai_images.prices_for(typed, "another-model") == {"text_in": None, "image_in": None, "image_out": None}                          # not the typed ones, and no list price


def test_a_picture_and_what_it_cost_are_stored_together_or_not_at_all(ai, project, monkeypatch, app):
    ready(ai, project, monkeypatch)
    FakeOpenAI(monkeypatch, usage=USAGE)

    def broken(*args, **kwargs):
        raise RuntimeError("the ledger could not be written")
    monkeypatch.setattr(ai_images, "_record_usage", broken)
    queue(ai, project, "square")
    assert rows(app) == [] and [i for i in state(ai, project)["images"] if i["kind"] == "generated"] == []       # no picture without its cost
    assert state(ai, project)["jobs"][0]["status"] == "failed"
