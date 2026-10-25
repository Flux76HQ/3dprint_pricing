"""The update check: it announces a newer release to the signed-in owner, reads GitHub politely, and never takes a page down."""
from pathlib import Path
from unittest import mock

import pytest
import requests

from app import updates
from app.config import _switch
from tests.test_auth_api import H
from tests.test_password import owner  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://github.com/Flux76HQ/3dprint_pricing"


class Answer:
    def __init__(self, status=302, location=None):
        self.status_code = status
        self.headers = {"Location": location} if location is not None else {}


def tag(version):
    return Answer(302, f"{BASE}/releases/tag/v{version}")


def github(*answers):
    """GitHub answers with these, one per call (the last one repeats); returns the mock so a test can see what was asked."""
    return mock.patch("app.updates.requests.get", side_effect=[*answers, *answers[-1:] * 50])


def status(client):
    res = client.get("/api/update")
    assert res.status_code == 200
    return res.get_json()


def check_now(client):
    res = client.post("/api/update/check", json={}, headers=H)
    assert res.status_code == 200
    return res.get_json()


@pytest.fixture
def checker(app):
    return app.extensions["update_checker"]


# --- numbers -------------------------------------------------------------------------------------------------

def test_versions_are_compared_part_by_part():
    assert updates.parse("v1.10.0") == (1, 10, 0) and updates.parse("2.1") == (2, 1)
    assert updates.is_newer("1.10.0", "1.9.0") and not updates.is_newer("1.9.0", "1.10.0")
    assert not updates.is_newer("2.1", "2.1.0") and not updates.is_newer("2.1.0", "2.1")
    assert updates.is_newer("2.1.1", "2.1") and updates.is_newer("0.26.19", "0.26.18")


@pytest.mark.parametrize("junk", ["", "latest", "1.2.x", "1..2", "0.26.19-beta", None])
def test_a_version_that_does_not_parse_is_not_newer_and_is_not_an_error(junk):
    assert updates.parse(junk) is None
    assert not updates.is_newer(junk, "0.26.18") and not updates.is_newer("0.26.19", junk)


# --- reading GitHub --------------------------------------------------------------------------------------------

def test_a_new_release_is_reported_with_a_link_to_this_repository(owner, app):
    current = app.extensions["update_checker"].current
    newer = f"{current.rsplit('.', 1)[0]}.{int(current.rsplit('.', 1)[1]) + 1}"
    with github(tag(newer)):
        body = status(owner)
    assert body["enabled"] and body["available"] and body["latest"] == newer and body["current"] == current
    assert body["url"] == f"{BASE}/releases/tag/v{newer}" and body["repo"] == "Flux76HQ/3dprint_pricing"
    assert body["error"] is None and body["checkedAt"]


def test_the_version_that_runs_is_not_an_update(owner, checker):
    with github(tag(checker.current)):
        body = status(owner)
    assert body["latest"] == checker.current and body["available"] is False and body["error"] is None


def test_a_beta_ahead_of_the_latest_release_has_nothing_to_update_to(owner):
    with github(tag("0.1.0")):
        assert status(owner)["available"] is False


def test_the_request_carries_nothing_about_the_installation(owner):
    with github(tag("9.9.9")) as get:
        status(owner)
    get.assert_called_once()
    assert get.call_args.args == (f"{BASE}/releases/latest",)
    assert get.call_args.kwargs["allow_redirects"] is False and get.call_args.kwargs["timeout"] <= 10
    assert get.call_args.kwargs["headers"] == {"User-Agent": updates.USER_AGENT}      # no version, no instance id, no cookie


def test_the_link_is_built_here_whatever_the_answer_says(owner):
    with github(Answer(302, "/Flux76HQ/3dprint_pricing/releases/tag/v9.9.9")):          # a relative Location is fine
        body = status(owner)
    assert body["url"] == f"{BASE}/releases/tag/v9.9.9"


@pytest.mark.parametrize("location", ["https://evil.example/Flux76HQ/3dprint_pricing/releases/tag/v9.9.9", "javascript:alert(1)",
                                      f"{BASE}/releases/tag/v9.9.9-beta", f"{BASE}/pull/1", ""])
def test_an_unexpected_redirect_is_an_error_not_a_release(owner, location):
    with github(Answer(302, location)):
        body = status(owner)
    assert body["error"] == "unexpected" and body["latest"] == "" and body["available"] is False and body["url"] == ""


@pytest.mark.parametrize("answer", [Answer(302, f"{BASE}/releases"), Answer(404)])
def test_no_release_yet_is_not_an_error(owner, answer):
    with github(answer):
        body = status(owner)
    assert body["error"] is None and body["latest"] == "" and body["available"] is False and body["url"] == ""


@pytest.mark.parametrize("answer, key, detail", [
    (Answer(403), "rate_limit", "HTTP 403"), (Answer(429), "rate_limit", "HTTP 429"), (Answer(500), "unexpected", "HTTP 500"),
    (requests.exceptions.SSLError(), "ssl", "SSLError"), (requests.exceptions.ConnectTimeout(), "timeout", "Timeout"),
    (requests.exceptions.ConnectionError(), "connection", "ConnectionError"), (requests.exceptions.TooManyRedirects(), "unexpected", "TooManyRedirects")])
def test_an_unreachable_github_is_an_error_with_its_cause_not_a_crash(owner, caplog, answer, key, detail):
    with github(answer):
        body = status(owner)
    assert body["error"] == key and body["errorDetail"] == detail and body["available"] is False
    assert any("Update check failed" in r.getMessage() for r in caplog.records)                # the logs say so too


def test_a_bug_in_the_check_never_becomes_an_error_page(owner):
    with github(ValueError("boom")):
        body = status(owner)
    assert body["error"] == "unexpected" and body["errorDetail"] == "ValueError"


# --- being polite -----------------------------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_checker(app, *answers):
    clock = Clock()
    fetch = mock.Mock(side_effect=answers)
    return updates.Checker("0.26.18", fetch=fetch, clock=clock), fetch, clock


def test_the_answer_is_remembered_and_a_page_view_never_calls_github(app):
    checker, fetch, clock = make_checker(app, "0.26.19", "0.26.20")
    with app.app_context():
        assert checker.status()["latest"] == "0.26.19"
        clock.now += updates.SUCCESS_TTL - 1
        assert checker.status()["latest"] == "0.26.19" and fetch.call_count == 1
        clock.now += 2
        assert checker.status()["latest"] == "0.26.20" and fetch.call_count == 2


def test_check_now_skips_the_cache_but_not_a_floor_of_thirty_seconds(app):
    checker, fetch, clock = make_checker(app, "0.26.19", "0.26.20", "0.26.21")
    with app.app_context():
        checker.status()
        for _ in range(5):
            assert checker.status(force=True)["latest"] == "0.26.19"                           # hammering is a cache hit
        assert fetch.call_count == 1
        clock.now += updates.CHECK_NOW_FLOOR
        assert checker.status(force=True)["latest"] == "0.26.20" and fetch.call_count == 2


def test_a_failure_is_retried_after_ten_minutes_and_keeps_the_last_good_answer(app):
    checker, fetch, clock = make_checker(app, "0.26.19", updates.CheckError("rate_limit", "HTTP 403"), "0.26.20")
    with app.app_context():
        checker.status()
        clock.now += updates.SUCCESS_TTL
        failed = checker.status()
        assert failed["error"] == "rate_limit" and failed["latest"] == "0.26.19" and failed["available"] is True      # the announced update stays
        clock.now += updates.FAILURE_TTL - 1
        checker.status()
        assert fetch.call_count == 2
        clock.now += 2
        ok = checker.status()
        assert fetch.call_count == 3 and ok["error"] is None and ok["latest"] == "0.26.20"


def test_switched_off_it_is_reported_as_off_and_calls_nothing(app):
    fetch = mock.Mock()
    off = updates.Checker("0.26.18", enabled=False, fetch=fetch)
    with app.app_context():
        body = off.status()
        assert off.status(force=True) == body
    assert body["enabled"] is False and body["available"] is False and body["error"] is None and body["latest"] == ""
    fetch.assert_not_called()


@pytest.mark.parametrize("value, expected", [("", True), ("true", True), ("TRUE", True), ("1", True), ("yes", True), ("whatever", True),
                                              ("false", False), ("False", False), ("0", False), ("no", False), ("OFF", False), (" off ", False)])
def test_one_variable_switches_it_off(monkeypatch, value, expected):
    monkeypatch.setenv("PRINTPRICING_UPDATE_CHECK", value)
    assert _switch("PRINTPRICING_UPDATE_CHECK") is expected


def test_unset_means_on(monkeypatch):
    monkeypatch.delenv("PRINTPRICING_UPDATE_CHECK", raising=False)
    assert _switch("PRINTPRICING_UPDATE_CHECK") is True


# --- who may ask -------------------------------------------------------------------------------------------------

def test_only_a_signed_in_owner_gets_the_status(client):
    with github(tag("9.9.9")) as get:
        assert client.get("/api/update").status_code == 401
        assert client.post("/api/update/check", json={}, headers=H).status_code == 401
    get.assert_not_called()                                                                  # an anonymous visitor cannot make the server call out


def test_check_now_goes_through_the_same_checker(owner):
    with github(tag("9.9.9")) as get:
        status(owner)
        assert check_now(owner)["latest"] == "9.9.9"
    assert get.call_count == 1                                                               # inside the floor: no second call


# --- documented where it is configured -----------------------------------------------------------------------------

def test_the_variable_is_documented_everywhere_a_variable_is():
    for name in (".env.example", "README.md", "README.nl.md", "docs/handleiding.md"):
        assert "PRINTPRICING_UPDATE_CHECK" in (ROOT / name).read_text(encoding="utf-8"), name


# --- the screens -------------------------------------------------------------------------------------------------

def script(name):
    return (ROOT / "frontend" / "js" / name).read_text(encoding="utf-8")


def test_every_reason_the_server_can_give_has_a_sentence_in_both_languages():
    import json
    for lang in ("nl", "en"):
        texts = json.loads((ROOT / "frontend" / "lang" / f"{lang}.json").read_text(encoding="utf-8"))
        assert all(f"release.err.{key}" in texts for key in updates.ERROR_KEYS), lang
        assert all("{detail}" in texts[f"release.err.{key}"] for key in updates.ERROR_KEYS), lang
    settings = script("settings.js")
    assert all(f"{key}: 'release.err.{key}'" in settings for key in updates.ERROR_KEYS)            # the screen maps each reason to its text


def test_the_banner_is_dismissed_per_version_and_storage_may_be_absent():
    release = script("release.js")
    assert "dismissed() === state.latest" in release and "dismiss(state.latest)" in release          # an even newer version shows it again
    for call in ("localStorage.getItem", "localStorage.setItem"):
        assert "try {" in release.split(call)[0][-120:], call                                              # wrapped in try/catch


def test_the_script_starts_after_sign_in_redraws_on_a_language_change_and_stops_on_sign_out():
    main = script("main.js")
    start = main[main.index("async function start()"):]
    assert main.index("stopRelease()") < main.index("loginView(")                                       # nothing of the owner stays on the login screen
    assert start.index("initRelease()") > start.index("session = { user: status.user")                  # only when signed in
    assert "redrawRelease()" in main[main.index("async function chooseLanguage"):main.index("function route()")]
    assert "releaseAvailable()" in main and "nav-dot" in main                                           # the dot on the entries that lead to Settings


def test_the_settings_page_shows_the_state_the_date_the_notes_and_a_check_now_button():
    settings = script("settings.js")
    for key in ("release.available", "release.uptodate", "release.none", "release.disabled", "release.failed", "release.checked",
                "release.notes", "release.check", "release.how", "release.privacy"):
        assert f"'{key}'" in settings, key
    assert "checkRelease" in settings and "rel: 'noopener noreferrer'" in settings.replace('rel: "noopener noreferrer"', "rel: 'noopener noreferrer'")
