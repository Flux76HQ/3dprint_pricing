"""Factory settings: everything goes, only with proof it is the owner, and the app can be set up again from the start."""
import os
from pathlib import Path

import psycopg

from tests import printfiles as pf
from tests.test_auth_api import H, onboard, post
from tests.test_backup import fill, upload
from tests.test_password import (  # noqa: F401  (fixtures)
    PASSWORD, _reset_limits, authenticated, code_for, confirmation, enable, owner)

RESET = "/api/system/reset"
WORD = {"confirm": "RESET"}                                                         # what the owner types; settings.js has the same word


def tables(app):
    """Rows per table; the pending challenges are not data."""

    with psycopg.connect(app.config["APP_CONFIG"].database_url) as conn:
        names = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename NOT IN ('schema_migrations', 'webauthn_challenges')")]
        return {name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in names}


def test_a_reset_needs_the_word_typed_and_wipes_nothing_without_it(owner, app):
    fill(owner)
    before = tables(app)
    proof = confirmation(owner, "factory-reset")
    for body in ({}, {"confirm": ""}, {"confirm": "reset"}, {"confirm": "RESET "}, {"confirm": "yes"}, {"confirm": None}):
        res = post(owner, RESET, {**body, "credential": proof})
        assert res.status_code == 400 and "RESET" in res.get_json()["error"], body
    assert tables(app) == before and authenticated(owner)
    assert post(owner, RESET, {**WORD, "credential": proof}).status_code == 200      # the refused attempts did not spend the confirmation


def test_wrong_attempts_count_against_the_same_lock_as_signing_in(owner, app):
    secret, _ = enable(owner)
    fill(owner)
    for _ in range(5):
        assert post(owner, RESET, {**WORD, "current_password": "wrong wrong wrong wrong", "code": code_for(secret, 1)}).status_code == 401
    locked = post(owner, RESET, {**WORD, "current_password": PASSWORD, "code": code_for(secret, 1)})
    assert locked.status_code == 429                                                  # the right password is refused too: the lock is shared with login
    assert tables(app)["printers"] == 1


def test_a_reset_leaves_a_trace_without_contents(owner, app, caplog):
    fill(owner)
    upload(owner, pf.stl_binary())
    with caplog.at_level("WARNING"):
        assert post(owner, RESET, {**WORD, "credential": confirmation(owner, "factory-reset")}).status_code == 200
    line = next(r.getMessage() for r in caplog.records if "Factory reset" in r.getMessage())
    assert "tables emptied" in line and "1 files removed" in line
    assert "passkey" not in line.lower() and "password" not in line.lower()


def test_the_screen_asks_for_the_same_word():
    from app.system import CONFIRM_WORD
    script = (Path(__file__).resolve().parents[2] / "frontend" / "js" / "settings.js").read_text(encoding="utf-8")
    assert f"const RESET_WORD = '{CONFIRM_WORD}'" in script


def test_a_reset_needs_a_session(client):
    assert post(client, RESET).status_code == 401


def test_a_reset_needs_proof_for_exactly_this_action(owner, app):
    fill(owner)
    before = tables(app)
    assert post(owner, RESET, WORD).status_code == 400
    assert post(owner, RESET, {**WORD, "credential": confirmation(owner, "password-disable")}).status_code == 403     # a confirmation for another action
    assert post(owner, RESET, {**WORD, "credential": confirmation(owner, "regenerate-recovery")}).status_code == 403
    assert post(owner, RESET, {**WORD, "current_password": PASSWORD, "code": "000000"}).status_code == 409           # password login is not on
    assert tables(app) == before and authenticated(owner)


def test_a_confirmation_cannot_be_used_twice(owner):
    proof = confirmation(owner, "factory-reset")
    assert post(owner, RESET, {**WORD, "credential": proof}).status_code == 200
    onboard(owner)
    assert post(owner, RESET, {**WORD, "credential": proof}).status_code == 403


def test_with_the_passkey_everything_is_gone_and_the_app_is_set_up_again(owner, app):
    fill(owner)
    upload(owner, pf.stl_binary())
    enable(owner)
    owner.post("/api/push/subscribe", json={"endpoint": "https://push.example.test/x", "keys": {"p256dh": "a", "auth": "b"}}, headers=H)
    uploads = app.config["APP_CONFIG"].upload_dir
    assert tables(app)["users"] == 1 and tables(app)["print_files"] == 1

    res = post(owner, RESET, {**WORD, "credential": confirmation(owner, "factory-reset")})
    assert res.status_code == 200 and res.get_json() == {"ok": True}

    assert {name: n for name, n in tables(app).items() if n} == {}                  # not a single row, in any table
    assert os.listdir(uploads) == []
    status = owner.get("/api/auth/status").get_json()
    assert status["onboarded"] is False and status["authenticated"] is False and status["password_login"] is False
    assert owner.get("/api/printers").status_code == 401                            # the session cookie was removed

    onboard(owner, name="Nieuw")                                                    # the setup code and a new passkey, as on day one
    assert owner.get("/api/auth/status").get_json()["user"]["display_name"] == "Nieuw"
    assert owner.get("/api/printers").get_json() == [] and owner.get("/api/projects").get_json() == []


def test_numbers_start_over(owner):
    from tests.test_domain_api import make, sheet_payload
    first = make(owner, "/api/projects", sheet_payload())
    assert post(owner, RESET, {**WORD, "credential": confirmation(owner, "factory-reset")}).status_code == 200
    onboard(owner)
    assert make(owner, "/api/projects", sheet_payload())["number"] == first["number"]


def test_with_password_login_on_the_password_and_a_code_do_too(owner, app):
    secret, _ = enable(owner)
    fill(owner)
    assert post(owner, RESET, {**WORD, "current_password": "wrong wrong wrong wrong", "code": code_for(secret, 1)}).status_code == 401
    assert tables(app)["printers"] == 1
    assert post(owner, RESET, {**WORD, "current_password": PASSWORD, "code": code_for(secret, 1)}).status_code == 200
    assert {name: n for name, n in tables(app).items() if n} == {}
    assert owner.get("/api/auth/status").get_json()["onboarded"] is False
    assert post(owner, "/api/auth/password/login", {"password": PASSWORD}).status_code == 401      # the password went with it

