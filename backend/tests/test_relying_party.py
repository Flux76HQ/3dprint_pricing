"""RP_ID and RP_ORIGINS are optional: unset, the app follows the address it is opened on (relying_party.py)."""
import os

import pytest

from app import create_app
from app.config import ConfigError, Config, load_config
from app.db import run_migrations
from tests.conftest import SECRET, SETUP_CODE
from tests.fake_authenticator import FakeAuthenticator

HTTPS = "https://print.example.com"


@pytest.fixture
def open_app(fresh_db, tmp_path):
    """An app with neither RP_ID nor RP_ORIGINS, as a new installation on a home network starts."""
    run_migrations(fresh_db)
    cfg = Config(database_url=fresh_db, session_secret=SECRET, setup_code=SETUP_CODE, rp_id="", rp_name="Test", rp_origins=(),
                 session_hours=24, cookie_secure=False, upload_dir=str(tmp_path / "up"), max_upload_mb=2,
                 static_dir=os.path.join(os.path.dirname(__file__), "static"))
    app = create_app(cfg)
    yield app
    app.extensions["pool"].close()


def call(app, method, path, base, body=None, **headers):
    return getattr(app.test_client(), method)(path, base_url=base, json=body, headers=headers) if body is not None \
        else getattr(app.test_client(), method)(path, base_url=base, headers=headers)


def onboard_with_passkey(app, base):
    host = base.split("://", 1)[1].split(":")[0]
    key = FakeAuthenticator(rp_id=host, origin=base)
    client = app.test_client()
    post = lambda path, body: client.post(path, json=body, base_url=base, headers={"Origin": base})  # noqa: E731
    options = post("/api/auth/onboarding/options", {"setup_code": SETUP_CODE, "display_name": "Owner"}).get_json()
    assert options["rp"]["id"] == host
    res = post("/api/auth/onboarding/verify", {"credential": key.register(options)})
    return key, client, res


def test_the_relying_party_is_the_host_the_app_is_opened_on(open_app):
    status = call(open_app, "get", "/api/auth/status", "https://print.example.com:6443").get_json()
    assert status["rp_id"] == "print.example.com"            # no port
    assert call(open_app, "get", "/api/auth/status", "http://192.168.1.20:6080").get_json()["rp_id"] == "192.168.1.20"
    assert call(open_app, "get", "/api/auth/status", "http://[::1]:6080").get_json()["rp_id"] == "::1"


@pytest.mark.parametrize("base, problem", [
    ("http://192.168.1.20:6080", "passkey.ip_address"),
    ("https://192.168.1.20", "passkey.ip_address"),
    ("http://print.example.com", "passkey.needs_https"),
    ("https://print.example.com", None),
    ("http://localhost:6080", None),                         # browsers treat localhost as a secure context
])
def test_status_says_when_a_passkey_cannot_work(open_app, base, problem):
    assert call(open_app, "get", "/api/auth/status", base).get_json()["passkey_problem"] == problem


def test_a_proxy_that_terminates_https_is_believed(open_app):
    status = call(open_app, "get", "/api/auth/status", "http://app:6080", **{"X-Forwarded-Proto": "https", "X-Forwarded-Host": "print.example.com"})
    assert status.get_json()["rp_id"] == "print.example.com" and status.get_json()["passkey_problem"] is None


def test_a_passkey_can_be_made_and_used_on_the_address_in_use(open_app):
    key, client, res = onboard_with_passkey(open_app, HTTPS)
    assert res.status_code == 200
    cookie = res.headers["Set-Cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    client.post("/api/auth/logout", base_url=HTTPS, headers={"Origin": HTTPS})
    options = client.post("/api/auth/login/options", base_url=HTTPS, json={}, headers={"Origin": HTTPS}).get_json()
    assert options["rpId"] == "print.example.com"
    signed_in = client.post("/api/auth/login/verify", base_url=HTTPS, json={"credential": key.assert_(options)}, headers={"Origin": HTTPS})
    assert signed_in.status_code == 200


def test_a_passkey_made_for_another_address_is_refused(open_app):
    key = FakeAuthenticator(rp_id="print.example.com", origin="https://print.example.com")
    client = open_app.test_client()
    other = "https://evil.example.net"
    options = client.post("/api/auth/onboarding/options", base_url=other, json={"setup_code": SETUP_CODE, "display_name": "Owner"},
                          headers={"Origin": other}).get_json()
    res = client.post("/api/auth/onboarding/verify", base_url=other, json={"credential": key.register(options)}, headers={"Origin": other})
    assert res.status_code == 400


def test_the_cookie_is_secure_only_on_https(open_app):
    client = open_app.test_client()
    plain = "http://192.168.1.20:6080"
    res = client.post("/api/auth/onboarding/password", base_url=plain, headers={"Origin": plain},
                      json={"setup_code": SETUP_CODE, "display_name": "Owner", "password": "a long enough password 1"})
    assert res.status_code == 200 and "Secure" not in res.headers["Set-Cookie"]


def test_a_write_must_come_from_the_page_the_app_served(open_app):
    base = "http://192.168.1.20:6080"
    assert call(open_app, "post", "/api/auth/logout", base, {}, Origin=base).status_code == 200
    assert call(open_app, "post", "/api/auth/logout", base, {}).status_code == 200           # no Origin header: not a browser's cross-site call
    refused = call(open_app, "post", "/api/auth/logout", base, {}, Origin="https://evil.example.net")
    assert refused.status_code == 403
    assert call(open_app, "post", "/api/auth/logout", base, {}, Origin="http://192.168.1.21:6080").status_code == 403
    assert call(open_app, "post", "/api/auth/logout", base, {}, Origin=base.upper()).status_code == 200      # case is not an attack


def test_behind_a_proxy_the_forwarded_host_is_the_page(open_app):
    forwarded = {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "print.example.com"}
    assert call(open_app, "post", "/api/auth/logout", "http://app:6080", {}, Origin=HTTPS, **forwarded).status_code == 200
    assert call(open_app, "post", "/api/auth/logout", "http://app:6080", {}, Origin="http://app:6080", **forwarded).status_code == 403


def test_pinned_origins_still_decide_when_they_are_set(app):
    client = app.test_client()
    assert client.post("/api/auth/logout", json={}, headers={"Origin": "https://localhost:6080"}).status_code == 200
    assert client.post("/api/auth/logout", json={}, headers={"Origin": "https://evil.example.net"}).status_code == 403


def test_the_invitation_link_uses_the_address_in_use(open_app):
    key, client, _ = onboard_with_passkey(open_app, HTTPS)
    res = client.post("/api/users/invites", base_url=HTTPS, headers={"Origin": HTTPS}, json={"name": "Anna"})
    assert res.status_code == 201 and res.get_json()["url"].startswith(f"{HTTPS}/#invite=")


@pytest.fixture
def env(monkeypatch):
    for name in ("RP_ID", "RP_ORIGINS", "VAPID_SUBJECT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("SETUP_CODE", "code")
    return monkeypatch


def test_the_configuration_needs_neither_variable(env):
    cfg = load_config()
    assert cfg.rp_id == "" and cfg.rp_origins == () and cfg.cookie_secure is False
    assert cfg.vapid_subject == "mailto:admin@localhost"      # push needs a contact: set VAPID_SUBJECT (or RP_ID) for the real one


def test_a_pinned_configuration_is_read_as_before(env):
    env.setenv("RP_ID", "Print.Example.com")
    env.setenv("RP_ORIGINS", "https://print.example.com/, https://print2.example.com")
    cfg = load_config()
    assert cfg.rp_id == "print.example.com" and cfg.rp_origins == ("https://print.example.com", "https://print2.example.com")
    assert cfg.cookie_secure is True and cfg.vapid_subject == "mailto:admin@print.example.com"


@pytest.mark.parametrize("value", ["https://print.example.com", "print.example.com:6080", "print.example.com/app"])
def test_rp_id_is_a_bare_domain(env, value):
    env.setenv("RP_ID", value)
    with pytest.raises(ConfigError):
        load_config()
