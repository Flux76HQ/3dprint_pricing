"""Optional password login: off by default; a password alone signs in; with two-step verification (TOTP) switched on there is no
session until both factors have passed; and nothing that weakens it is done without a fresh confirmation."""
import base64
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app import passwords, password_api
from tests.conftest import ORIGIN, connect
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
    """Give the person a password login (no second factor)."""
    return post(client, "/api/auth/password/setup", {"password": password})


def start_totp(client):
    """Begin adding an authenticator app: the secret to put in it."""
    return post(client, "/api/auth/password/totp/start")


def secret_of(started) -> bytes:
    text = started.get_json()["secret"]
    return base64.b32decode(text + "=" * (-len(text) % 8))


def code_for(secret, offset=0):
    return passwords.totp_code(secret, passwords.current_step() + offset)


def enable_password(client, password=PASSWORD):
    done = start(client, password)
    assert done.status_code == 200, done.get_json()


def enable(client, password=PASSWORD):
    """A password and an authenticator app: returns the app's secret and the backup codes."""
    enable_password(client, password)
    started = start_totp(client)
    assert started.status_code == 200, started.get_json()
    secret = secret_of(started)
    confirmed = post(client, "/api/auth/password/totp/confirm", {"code": code_for(secret)})
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
    for path in ("status", "setup", "totp/start", "totp/confirm", "totp/disable", "disable", "change", "backup-codes/regenerate"):
        method = client.get if path == "status" else (lambda p, **kw: client.post(p, json={}, headers=H))
        assert method(f"/api/auth/password/{path}").status_code == 401, path


# --- switching it on ---------------------------------------------------------------------------------------------

def test_turning_it_on_needs_a_session_but_no_passkey_confirmation(owner, client):
    # It has to work on a device that cannot do a passkey ceremony: the session you are in is enough.
    assert start(owner).status_code == 200
    assert post(owner, "/api/auth/stepup/options", {"action": "password-enable"}).status_code == 400   # no such step-up
    signed_out(owner)
    assert start(owner).status_code == 401                                                              # but never without a session


def test_turning_it_on_twice_is_refused_while_it_is_on(owner):
    enable_password(owner)
    assert start(owner).status_code == 409


def test_a_password_is_stored_as_a_hash_with_no_second_factor_to_begin_with(owner, app):
    assert start(owner).status_code == 200
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        stored_hash, secret, pending, enabled = conn.execute(
            "SELECT password_hash, totp_secret, pending_totp_secret, enabled FROM password_credentials").fetchone()
    assert stored_hash.startswith("$argon2id$") and PASSWORD not in stored_hash
    assert secret is None and pending is None and enabled is True
    assert owner.get("/api/auth/password/status").get_json() == {"enabled": True, "totp": False, "backup_codes_remaining": 0, "passkeys": 1}
    assert owner.get("/api/auth/status").get_json()["password_login"] is True


def test_a_weak_password_is_refused_with_a_reason(owner):
    for weak in ("kort", "password1234"):
        res = start(owner, weak)
        assert res.status_code == 400 and res.get_json()["error"]
    assert owner.get("/api/auth/password/status").get_json()["enabled"] is False


def test_the_authenticator_app_needs_a_password_first(owner):
    assert start_totp(owner).status_code == 409
    assert post(owner, "/api/auth/password/totp/confirm", {"code": "000000"}).status_code == 409


def test_totp_setup_returns_a_qr_and_the_manual_key_and_stores_nothing_readable(owner, app):
    enable_password(owner)
    started = start_totp(owner)
    body = started.get_json()
    assert started.status_code == 200 and body["qr"].startswith("data:image/svg+xml")
    assert body["uri"].startswith("otpauth://totp/") and f"secret={body['secret']}" in body["uri"] and "issuer=3D%20Print%20Pricing" in body["uri"]
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        active, sealed = conn.execute("SELECT totp_secret, pending_totp_secret FROM password_credentials").fetchone()
    assert active is None                                                                   # nothing changes until a code is confirmed
    assert body["secret"].encode() not in bytes(sealed) and secret_of(started) not in bytes(sealed)


def test_a_pending_authenticator_app_changes_nothing_about_signing_in(owner):
    enable_password(owner)
    start_totp(owner)
    signed_out(owner)
    first = password_login(owner)
    assert first.status_code == 200 and "mfa_required" not in first.get_json() and authenticated(owner)     # the password still signs in


def test_a_wrong_code_does_not_switch_it_on_and_the_right_one_does(owner):
    enable_password(owner)
    secret = secret_of(start_totp(owner))
    wrong = post(owner, "/api/auth/password/totp/confirm", {"code": "000000"})
    assert wrong.status_code == 400 and owner.get("/api/auth/password/status").get_json()["totp"] is False
    done = post(owner, "/api/auth/password/totp/confirm", {"code": code_for(secret)})
    codes = done.get_json()["backup_codes"]
    assert done.status_code == 200 and len(codes) == 8 and len(set(codes)) == 8
    assert owner.get("/api/auth/password/status").get_json() == {"enabled": True, "totp": True, "backup_codes_remaining": 8, "passkeys": 1}
    assert start_totp(owner).status_code == 409                                             # already on
    assert post(owner, "/api/auth/password/totp/confirm", {"code": code_for(secret, 1)}).status_code == 409


def test_starting_again_replaces_the_pending_secret(owner):
    enable_password(owner)
    first, second = secret_of(start_totp(owner)), secret_of(start_totp(owner))
    assert first != second
    assert post(owner, "/api/auth/password/totp/confirm", {"code": code_for(first)}).status_code == 400
    assert post(owner, "/api/auth/password/totp/confirm", {"code": code_for(second)}).status_code == 200


# --- a password on its own -------------------------------------------------------------------------------------

def test_a_password_alone_signs_in_when_there_is_no_second_factor(owner):
    enable_password(owner)
    signed_out(owner)
    res = password_login(owner)
    assert res.status_code == 200 and res.get_json() == {"ok": True}
    assert "HttpOnly" in res.headers["Set-Cookie"] and authenticated(owner)
    signed_out(owner)
    assert password_login(owner, "not the password at all").status_code == 401 and not authenticated(owner)


def test_a_password_alone_is_still_locked_after_five_failures(owner):
    enable_password(owner)
    signed_out(owner)
    for _ in range(5):
        assert password_login(owner, "wrong wrong wrong wrong").status_code == 401
    assert password_login(owner).status_code == 429 and not authenticated(owner)


def test_the_second_step_refuses_a_token_once_the_second_factor_is_gone(owner):
    secret, _ = enable(owner)
    signed_out(owner)
    token = password_login(owner).get_json()["mfa_token"]
    options = post(owner, "/api/auth/login/options").get_json()
    assert post(owner, "/api/auth/login/verify", {"credential": owner.passkey.assert_(options)}).status_code == 200
    assert post(owner, "/api/auth/password/totp/disable", {"credential": confirmation(owner, "password-totp-disable")}).status_code == 200
    signed_out(owner)
    res = post(owner, "/api/auth/password/mfa", {"mfa_token": token, "code": code_for(secret, 1)})       # a code that has never been used
    assert res.status_code == 401 and not authenticated(owner)


def test_switching_off_the_authenticator_app_keeps_the_password_and_drops_the_backup_codes(owner, app):
    secret, _ = enable(owner)
    assert post(owner, "/api/auth/password/totp/disable", {}).status_code == 400                                         # needs a confirmation
    assert post(owner, "/api/auth/password/totp/disable", {"credential": confirmation(owner, "password-disable")}).status_code == 403   # for this action only
    assert post(owner, "/api/auth/password/totp/disable", {"credential": confirmation(owner, "password-totp-disable")}).status_code == 200
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        assert conn.execute("SELECT totp_secret, pending_totp_secret, enabled FROM password_credentials").fetchone() == (None, None, True)
        assert conn.execute("SELECT count(*) FROM mfa_backup_codes").fetchone()[0] == 0
    signed_out(owner)
    assert password_login(owner).status_code == 200 and authenticated(owner)
    assert post(owner, "/api/auth/password/totp/disable", {"credential": confirmation(owner, "password-totp-disable")}).status_code == 409


def test_new_backup_codes_need_the_authenticator_app(owner):
    enable_password(owner)
    res = post(owner, "/api/auth/password/backup-codes/regenerate", {"credential": confirmation(owner, "password-backup-codes")})
    assert res.status_code == 409


def test_confirming_with_the_password_alone_works_without_a_second_factor_and_not_with_one(owner):
    enable_password(owner)
    new = "een-heel-ander-wachtwoord-77"
    assert post(owner, "/api/auth/password/change", {"current_password": PASSWORD, "password": new}).status_code == 200
    post(owner, "/api/auth/password/totp/confirm", {"code": code_for(secret_of(start_totp(owner)))})
    refused = post(owner, "/api/auth/password/change", {"current_password": new, "password": "nog-een-ander-wachtwoord-88"})
    assert refused.status_code == 401                                                       # now a code is part of it


def test_the_password_cannot_be_switched_off_while_it_is_the_only_way_in(app, client):
    from tests.test_auth_api import SETUP_CODE
    created = post(client, "/api/auth/onboarding/password", {"setup_code": SETUP_CODE, "display_name": "Owner", "password": PASSWORD})
    assert created.status_code == 200
    refused = post(client, "/api/auth/password/disable", {"current_password": PASSWORD})
    assert refused.status_code == 409 and "passkey" in refused.get_json()["error"].lower()
    assert client.get("/api/auth/password/status").get_json()["enabled"] is True


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
    with connect(cfg.database_path) as conn:
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
    url = app.config["APP_CONFIG"].database_path
    def unlock():
        with connect(url) as conn:
            conn.execute("UPDATE password_credentials SET locked_until = strftime('%Y-%m-%d %H:%M:%f', 'now', '-1 minutes')")
    for _ in range(5):
        password_login(owner, "wrong wrong wrong wrong")
    for _ in range(5):                                           # one guess per lock; every five of them the lock doubles
        unlock()
        password_login(owner, "wrong wrong wrong wrong")
    with connect(url) as conn:
        minutes = conn.execute("SELECT (julianday(locked_until) - julianday('now')) * 1440 FROM password_credentials").fetchone()[0]
    assert 28 < minutes <= 30
    unlock()
    assert full_login(owner, secret, offset=1).status_code == 200
    with connect(url) as conn:
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
    with connect(app.config["APP_CONFIG"].database_path) as conn:
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


# --- confirming without a passkey (a device where it cannot be used) ------------------------------------------------

def sure(secret, offset=1, password=PASSWORD):
    """Password plus a fresh code; enabling already used the current step, hence offset 1."""
    return {"current_password": password, "code": code_for(secret, offset)}


def test_it_can_be_turned_off_with_the_password_and_a_code_when_no_passkey_works(owner, app):
    secret, _ = enable(owner)
    assert post(owner, "/api/auth/password/disable", sure(secret)).status_code == 200
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        assert conn.execute("SELECT count(*) FROM password_credentials").fetchone()[0] == 0


def test_a_backup_code_confirms_too_and_is_used_up(owner):
    secret, codes = enable(owner)
    body = {"current_password": PASSWORD, "code": codes[0]}
    assert post(owner, "/api/auth/password/backup-codes/regenerate", body).status_code == 200
    assert post(owner, "/api/auth/password/disable", body).status_code == 401              # replaced anyway; and never twice


def test_changing_the_password_and_new_backup_codes_work_the_same_way(owner):
    secret, old = enable(owner)
    changed = post(owner, "/api/auth/password/change", {**sure(secret), "password": "een-heel-ander-wachtwoord-77"})
    assert changed.status_code == 200
    signed_out(owner)
    assert password_login(owner).status_code == 401 and password_login(owner, "een-heel-ander-wachtwoord-77").status_code == 200
    token = password_login(owner, "een-heel-ander-wachtwoord-77").get_json()["mfa_token"]
    assert post(owner, "/api/auth/password/mfa", {"mfa_token": token, "code": old[0]}).status_code == 200   # signed in by password
    fresh = post(owner, "/api/auth/password/backup-codes/regenerate",                                          # and confirming without a passkey
                 {"current_password": "een-heel-ander-wachtwoord-77", "code": old[1]})
    assert fresh.status_code == 200 and not set(fresh.get_json()["backup_codes"]) & set(old)


def test_a_code_cannot_confirm_twice(owner):
    secret, _ = enable(owner)
    body = sure(secret)
    assert post(owner, "/api/auth/password/backup-codes/regenerate", body).status_code == 200
    assert post(owner, "/api/auth/password/backup-codes/regenerate", body).status_code == 401


def test_a_wrong_password_burns_no_code_and_counts_toward_the_lock(owner, app):
    secret, codes = enable(owner)
    for _ in range(4):
        assert post(owner, "/api/auth/password/disable", {"current_password": "fout-fout-fout-123", "code": codes[0]}).status_code == 401
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        assert conn.execute("SELECT count(*) FROM mfa_backup_codes WHERE used_at IS NOT NULL").fetchone()[0] == 0
    assert post(owner, "/api/auth/password/disable", {"current_password": "fout-fout-fout-123", "code": codes[0]}).status_code == 401
    locked = post(owner, "/api/auth/password/disable", sure(secret))                         # now even the right ones are refused
    assert locked.status_code == 429
    assert owner.get("/api/auth/password/status").get_json()["enabled"] is True


def test_the_right_password_with_a_wrong_code_is_refused_and_counted(owner, app):
    secret, _ = enable(owner)
    assert post(owner, "/api/auth/password/disable", {"current_password": PASSWORD, "code": "000000"}).status_code == 401
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        assert conn.execute("SELECT failed_count FROM password_credentials").fetchone()[0] == 1
    assert owner.get("/api/auth/password/status").get_json()["enabled"] is True


def test_with_neither_confirmation_nothing_happens(owner):
    enable(owner)
    for path in ("disable", "backup-codes/regenerate"):
        assert post(owner, f"/api/auth/password/{path}", {}).status_code == 400
    assert owner.get("/api/auth/password/status").get_json()["enabled"] is True


def test_a_weak_new_password_is_refused_before_a_confirmation_is_spent(owner, app):
    secret, _ = enable(owner)
    refused = post(owner, "/api/auth/password/change", {**sure(secret), "password": "kort"})
    assert refused.status_code == 400
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        assert conn.execute("SELECT failed_count, last_totp_step FROM password_credentials").fetchone()[0] == 0
    assert post(owner, "/api/auth/password/change", {**sure(secret), "password": "een-heel-ander-wachtwoord-77"}).status_code == 200


def test_confirming_with_a_password_needs_a_session_and_the_ip_limit_applies(client, owner):
    secret, _ = enable(owner)
    for _ in range(20):
        owner.post("/api/auth/password/disable", json={"current_password": "x", "code": "000000"}, headers=H)
    assert post(owner, "/api/auth/password/disable", sure(secret)).status_code in (429,)
    signed_out(owner)
    assert post(owner, "/api/auth/password/disable", sure(secret)).status_code == 401
