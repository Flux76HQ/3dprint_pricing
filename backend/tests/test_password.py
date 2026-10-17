"""Optional password login with mandatory TOTP: off by default, switched on only with a fresh passkey
confirmation and a confirmed authenticator code, and no session until both factors have passed."""
import base64
from datetime import datetime, timedelta, timezone

import jwt
import psycopg
import pytest

from app import passwords, password_api
from tests.conftest import ORIGIN
from tests.fake_authenticator import FakeAuthenticator
from tests.test_auth_api import H, onboard, post

PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def _reset_limits():
    from app import auth
    password_api.ip_limiter.hits.clear()
    auth.setup_limiter.hits.clear()


@pytest.fixture
def owner(client):
    auth, _ = onboard(client)
    client.passkey = auth
    return client


def confirmation(client, action):
    options = post(client, "/api/auth/stepup/options", {"action": action}).get_json()
    return client.passkey.assert_(options)


def start(client, password=PASSWORD):
    body = {"password": password}
    return post(client, "/api/auth/password/setup/start", body)


def secret_of(started) -> bytes:
    text = started.get_json()["secret"]
    return base64.b32decode(text + "=" * (-len(text) % 8))


def code_for(secret, offset=0):
    return passwords.totp_code(secret, passwords.current_step() + offset)


def enable(client, password=PASSWORD):
    started = start(client, password)
    assert started.status_code == 200, started.get_json()
    secret = secret_of(started)
    confirmed = post(client, "/api/auth/password/setup/confirm", {"code": code_for(secret)})
    assert confirmed.status_code == 200, confirmed.get_json()
    return secret, confirmed.get_json()["backup_codes"]


def signed_out(client):
    post(client, "/api/auth/logout")


def password_login(client, password=PASSWORD):
    return post(client, "/api/auth/password/login", {"password": password})


def full_login(client, secret, offset=0, password=PASSWORD):
    first = password_login(client, password)
    assert first.status_code == 200, first.get_json()
    return post(client, "/api/auth/password/mfa", {"mfa_token": first.get_json()["mfa_token"], "code": code_for(secret, offset)})


def authenticated(client) -> bool:
    return client.get("/api/auth/status").get_json()["authenticated"]


# --- primitives ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("moment, expected", [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
                                              (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")])
def test_totp_matches_the_rfc_6238_test_vectors(moment, expected):
    secret = b"12345678901234567890"
    assert passwords.totp_code(secret, moment // 30, digits=8) == expected
    assert passwords.totp_code(secret, moment // 30) == expected[-6:]


def test_a_code_is_accepted_within_one_step_of_drift_and_only_once():
    secret, now = passwords.new_secret(), 1_800_000_000.0
    step = passwords.current_step(now)
    for offset in (-1, 0, 1):
        assert passwords.verify_totp(secret, passwords.totp_code(secret, step + offset), now=now) == step + offset
    for offset in (-2, 2):
        assert passwords.verify_totp(secret, passwords.totp_code(secret, step + offset), now=now) is None
    code = passwords.totp_code(secret, step)
    assert passwords.verify_totp(secret, code, now=now, last_step=step) is None          # already used
    assert passwords.verify_totp(secret, code, now=now, last_step=step - 1) == step
    for junk in ("", "12345", "1234567", "12345a", "١٢٣٤٥٦", None):
        assert passwords.verify_totp(secret, junk, now=now) is None


@pytest.mark.parametrize("password, fragment", [
    ("short", "minstens 12"), ("x" * 129, "hoogstens 128"), ("password1234", "voorspelbaar"),
    ("aaaaaaaaaaaaaaa", "voorspelbaar"), ("abababababab", "voorspelbaar"), ("Helmer is mijn naam!", "naam"),
])
def test_password_policy_is_about_length_and_obvious_guesses(password, fragment):
    with pytest.raises(ValueError, match=fragment):
        passwords.check_policy(password, "Helmer")


def test_a_passphrase_is_fine_and_so_is_unicode():
    passwords.check_policy("correct horse battery staple", "Helmer")
    passwords.check_policy("zeer lange wachtzin met ünïcödé en 🔐", "Helmer")


def test_hashes_are_argon2id_and_verification_fails_closed():
    stored = passwords.hash_password(PASSWORD)
    assert stored.startswith("$argon2id$") and stored != passwords.hash_password(PASSWORD)    # salted
    assert passwords.verify_password(stored, PASSWORD) and not passwords.verify_password(stored, PASSWORD + "x")
    assert passwords.verify_password("not a hash", PASSWORD) is False


def test_the_secret_is_encrypted_at_rest_and_a_changed_key_fails_closed():
    secret = passwords.new_secret()
    sealed = passwords.seal("k" * 40, secret)
    assert secret not in sealed and passwords.b32(secret).encode() not in sealed
    assert passwords.unseal("k" * 40, sealed) == secret
    assert passwords.unseal("other-secret-" + "x" * 30, sealed) is None


def test_the_mfa_token_is_its_own_kind_of_proof():
    key = "k" * 40
    token = passwords.make_mfa_token(key, "user-1")
    assert passwords.read_mfa_token(key, token) == "user-1"
    assert passwords.read_mfa_token("z" * 40, token) is None
    assert passwords.read_mfa_token(key, token[:-3] + "abc") is None
    assert passwords.read_mfa_token(key, "garbage") is None
    old = datetime.now(timezone.utc) - timedelta(minutes=6)
    assert passwords.read_mfa_token(key, passwords.make_mfa_token(key, "user-1", now=old)) is None      # five minutes only
    session_like = jwt.encode({"sub": "user-1", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, key, algorithm="HS256")
    assert passwords.read_mfa_token(key, session_like) is None                                           # a session is no MFA token


# --- off by default --------------------------------------------------------------------------------------------

def test_password_login_is_off_by_default_and_says_nothing_else(owner):
    signed_out(owner)
    assert owner.get("/api/auth/status").get_json()["password_login"] is False
    refused = password_login(owner)
    assert refused.status_code == 401 and refused.get_json() == {"error": "Inloggen mislukt."}
    assert not authenticated(owner)


def test_management_endpoints_need_a_session(client):
    for path in ("status", "setup/start", "setup/confirm", "setup/cancel", "disable", "change", "backup-codes/regenerate"):
        method = client.get if path == "status" else (lambda p, **kw: client.post(p, json={}, headers=H))
        assert method(f"/api/auth/password/{path}").status_code == 401, path


# --- switching it on ---------------------------------------------------------------------------------------------

def test_turning_it_on_needs_a_session_but_no_passkey_confirmation(owner, client):
    # It has to work on a device that cannot do a passkey ceremony: the session you are in is enough.
    assert start(owner).status_code == 200
    assert post(owner, "/api/auth/stepup/options", {"action": "password-enable"}).status_code == 400   # no such step-up any more
    signed_out(owner)
    assert start(owner).status_code == 401                                                              # but never without a session


def test_turning_it_on_twice_is_refused_while_it_is_on(owner):
    enable(owner)
    assert start(owner).status_code == 409


def test_setup_returns_a_qr_and_the_manual_key_and_stores_nothing_readable(owner, app):
    started = start(owner)
    body = started.get_json()
    assert started.status_code == 200 and body["qr"].startswith("data:image/svg+xml")
    assert body["uri"].startswith("otpauth://totp/") and f"secret={body['secret']}" in body["uri"] and "issuer=3D%20Print%20Pricing" in body["uri"]
    with psycopg.connect(app.config["APP_CONFIG"].database_url) as conn:
        stored_hash, sealed, enabled = conn.execute("SELECT password_hash, totp_secret, enabled FROM password_credentials").fetchone()
    assert stored_hash.startswith("$argon2id$") and PASSWORD not in stored_hash
    assert body["secret"].encode() not in bytes(sealed) and secret_of(started) not in bytes(sealed)
    assert enabled is False


def test_a_weak_password_is_refused_with_a_reason(owner):
    for weak in ("kort", "password1234"):
        res = start(owner, weak)
        assert res.status_code == 400 and res.get_json()["error"]


def test_nothing_works_until_the_second_factor_is_confirmed(owner):
    start(owner)
    assert owner.get("/api/auth/password/status").get_json()["pending"] is True
    signed_out(owner)
    assert owner.get("/api/auth/status").get_json()["password_login"] is False               # pending is not enabled
    assert password_login(owner).status_code == 401


def test_a_wrong_code_does_not_switch_it_on_and_the_right_one_does(owner):
    secret = secret_of(start(owner))
    wrong = post(owner, "/api/auth/password/setup/confirm", {"code": "000000"})
    assert wrong.status_code == 400 and owner.get("/api/auth/password/status").get_json()["enabled"] is False
    done = post(owner, "/api/auth/password/setup/confirm", {"code": code_for(secret)})
    codes = done.get_json()["backup_codes"]
    assert done.status_code == 200 and len(codes) == 8 and len(set(codes)) == 8
    assert owner.get("/api/auth/password/status").get_json() == {"enabled": True, "pending": False, "backup_codes_remaining": 8}
    assert owner.get("/api/auth/status").get_json()["password_login"] is True
    assert start(owner).status_code == 409                                                    # already on
    assert post(owner, "/api/auth/password/setup/confirm", {"code": code_for(secret, 1)}).status_code == 409


def test_cancelling_removes_the_half_finished_setup_but_never_an_enabled_one(owner):
    start(owner)
    post(owner, "/api/auth/password/setup/cancel")
    assert owner.get("/api/auth/password/status").get_json()["pending"] is False
    enable(owner)
    post(owner, "/api/auth/password/setup/cancel")
    assert owner.get("/api/auth/password/status").get_json()["enabled"] is True


# --- logging in --------------------------------------------------------------------------------------------------

def test_password_alone_gives_no_session_only_a_token_for_the_second_step(owner):
    secret, _ = enable(owner)
    signed_out(owner)
    first = password_login(owner)
    assert first.status_code == 200 and first.get_json()["mfa_required"] is True
    assert "Set-Cookie" not in first.headers and not authenticated(owner)
    owner.set_cookie("pp_session", first.get_json()["mfa_token"], domain="localhost")           # the token is no session
    assert not authenticated(owner) and owner.get("/api/printers").status_code == 401
    owner.delete_cookie("pp_session", domain="localhost")
    second = post(owner, "/api/auth/password/mfa", {"mfa_token": first.get_json()["mfa_token"], "code": code_for(secret, 1)})
    assert second.status_code == 200 and "HttpOnly" in second.headers["Set-Cookie"] and authenticated(owner)


def test_wrong_password_and_wrong_code_get_the_same_plain_refusal(owner):
    secret, _ = enable(owner)
    signed_out(owner)
    bad_password = password_login(owner, "not the password at all")
    token = password_login(owner).get_json()["mfa_token"]
    bad_code = post(owner, "/api/auth/password/mfa", {"mfa_token": token, "code": "000000"})
    assert (bad_password.status_code, bad_code.status_code) == (401, 401)
    assert bad_password.get_json() == bad_code.get_json() == {"error": "Inloggen mislukt."}
    assert not authenticated(owner)


def test_a_code_works_once_even_across_logins(owner):
    secret, _ = enable(owner)                                    # enabling already used the current step
    signed_out(owner)
    assert full_login(owner, secret).status_code == 401           # same step as the confirmation: replay
    assert full_login(owner, secret, offset=1).status_code == 200
    signed_out(owner)
    assert full_login(owner, secret, offset=1).status_code == 401  # and that one is spent now
    assert not authenticated(owner)


def test_a_backup_code_logs_in_once(owner):
    secret, codes = enable(owner)
    signed_out(owner)
    token = password_login(owner).get_json()["mfa_token"]
    noisy = " " + codes[0].lower().replace("-", " – ") + " "
    assert post(owner, "/api/auth/password/mfa", {"mfa_token": token, "code": noisy}).status_code == 200
    assert owner.get("/api/auth/password/status").get_json()["backup_codes_remaining"] == 7
    signed_out(owner)
    token = password_login(owner).get_json()["mfa_token"]
    assert post(owner, "/api/auth/password/mfa", {"mfa_token": token, "code": codes[0]}).status_code == 401   # spent
    assert post(owner, "/api/auth/password/mfa", {"mfa_token": token, "code": "AAAA-AAAA-AAAA"}).status_code == 401


def test_a_bad_or_expired_or_foreign_mfa_token_is_refused(owner, app):
    secret, _ = enable(owner)
    signed_out(owner)
    cfg = app.config["APP_CONFIG"]
    with psycopg.connect(cfg.database_url) as conn:
        user_id = conn.execute("SELECT user_id FROM password_credentials").fetchone()[0]
    expired = passwords.make_mfa_token(cfg.session_secret, user_id, now=datetime.now(timezone.utc) - timedelta(minutes=10))
    foreign = passwords.make_mfa_token("y" * 40, user_id)
    for token in ("", "garbage", expired, foreign, None):
        res = post(owner, "/api/auth/password/mfa", {"mfa_token": token, "code": code_for(secret, 1)})
        assert res.status_code == 401 and not authenticated(owner), token


# --- guessing -------------------------------------------------------------------------------------------------------

def test_five_failures_lock_password_login_even_for_the_right_password_and_passkeys_still_work(owner, app):
    secret, _ = enable(owner)
    signed_out(owner)
    for _ in range(5):
        assert password_login(owner, "wrong wrong wrong wrong").status_code == 401
    locked = password_login(owner)                                           # the correct password, but locked
    assert locked.status_code == 429 and "15 minuten" in locked.get_json()["error"] and "passkey" in locked.get_json()["error"]
    assert password_login(owner, "wrong wrong wrong wrong").status_code == 429       # no hint about which was right
    options = post(owner, "/api/auth/login/options").get_json()                      # a passkey is a different door
    assert post(owner, "/api/auth/login/verify", {"credential": owner.passkey.assert_(options)}).status_code == 200


def test_the_lock_ends_resets_after_a_real_login_and_doubles_when_guessing_continues(owner, app):
    secret, _ = enable(owner)
    signed_out(owner)
    url = app.config["APP_CONFIG"].database_url
    def unlock():
        with psycopg.connect(url) as conn:
            conn.execute("UPDATE password_credentials SET locked_until = now() - interval '1 minute'")
    for _ in range(5):
        password_login(owner, "wrong wrong wrong wrong")
    for _ in range(5):                                           # one guess per lock; every five of them the lock doubles
        unlock()
        password_login(owner, "wrong wrong wrong wrong")
    with psycopg.connect(url) as conn:
        minutes = conn.execute("SELECT extract(epoch FROM locked_until - now()) / 60 FROM password_credentials").fetchone()[0]
    assert 28 < minutes <= 30
    unlock()
    assert full_login(owner, secret, offset=1).status_code == 200
    with psycopg.connect(url) as conn:
        assert conn.execute("SELECT failed_count, locked_until FROM password_credentials").fetchone() == (0, None)


def test_wrong_codes_count_towards_the_same_lock(owner):
    secret, _ = enable(owner)
    signed_out(owner)
    token = password_login(owner).get_json()["mfa_token"]
    for _ in range(5):
        assert post(owner, "/api/auth/password/mfa", {"mfa_token": token, "code": "000000"}).status_code == 401
    assert post(owner, "/api/auth/password/mfa", {"mfa_token": token, "code": code_for(secret, 1)}).status_code == 429
    assert password_login(owner).status_code == 429


def test_requests_per_address_are_limited_on_both_steps(owner, monkeypatch):
    enable(owner)
    signed_out(owner)
    monkeypatch.setattr(password_api, "ip_limiter", password_api.RateLimiter(limit=2, window_seconds=900))
    assert password_login(owner).status_code == 200 and password_login(owner).status_code == 200
    assert password_login(owner).status_code == 429
    assert post(owner, "/api/auth/password/mfa", {"mfa_token": "x", "code": "1"}).status_code == 429


def test_a_rotated_session_secret_fails_closed_instead_of_crashing(owner, monkeypatch):
    secret, _ = enable(owner)
    signed_out(owner)
    monkeypatch.setattr(passwords, "unseal", lambda *a, **k: None)          # what a changed SESSION_SECRET looks like
    res = full_login(owner, secret, offset=1)
    assert res.status_code == 401 and res.get_json() == {"error": "Inloggen mislukt."} and not authenticated(owner)


# --- changing and switching off -----------------------------------------------------------------------------------------

def test_changing_the_password_needs_the_passkey_and_keeps_the_second_factor(owner):
    secret, _ = enable(owner)
    new = "another long passphrase here"
    assert post(owner, "/api/auth/password/change", {"password": new}).status_code == 400
    assert post(owner, "/api/auth/password/change", {"password": new, "credential": confirmation(owner, "password-disable")}).status_code == 403
    assert post(owner, "/api/auth/password/change", {"password": "short", "credential": confirmation(owner, "password-change")}).status_code == 400
    assert post(owner, "/api/auth/password/change", {"password": new, "credential": confirmation(owner, "password-change")}).status_code == 200
    signed_out(owner)
    assert password_login(owner, PASSWORD).status_code == 401
    assert full_login(owner, secret, offset=1, password=new).status_code == 200      # still needs the code


def test_switching_it_off_removes_everything_and_needs_the_passkey(owner, app):
    enable(owner)
    assert post(owner, "/api/auth/password/disable", {}).status_code == 400
    assert post(owner, "/api/auth/password/disable", {"credential": confirmation(owner, "password-change")}).status_code == 403
    assert post(owner, "/api/auth/password/disable", {"credential": confirmation(owner, "password-disable")}).status_code == 200
    with psycopg.connect(app.config["APP_CONFIG"].database_url) as conn:
        assert conn.execute("SELECT count(*) FROM password_credentials").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM mfa_backup_codes").fetchone()[0] == 0
    signed_out(owner)
    assert owner.get("/api/auth/status").get_json()["password_login"] is False and password_login(owner).status_code == 401


def test_new_backup_codes_replace_the_old_ones(owner):
    secret, old = enable(owner)
    new = post(owner, "/api/auth/password/backup-codes/regenerate", {"credential": confirmation(owner, "password-backup-codes")}).get_json()["backup_codes"]
    assert len(new) == 8 and not set(new) & set(old)
    signed_out(owner)
    token = password_login(owner).get_json()["mfa_token"]
    assert post(owner, "/api/auth/password/mfa", {"mfa_token": token, "code": old[0]}).status_code == 401
    assert post(owner, "/api/auth/password/mfa", {"mfa_token": token, "code": new[0]}).status_code == 200
    assert post(owner, "/api/auth/password/backup-codes/regenerate", {}).status_code in (400, 401)


def test_two_simultaneous_requests_with_the_same_code_let_only_one_in(owner, app):
    """Both read the row before either wrote: the atomic claim on the step is what stops the second."""
    secret, _ = enable(owner)
    pool = app.extensions["pool"]
    code = code_for(secret, 1)
    with app.app_context(), pool.connection() as conn:
        stale = conn.execute("SELECT user_id, totp_secret, last_totp_step FROM password_credentials").fetchone()
    results = []
    for _ in range(2):                                           # the same stale snapshot, as two racing workers would have
        with app.app_context(), pool.connection() as conn:
            results.append(password_api._check_second_factor(conn, stale, code))
    assert results == [True, False]
