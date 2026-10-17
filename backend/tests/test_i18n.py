"""Words live in catalogs, in two languages, and every screen and every server message uses them.

The app is Dutch and English; the browser's language is the default, a choice is saved with the account.
These tests keep the catalogs complete and alike, and the server's answers in the language asked for."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest
from pywebpush import WebPushException

from app import i18n
from tests.test_auth_api import H, onboard, post
from tests.test_push import ENDPOINT, owner, pushapp, subscribe  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[2]
BACK, FRONT = ROOT / "backend" / "app", ROOT / "frontend"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


EN = {"X-Lang": "en"}
NL = {"X-Lang": "nl"}


# --- the catalogs --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("folder", [BACK / "lang", FRONT / "lang"], ids=["server", "screens"])
def test_both_languages_have_the_same_keys_and_the_same_placeholders(folder):
    nl, en = load(folder / "nl.json"), load(folder / "en.json")
    assert set(nl) == set(en), (sorted(set(nl) ^ set(en)))
    for key in nl:
        assert set(PLACEHOLDER.findall(nl[key])) == set(PLACEHOLDER.findall(en[key])), key
        assert nl[key].strip() and en[key].strip(), key


@pytest.mark.parametrize("folder", [BACK / "lang", FRONT / "lang"], ids=["server", "screens"])
def test_english_is_translated_not_copied(folder):
    nl, en = load(folder / "nl.json"), load(folder / "en.json")
    same = sorted(k for k in nl if nl[k] == en[k] and len(nl[k]) > 14 and not k.endswith(("_ph", "_name")) and k != "push.test_title")
    assert same == [], same


def test_every_key_the_screens_use_has_text():
    keys = load(FRONT / "lang" / "nl.json")
    used, dynamic = set(), set()
    for script in (FRONT / "js").glob("*.js"):
        text = script.read_text(encoding="utf-8")
        used |= set(re.findall(r"""\bt\(\s*['"]([\w.]+)['"]""", text))
        dynamic |= {m for m in re.findall(r"\bt\(`([\w.${}]+)`", text)}
    used.discard("key")                                                    # the parameter name inside i18n.js
    missing = sorted(k for k in used if k not in keys and f"{k}_one" not in keys)
    assert missing == [], missing
    assert dynamic == {"${config.id}.edit", "${config.id}.new"}            # the one computed key, covered by these entries
    for res in ("filament", "packaging", "printer", "tariff"):
        assert f"{res}.new" in keys and f"{res}.edit" in keys


def test_every_key_the_server_uses_has_text():
    keys = load(BACK / "lang" / "nl.json")
    used = set()
    for module in BACK.glob("*.py"):
        text = module.read_text(encoding="utf-8")
        used |= set(re.findall(r"""(?:ApiError\(\s*\d+,\s*|\bL\(|Localized\(|\btr\(|translate\([\w.\(\)]+,\s*|PrintFileError\(|WebAuthnError\()\s*["']([\w.]+)["']""", text))
        used |= set(re.findall(r"""\b(?:text|number|boolean|optional_int)\(\s*["'](f\.\w+)["']""", text))
    missing = sorted(k for k in used if k not in keys and f"{k}_one" not in keys)
    assert missing == [], missing
    assert len(used) > 80


def test_no_dutch_text_is_left_in_the_screens():
    """A Dutch sentence in a quoted string is a text that never reaches the English screen."""
    dutch = re.compile(r"\b(?:de|het|een|niet|geen|je|jouw|moet|voor|naar|ook|deze|dit|wordt|voeg|kies|nog|maak|sla)\b")
    offenders = []
    for script in (FRONT / "js").glob("*.js"):
        for number, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("//")[0]
            for literal in re.findall(r"""(?<![\w.])(?:'([^'\n]{12,})'|"([^"\n]{12,})")""", code):
                text = literal[0] or literal[1]
                if " " in text and dutch.search(text.lower()):
                    offenders.append(f"{script.name}:{number}: {text[:60]}")
    assert offenders == [], offenders


# --- choosing a language -----------------------------------------------------------------------------------------

def test_the_server_picks_header_then_saved_choice_then_browser_then_dutch(client):
    onboard(client)
    def say(headers):
        return client.post("/api/calculate", json={"data": "x"}, headers={**H, **headers}).get_json()["error"]
    assert say({}) == "'data' ontbreekt."                                                    # nothing known: Dutch
    assert say({"Accept-Language": "en-GB,en;q=0.9"}) == "'data' is missing."               # the browser's language
    assert say({"Accept-Language": "de-DE,fr;q=0.8,en;q=0.5"}) == "'data' is missing."      # first one we speak
    assert say({"Accept-Language": "de-DE"}) == "'data' ontbreekt."
    assert client.put("/api/preferences", json={"language": "en"}, headers=H).status_code == 200
    assert say({"Accept-Language": "nl"}) == "'data' is missing."                           # the saved choice beats the browser
    assert say(NL) == "'data' ontbreekt."                                                   # what the screen shows beats both


def test_the_language_is_saved_with_the_account_and_must_be_one_we_have(client):
    onboard(client)
    assert client.get("/api/preferences", headers=H).get_json().get("language") is None
    assert client.put("/api/preferences", json={"language": "fr"}, headers=H).status_code == 400
    assert client.put("/api/preferences", json={"language": 1}, headers=H).status_code == 400
    saved = client.put("/api/preferences", json={"language": "en"}, headers=H)
    assert saved.get_json()["language"] == "en" and client.get("/api/preferences", headers=H).get_json()["language"] == "en"
    client.post("/api/auth/logout", headers=H)                                              # every device: it is in the database
    assert client.get("/api/preferences", headers=H).status_code == 401


# --- the server speaks it ------------------------------------------------------------------------------------------

def test_errors_come_back_in_the_requested_language(client):
    assert client.get("/api/spools", headers=EN).get_json()["error"] == "Not signed in."
    assert client.get("/api/spools", headers=NL).get_json()["error"] == "Niet ingelogd."
    assert client.get("/api/nope", headers=EN).get_json()["error"] == "Not found."
    onboard(client)
    assert client.get("/api/nope", headers=EN).get_json()["error"] == "Not found."


def test_validation_messages_translate_their_field_names_too(client):
    onboard(client)
    body = {"brand": "", "roll_weight_g": 1000, "price": 1, "remaining_g": 1}
    assert client.post("/api/spools", json=body, headers={**H, **NL}).get_json()["error"] == "Merk is verplicht."
    assert client.post("/api/spools", json=body, headers={**H, **EN}).get_json()["error"] == "Brand is required."
    bad = {**body, "brand": "x", "price": "abc"}
    assert client.post("/api/spools", json=bad, headers={**H, **EN}).get_json()["error"] == "Roll price: 'abc' is not a number."
    low = {**body, "brand": "x", "roll_weight_g": 0}
    assert client.post("/api/spools", json=low, headers={**H, **EN}).get_json()["error"] == "Roll weight (g): must be greater than 0."
    assert client.post("/api/spools", json=low, headers={**H, **NL}).get_json()["error"] == "Gewicht rol (g): moet groter dan 0 zijn."
    temp = {**body, "brand": "x", "print_temp_c": "900"}
    assert "whole number between 0 and 500" in client.post("/api/spools", json=temp, headers={**H, **EN}).get_json()["error"]


def test_calculation_errors_name_the_line_in_the_requested_language(client):
    onboard(client)
    data = {"data": {"filament": [{"grams": "x", "price_per_kg": 1}]}}
    assert client.post("/api/calculate", json=data, headers={**H, **NL}).get_json()["error"] == "Filament 1: gram: 'x' is geen getal."
    assert client.post("/api/calculate", json=data, headers={**H, **EN}).get_json()["error"] == "Filament 1: grams: 'x' is not a number."
    vat = {"data": {}, "vat_pct": 150}
    assert client.post("/api/calculate", json=vat, headers={**H, **EN}).get_json()["error"] == "VAT: must be between 0 and 100%."


def test_password_and_login_messages_follow_the_language(client):
    onboard(client)
    weak = client.post("/api/auth/password/setup/start", json={"password": "short"}, headers={**H, **EN})
    assert weak.get_json()["error"] == "The password must have at least 12 characters."
    assert client.post("/api/auth/password/login", json={"password": "x"}, headers={**H, **EN}).get_json()["error"] == "Sign-in failed."
    assert client.post("/api/auth/password/login", json={"password": "x"}, headers={**H, **NL}).get_json()["error"] == "Inloggen mislukt."


def test_print_file_errors_come_back_translated(client):
    import io
    onboard(client)
    junk = {"file": (io.BytesIO(b"not a model at all"), "x.stl")}
    dutch = client.post("/api/print-files", data=junk, headers={**H, **NL}, content_type="multipart/form-data")
    junk = {"file": (io.BytesIO(b"not a model at all"), "x.stl")}
    english = client.post("/api/print-files", data=junk, headers={**H, **EN}, content_type="multipart/form-data")
    assert dutch.status_code == english.status_code == 400
    assert dutch.get_json()["error"] != english.get_json()["error"] and english.get_json()["error"].startswith(("This ", "The "))


def test_a_message_without_text_shows_its_key_instead_of_nothing():
    assert i18n.translate("en", "no.such.key") == "no.such.key"
    assert i18n.translate("fr", "err.not_found") == "Niet gevonden."                         # an unknown language falls back to Dutch
    assert i18n.translate("en", "stock.rolls", n=1) == "stock.rolls"


# --- notifications ---------------------------------------------------------------------------------------------------

def test_the_test_notification_and_its_failure_reasons_follow_the_language(owner):
    subscribe(owner)
    with mock.patch("app.push.webpush", side_effect=[WebPushException("no", response=mock.Mock(status_code=403))]) as sent:
        english = post(owner, "/api/push/test", headers={**H, **EN}).get_json()
    assert english["results"][0]["reason"].startswith("push.example.test rejects this server")
    assert json.loads(sent.call_args.kwargs["data"])["body"] == "Test notification: notifications work on this device."
    with mock.patch("app.push.webpush", side_effect=[None]) as sent:
        post(owner, "/api/push/test", headers={**H, **NL})
    assert json.loads(sent.call_args.kwargs["data"])["body"] == "Testmelding: meldingen werken op dit apparaat."


def test_a_stored_failure_is_shown_in_the_language_read_at_the_time_not_the_one_it_happened_in(owner):
    subscribe(owner)
    with mock.patch("app.push.webpush", side_effect=[ConnectionError("down")]):
        post(owner, "/api/push/test", headers={**H, **NL})
    nl = owner.get("/api/push/devices", headers=NL).get_json()["devices"][0]["last_error"]
    en = owner.get("/api/push/devices", headers=EN).get_json()["devices"][0]["last_error"]
    assert nl.startswith("De server bereikt push.example.test niet") and en.startswith("The server cannot reach push.example.test")


def test_the_release_announcement_speaks_each_persons_saved_language(owner, pushapp):
    from announce_release import announce
    subscribe(owner)
    owner.put("/api/preferences", json={"language": "en"}, headers=H)
    pool, cfg = pushapp.extensions["pool"], pushapp.config["APP_CONFIG"]
    announce(pool, cfg, "v1 (a)")                                                          # first run only records the version
    with mock.patch("app.push.webpush") as sent:
        announce(pool, cfg, "v2 (b)")
    body = json.loads(sent.call_args.kwargs["data"])["body"]
    assert body == "Version v2 (b) is available. Open the app to update."
