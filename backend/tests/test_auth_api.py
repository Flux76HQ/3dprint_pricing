from app import webauthn as wa
from tests.conftest import ORIGIN, SETUP_CODE
from tests.fake_authenticator import FakeAuthenticator

H = {"Origin": ORIGIN}


def post(client, path, body=None, headers=H):
    return client.post(path, json=body or {}, headers=headers)


def onboard(client, name="Helmer", auth=None):
    auth = auth or FakeAuthenticator()
    options = post(client, "/api/auth/onboarding/options",
                   {"setup_code": SETUP_CODE, "display_name": name}).get_json()
    res = post(client, "/api/auth/onboarding/verify", {"credential": auth.register(options)})
    return auth, res


def login(client, auth):
    options = post(client, "/api/auth/login/options").get_json()
    return post(client, "/api/auth/login/verify", {"credential": auth.assert_(options)})


def test_status_before_onboarding(client):
    body = client.get("/api/auth/status").get_json()
    assert body["onboarded"] is False and body["authenticated"] is False


def test_onboarding_creates_owner_session_and_recovery_codes(client):
    auth, res = onboard(client)
    assert res.status_code == 200
    codes = res.get_json()["recovery_codes"]
    assert len(codes) == 8 and all(len(c) == 14 for c in codes)
    cookie = res.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Strict" in cookie
    status = client.get("/api/auth/status").get_json()
    assert status["onboarded"] and status["authenticated"] and status["user"]["display_name"] == "Helmer"


def test_options_do_not_insist_on_a_discoverable_key_or_on_user_verification(client):
    # A password manager (Enpass...) cannot always verify the user; asking for "required" makes it refuse.
    reg = post(client, "/api/auth/onboarding/options", {"setup_code": SETUP_CODE, "display_name": "Owner"}).get_json()
    assert reg["authenticatorSelection"] == {"residentKey": "preferred", "userVerification": "preferred"}
    assert post(client, "/api/auth/login/options").get_json()["userVerification"] == "preferred"


def test_login_options_name_the_owners_passkeys_so_a_non_discoverable_one_still_signs_in(client):
    assert post(client, "/api/auth/login/options").get_json()["allowCredentials"] == []  # nothing registered yet
    auth, _ = onboard(client)
    client.post("/api/auth/logout", headers=H)
    options = post(client, "/api/auth/login/options").get_json()
    assert options["allowCredentials"] == [{"type": "public-key", "id": wa.b64u_encode(auth.credential_id)}]
    assert post(client, "/api/auth/login/verify", {"credential": auth.assert_(options)}).status_code == 200


def test_stepup_options_let_the_browser_find_the_passkey_and_the_server_checks_whose_it_is(client):
    # A list of credential ids made Enpass skip the passkey it holds; the server still only accepts one of the
    # signed-in user's own credentials (see test_stepup_confirmation_from_someone_elses_key_is_refused).
    onboard(client)
    opts = post(client, "/api/auth/stepup/options", {"action": "regenerate-recovery"}).get_json()
    assert opts["allowCredentials"] == []
    assert opts["userVerification"] == "preferred"


def test_a_password_manager_passkey_can_onboard_log_in_and_confirm(client):
    # Flags 0x41 / 0x01: user present, not verified: what Enpass reports.
    auth = FakeAuthenticator()
    options = post(client, "/api/auth/onboarding/options",
                   {"setup_code": SETUP_CODE, "display_name": "Owner"}).get_json()
    assert post(client, "/api/auth/onboarding/verify",
                {"credential": auth.register(options, flags=0x41)}).status_code == 200
    options = post(client, "/api/auth/login/options").get_json()
    assert post(client, "/api/auth/login/verify",
                {"credential": auth.assert_(options, flags=0x01)}).status_code == 200
    opts = post(client, "/api/auth/stepup/options", {"action": "regenerate-recovery"}).get_json()
    assert post(client, "/api/auth/recovery/regenerate",
                {"credential": auth.assert_(opts, flags=0x01)}).status_code == 200


def test_onboarding_needs_the_setup_code(client):
    res = post(client, "/api/auth/onboarding/options", {"setup_code": "nope", "display_name": "X"})
    assert res.status_code == 403


def test_onboarding_is_closed_once_an_owner_exists(client):
    onboard(client)
    res = post(client, "/api/auth/onboarding/options", {"setup_code": SETUP_CODE, "display_name": "Mallory"})
    assert res.status_code == 409


def test_onboarding_challenge_cannot_be_replayed(client):
    auth = FakeAuthenticator()
    options = post(client, "/api/auth/onboarding/options",
                   {"setup_code": SETUP_CODE, "display_name": "A"}).get_json()
    cred = auth.register(options)
    assert post(client, "/api/auth/onboarding/verify", {"credential": cred}).status_code == 200
    assert post(client, "/api/auth/onboarding/verify", {"credential": cred}).status_code in (400, 409)


def test_login_logout_roundtrip(client):
    auth, _ = onboard(client)
    post(client, "/api/auth/logout")
    assert client.get("/api/auth/status").get_json()["authenticated"] is False
    assert login(client, auth).status_code == 200
    assert client.get("/api/auth/status").get_json()["authenticated"] is True


def test_login_refuses_an_unknown_credential(client):
    onboard(client)
    post(client, "/api/auth/logout")
    assert login(client, FakeAuthenticator()).status_code == 401


def test_setup_code_guessing_is_rate_limited(client):
    codes = [post(client, "/api/auth/onboarding/options", {"setup_code": f"g{i}", "display_name": "X"}).status_code
             for i in range(12)]
    assert codes[:10] == [403] * 10 and codes[10:] == [429, 429]


def test_a_challenge_is_single_use(client):
    auth, _ = onboard(client)
    post(client, "/api/auth/logout")
    options = post(client, "/api/auth/login/options").get_json()
    cred = auth.assert_(options)
    assert post(client, "/api/auth/login/verify", {"credential": cred}).status_code == 200
    assert post(client, "/api/auth/login/verify", {"credential": cred}).status_code == 401


def test_cross_origin_writes_are_refused(client):
    res = client.post("/api/auth/login/options", json={}, headers={"Origin": "https://evil.example"})
    assert res.status_code == 403


def test_recovery_code_logs_in_once_and_normalises_noise(client):
    _, res = onboard(client)
    code = res.get_json()["recovery_codes"][0]
    post(client, "/api/auth/logout")
    messy = " " + code.lower().replace("-", " – ") + " "
    assert post(client, "/api/auth/recovery/redeem", {"code": messy}).status_code == 200
    post(client, "/api/auth/logout")
    again = post(client, "/api/auth/recovery/redeem", {"code": code})
    assert again.status_code == 401
    unknown = post(client, "/api/auth/recovery/redeem", {"code": "AAAA-AAAA-AAAA"})
    assert unknown.get_json() == again.get_json()  # one message for every rejection


def test_recovery_does_not_guess_lookalikes(client):
    from app.auth import RECOVERY_ALPHABET, generate_code, normalise_code
    assert not set("01OI") & set(RECOVERY_ALPHABET)
    for _ in range(50):
        code = generate_code()
        assert normalise_code(code) == code.replace("-", "")
        assert normalise_code(code.lower().replace("-", " ")) == code.replace("-", "")
    assert normalise_code("AB0O") == "AB0O"  # no silent 0->O mapping


def test_add_second_passkey_then_delete_with_step_up(client):
    first, _ = onboard(client)
    second = FakeAuthenticator()
    options = post(client, "/api/auth/credentials/options").get_json()
    assert options["excludeCredentials"]
    res = post(client, "/api/auth/credentials/verify", {"credential": second.register(options), "label": "Laptop"})
    assert res.status_code == 200
    creds = client.get("/api/auth/credentials").get_json()["credentials"]
    assert [c["label"] for c in creds] == ["Eerste passkey", "Laptop"]
    laptop = creds[1]["id"]

    # without a confirmation the delete is refused
    assert client.delete(f"/api/auth/credentials/{laptop}", json={}, headers=H).status_code == 400

    # a confirmation for a different purpose does not count
    wrong = post(client, "/api/auth/stepup/options", {"action": "regenerate-recovery"}).get_json()
    res = client.delete(f"/api/auth/credentials/{laptop}", json={"credential": first.assert_(wrong)}, headers=H)
    assert res.status_code == 403

    opts = post(client, "/api/auth/stepup/options", {"action": "delete-credential", "target": laptop}).get_json()
    res = client.delete(f"/api/auth/credentials/{laptop}", json={"credential": first.assert_(opts)}, headers=H)
    assert res.status_code == 200
    assert len(client.get("/api/auth/credentials").get_json()["credentials"]) == 1


def test_last_passkey_cannot_be_deleted(client):
    first, _ = onboard(client)
    only = client.get("/api/auth/credentials").get_json()["credentials"][0]["id"]
    opts = post(client, "/api/auth/stepup/options", {"action": "delete-credential", "target": only}).get_json()
    res = client.delete(f"/api/auth/credentials/{only}", json={"credential": first.assert_(opts)}, headers=H)
    assert res.status_code == 409


def test_regenerating_recovery_codes_invalidates_the_old_ones(client):
    first, res = onboard(client)
    old = res.get_json()["recovery_codes"][0]
    opts = post(client, "/api/auth/stepup/options", {"action": "regenerate-recovery"}).get_json()
    new = post(client, "/api/auth/recovery/regenerate", {"credential": first.assert_(opts)}).get_json()
    assert len(new["recovery_codes"]) == 8 and old not in new["recovery_codes"]
    post(client, "/api/auth/logout")
    assert post(client, "/api/auth/recovery/redeem", {"code": old}).status_code == 401
    assert post(client, "/api/auth/recovery/redeem", {"code": new["recovery_codes"][0]}).status_code == 200


def test_stepup_confirmation_from_someone_elses_key_is_refused(client):
    first, _ = onboard(client)
    stranger = FakeAuthenticator()
    opts = post(client, "/api/auth/stepup/options", {"action": "regenerate-recovery"}).get_json()
    res = post(client, "/api/auth/recovery/regenerate", {"credential": stranger.assert_(opts)})
    assert res.status_code == 403


def test_unauthenticated_api_is_401_and_tampered_cookie_is_ignored(client):
    assert client.get("/api/printers").status_code == 401
    client.set_cookie("pp_session", "garbage", domain="localhost")
    assert client.get("/api/printers").status_code == 401


# --- onboarding with a password (no passkey can work on the address in use) -----------------------------------

OWNER_PASSWORD = "correct horse battery staple"


def onboard_with_password(client, name="Helmer", password=OWNER_PASSWORD, code=SETUP_CODE):
    return post(client, "/api/auth/onboarding/password", {"setup_code": code, "display_name": name, "password": password})


def test_the_owner_can_start_with_a_password_and_is_signed_in_with_recovery_codes(client):
    res = onboard_with_password(client)
    assert res.status_code == 200 and len(res.get_json()["recovery_codes"]) == 8
    cookie = res.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    status = client.get("/api/auth/status").get_json()
    assert status["onboarded"] and status["authenticated"] and status["password_login"] is True
    assert status["user"]["display_name"] == "Helmer" and status["user"]["role"] == "admin" and status["user"]["is_owner"] is True
    assert status["passkey_login"] is False


def test_the_owner_with_a_password_signs_in_again_with_name_or_without(client):
    onboard_with_password(client)
    post(client, "/api/auth/logout")
    assert post(client, "/api/auth/password/login", {"password": "not the password at all"}).status_code == 401
    assert post(client, "/api/auth/password/login", {"password": OWNER_PASSWORD}).status_code == 200
    assert client.get("/api/auth/status").get_json()["authenticated"] is True


def test_onboarding_with_a_password_needs_the_setup_code_a_name_and_a_good_password(client):
    assert onboard_with_password(client, code="wrong").status_code == 403
    assert onboard_with_password(client, name="  ").status_code == 400
    assert onboard_with_password(client, password="short").status_code == 400
    assert onboard_with_password(client, password="password1234").status_code == 400
    assert onboard_with_password(client, name="Helmer", password="my name is helmer!").status_code == 400    # the policy refers to the name
    assert client.get("/api/auth/status").get_json()["onboarded"] is False                                   # nothing was made


def test_onboarding_is_closed_once_there_is_an_owner_whichever_way_it_was_done(client):
    assert onboard_with_password(client).status_code == 200
    assert onboard_with_password(client, name="Other").status_code == 409
    options = post(client, "/api/auth/onboarding/options", {"setup_code": SETUP_CODE, "display_name": "Other"})
    assert options.status_code == 409


def test_the_setup_code_attempts_are_limited_for_the_password_way_too(client):
    for _ in range(10):
        assert onboard_with_password(client, code="wrong").status_code == 403
    assert onboard_with_password(client, code=SETUP_CODE).status_code == 429


def test_a_password_owner_can_add_a_passkey_and_then_remove_the_password(client):
    onboard_with_password(client)
    auth = FakeAuthenticator()
    options = post(client, "/api/auth/credentials/options").get_json()
    assert post(client, "/api/auth/credentials/verify", {"credential": auth.register(options)}).status_code == 200
    step = post(client, "/api/auth/stepup/options", {"action": "password-disable"}).get_json()
    assert post(client, "/api/auth/password/disable", {"credential": auth.assert_(step)}).status_code == 200
    assert client.get("/api/auth/status").get_json()["password_login"] is False


def test_recovery_codes_can_be_made_again_with_the_password_when_there_is_no_passkey(client):
    old = onboard_with_password(client).get_json()["recovery_codes"]
    assert post(client, "/api/auth/recovery/regenerate", {}).status_code == 400
    assert post(client, "/api/auth/recovery/regenerate", {"current_password": "not the password at all"}).status_code == 401
    new = post(client, "/api/auth/recovery/regenerate", {"current_password": OWNER_PASSWORD})
    assert new.status_code == 200 and not set(new.get_json()["recovery_codes"]) & set(old)


def test_the_last_passkey_may_go_when_there_is_a_password_and_not_otherwise(client):
    auth, _ = onboard(client)
    cred = client.get("/api/auth/credentials").get_json()["credentials"][0]["id"]
    step = post(client, "/api/auth/stepup/options", {"action": "delete-credential", "target": cred}).get_json()
    assert client.delete(f"/api/auth/credentials/{cred}", json={"credential": auth.assert_(step)}, headers=H).status_code == 409
    assert post(client, "/api/auth/password/setup", {"password": OWNER_PASSWORD}).status_code == 200
    step = post(client, "/api/auth/stepup/options", {"action": "delete-credential", "target": cred}).get_json()
    assert client.delete(f"/api/auth/credentials/{cred}", json={"credential": auth.assert_(step)}, headers=H).status_code == 200
