"""Factory settings: everything goes, only with proof it is the owner, and the app can be set up again from the start."""
import os

import psycopg

from tests import printfiles as pf
from tests.test_auth_api import H, onboard, post
from tests.test_backup import fill, upload
from tests.test_password import (  # noqa: F401  (fixtures)
    PASSWORD, _reset_limits, authenticated, code_for, confirmation, enable, owner)

RESET = "/api/system/reset"


def tables(app):
    """Rows per table; the pending challenges are not data."""

    with psycopg.connect(app.config["APP_CONFIG"].database_url) as conn:
        names = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename NOT IN ('schema_migrations', 'webauthn_challenges')")]
        return {name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in names}


def test_a_reset_needs_a_session(client):
    assert post(client, RESET).status_code == 401


def test_a_reset_needs_proof_for_exactly_this_action(owner, app):
    fill(owner)
    before = tables(app)
    assert post(owner, RESET).status_code == 400
    assert post(owner, RESET, {"credential": confirmation(owner, "password-disable")}).status_code == 403     # a confirmation for another action
    assert post(owner, RESET, {"credential": confirmation(owner, "regenerate-recovery")}).status_code == 403
    assert post(owner, RESET, {"current_password": PASSWORD, "code": "000000"}).status_code == 409           # password login is not on
    assert tables(app) == before and authenticated(owner)


def test_a_confirmation_cannot_be_used_twice(owner):
    proof = confirmation(owner, "factory-reset")
    assert post(owner, RESET, {"credential": proof}).status_code == 200
    onboard(owner)
    assert post(owner, RESET, {"credential": proof}).status_code == 403


def test_with_the_passkey_everything_is_gone_and_the_app_is_set_up_again(owner, app):
    fill(owner)
    upload(owner, pf.stl_binary())
    enable(owner)
    owner.post("/api/push/subscribe", json={"endpoint": "https://push.example.test/x", "keys": {"p256dh": "a", "auth": "b"}}, headers=H)
    uploads = app.config["APP_CONFIG"].upload_dir
    assert tables(app)["users"] == 1 and tables(app)["print_files"] == 1

    res = post(owner, RESET, {"credential": confirmation(owner, "factory-reset")})
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
    assert post(owner, RESET, {"credential": confirmation(owner, "factory-reset")}).status_code == 200
    onboard(owner)
    assert make(owner, "/api/projects", sheet_payload())["number"] == first["number"]


def test_with_password_login_on_the_password_and_a_code_do_too(owner, app):
    secret, _ = enable(owner)
    fill(owner)
    assert post(owner, RESET, {"current_password": "wrong wrong wrong wrong", "code": code_for(secret, 1)}).status_code == 401
    assert tables(app)["printers"] == 1
    assert post(owner, RESET, {"current_password": PASSWORD, "code": code_for(secret, 1)}).status_code == 200
    assert {name: n for name, n in tables(app).items() if n} == {}
    assert owner.get("/api/auth/status").get_json()["onboarded"] is False
    assert post(owner, "/api/auth/password/login", {"password": PASSWORD}).status_code == 401      # the password went with it

