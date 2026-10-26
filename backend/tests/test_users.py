"""User management: an administrator invites people with a link, the guest chooses their own passkey or password, a regular user can
be promoted to administrator, and the owner is out of reach. Also what only an administrator may do, and what is shared."""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import jwt
import psycopg
import pytest

from app import access, invites, password_api, users
from tests.conftest import ORIGIN, SECRET
from tests.fake_authenticator import FakeAuthenticator
from tests.test_auth_api import H, onboard, post
from tests.test_orders import new_order
from tests.test_password import PASSWORD, code_for, secret_of


@pytest.fixture(autouse=True)
def _reset_limits():
    invites.limiter.hits.clear()
    password_api.ip_limiter.hits.clear()


@pytest.fixture
def owner(client):
    auth, _ = onboard(client, "Helmer")
    client.passkey = auth
    return client


def put(client, path, body=None):
    return client.put(path, json=body or {}, headers=H)


def delete(client, path, body=None):
    return client.delete(path, json=body or {}, headers=H)


def as_guest(token):
    return {**H, "X-Invite-Token": token}


def invite(admin, name=None):
    res = post(admin, "/api/users/invites", {"name": name} if name else {})
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def accept(app, token, name="Anna"):
    """A guest opens the link and chooses a passkey. Returns their client and passkey."""
    guest, auth = app.test_client(), FakeAuthenticator()
    opts = guest.post("/api/invites/passkey/options", json={"name": name}, headers=as_guest(token))
    assert opts.status_code == 200, opts.get_json()
    done = guest.post("/api/invites/passkey/verify", json={"credential": auth.register(opts.get_json())}, headers=as_guest(token))
    assert done.status_code == 200, done.get_json()
    return guest, auth


def join_with_passkey(app, admin, name="Anna", *, invited_as=None, role=None):
    """A new person through an invitation; returns their client (with `.passkey` and `.user_id`). `role='admin'` also promotes them."""
    guest, auth = accept(app, invite(admin, invited_as)["token"], name)
    guest.passkey = auth
    guest.user_id = guest.get("/api/auth/status").get_json()["user"]["id"]
    if role == "admin":
        promote(admin, guest.user_id)
    return guest


def proof(client, action, target):
    options = post(client, "/api/auth/stepup/options", {"action": action, "target": target}).get_json()
    return {"credential": client.passkey.assert_(options)}


def promote(admin, user_id):
    res = put(admin, f"/api/users/{user_id}/role", {"role": "admin", **proof(admin, "user-promote", user_id)})
    assert res.status_code == 200, res.get_json()


def sql(app, query, params=()):
    with app.extensions["pool"].connection() as conn:
        cursor = conn.execute(query, params)
        return cursor.fetchall() if cursor.description else []


def user_list(admin):
    return {u["name"]: u for u in admin.get("/api/users").get_json()["users"]}


# --- the first person is the owner, an administrator ---------------------------------------------------------

def test_the_person_who_sets_the_app_up_is_the_owner_and_an_administrator(owner):
    me = owner.get("/api/auth/status").get_json()["user"]
    assert me["role"] == "admin" and me["is_owner"] is True
    assert user_list(owner)["Helmer"]["is_owner"] is True


def test_status_asks_for_a_name_at_the_password_login_only_when_there_are_several_people(app, owner):
    assert owner.get("/api/auth/status").get_json()["login_name_required"] is False
    join_with_passkey(app, owner)
    assert owner.get("/api/auth/status").get_json()["login_name_required"] is True


# --- who may call what -----------------------------------------------------------------------------------------

ADMIN_ONLY_CALLS = [
    ("GET", "/api/users"), ("POST", "/api/users/invites"), ("DELETE", f"/api/users/{uuid.uuid4()}"),
    ("POST", f"/api/users/{uuid.uuid4()}/reset"), ("PUT", f"/api/users/{uuid.uuid4()}/role"),
    ("DELETE", f"/api/users/invites/{uuid.uuid4()}"),
    ("GET", "/api/backup"), ("POST", "/api/backup/stage"), ("POST", "/api/backup/restore"), ("GET", "/api/backup/jobs/latest"),
    ("POST", "/api/system/reset"),
    ("GET", "/api/update"), ("POST", "/api/update/check"),
    ("GET", "/api/ai-images/settings"), ("PUT", "/api/ai-images/settings"), ("DELETE", "/api/ai-images/key"),
    ("POST", "/api/ai-images/test"), ("GET", "/api/ai-images/log"),
    ("POST", "/api/spoolman/sync"), ("POST", "/api/spoolman/push-library"), ("POST", "/api/spoolman/push-rolls"), ("POST", "/api/invoice-template"), ("DELETE", "/api/invoice-template"),
    ("POST", "/api/invoice-logo"), ("DELETE", "/api/invoice-logo"),
]


@pytest.mark.parametrize("method,path", ADMIN_ONLY_CALLS)
def test_a_regular_user_is_refused_what_is_for_administrators_and_nobody_at_all_is_not_let_in(app, owner, method, path):
    member = join_with_passkey(app, owner)
    assert member.open(path, method=method, json={}, headers=H).status_code == 403
    assert app.test_client().open(path, method=method, json={}, headers=H).status_code == 401


@pytest.mark.parametrize("path", ["/api/users", "/api/backup", "/api/update", "/api/ai-images/settings"])
def test_an_administrator_is_let_through_to_the_same_routes(owner, path):
    assert owner.get(path).status_code not in (401, 403)


def test_a_regular_user_does_the_everyday_work_and_can_read_what_the_screens_need(app, owner):
    member = join_with_passkey(app, owner)
    for path in ("/api/projects", "/api/customers", "/api/orders", "/api/spools", "/api/printers", "/api/filament-library/export",
                 "/api/invoice-logo", "/api/invoice-template", "/api/preferences"):
        assert member.get(path).status_code == 200, path
    assert post(member, "/api/customers", {"name": "Kees"}).status_code == 201
    assert member.post("/api/calculate", json={"data": {}}, headers=H).status_code != 403


def test_every_route_under_an_administrator_prefix_is_covered_by_the_list(app):
    """A new route in one of these files must not be reachable by a regular user because someone forgot a decorator."""
    for rule in app.url_map.iter_rules():
        for prefix, everything in access.ADMIN_ONLY:
            if rule.rule == prefix or rule.rule.startswith(prefix + "/"):
                guarded = (rule.methods - {"HEAD", "OPTIONS"}) - (set() if everything else {"GET"})      # a prefix that guards writes only
                assert all(access.is_admin_only(rule.rule, m) for m in guarded), rule


def test_the_list_follows_the_path_not_the_screen(app, owner):
    member = join_with_passkey(app, owner)
    assert member.get("/api/users/../users").status_code in (403, 404)
    assert access.is_admin_only("/api/users", "GET") and not access.is_admin_only("/api/usersX", "GET")
    assert not access.is_admin_only("/api/invoice-logo", "GET") and access.is_admin_only("/api/invoice-logo", "DELETE")


# --- an invitation -----------------------------------------------------------------------------------------------

def test_an_invitation_is_a_link_with_the_token_in_the_fragment_and_only_its_hash_is_kept(app, owner):
    made = invite(owner, "Anna")
    assert made["url"] == f"{ORIGIN}/#invite={made['token']}" and len(made["token"]) >= 40
    (row,) = sql(app, "SELECT token_hash, display_name, kind FROM invitations")
    assert bytes(row["token_hash"]) == hashlib.sha256(made["token"].encode()).digest()
    assert row["display_name"] == "Anna" and row["kind"] == "new"
    assert made["token"].encode() not in bytes(row["token_hash"])
    assert made["token"] not in str(sql(app, "SELECT * FROM invitations"))
    expires = datetime.fromisoformat(made["expires_at"])
    assert timedelta(days=6, hours=23) < expires - datetime.now(timezone.utc) <= timedelta(days=7)


def test_the_link_is_built_from_a_configured_address_not_from_the_requests_own_host(app, owner):
    spoofed = {"X-Forwarded-Host": "10.0.0.5:8000", "X-Forwarded-Proto": "http"}
    assert owner.post("/api/users/invites", json={}, headers={"Origin": ORIGIN, **spoofed}).get_json()["url"].startswith(ORIGIN + "/#invite=")
    assert owner.post("/api/users/invites", json={}, headers=spoofed).get_json()["url"].startswith(ORIGIN + "/#invite=")      # no Origin header at all
    # An origin that is not one of the configured ones is refused for every state-changing call, so it can never end up in a link.
    assert owner.post("/api/users/invites", json={}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_the_guest_sees_only_what_the_page_needs(app, owner):
    made = invite(owner, "Anna")
    info = app.test_client().get("/api/invites/info", headers=as_guest(made["token"])).get_json()
    assert info["kind"] == "new" and info["name"] == "Anna" and info["invited_by"] == "Helmer"
    assert set(info) == {"kind", "name", "invited_by", "expires_at"}


def test_an_unknown_expired_used_or_missing_token_all_get_the_same_answer(app, owner):
    guest = app.test_client()
    expired, used = invite(owner), invite(owner)
    sql(app, "UPDATE invitations SET expires_at = now() - interval '1 minute' WHERE token_hash = %s", (hashlib.sha256(expired["token"].encode()).digest(),))
    accept(app, used["token"])
    answers = {guest.get("/api/invites/info", headers=h).get_data(as_text=True)
               for h in (as_guest("x" * 43), as_guest(expired["token"]), as_guest(used["token"]), {}, as_guest(""), as_guest("short"))}
    assert len(answers) == 1 and guest.get("/api/invites/info", headers=as_guest("x" * 43)).status_code == 404
    for path in ("/api/invites/passkey/options", "/api/invites/password/start", "/api/invites/passkey/verify", "/api/invites/password/confirm"):
        assert guest.post(path, json={"name": "Z", "password": PASSWORD, "credential": {}, "code": "1"}, headers=as_guest(expired["token"])).status_code == 404, path


def test_an_invitation_is_not_a_session(app, owner):
    made = invite(owner)
    assert app.test_client().get("/api/projects", headers=as_guest(made["token"])).status_code == 401


def test_making_a_link_is_for_an_administrator_and_a_taken_or_reserved_name_is_refused(app, owner):
    invite(owner, "Anna")
    assert post(owner, "/api/users/invites", {"name": "anna"}).status_code == 409           # reserved by the open invitation
    assert post(owner, "/api/users/invites", {"name": "HELMER"}).status_code == 409         # a person who exists, in any case
    assert post(owner, "/api/users/invites", {"name": "x" * 61}).status_code == 400
    assert post(owner, "/api/users/invites", {"name": "bad\x07name"}).status_code == 400


def test_the_caps_count_open_invitations_as_people(app, owner, monkeypatch):
    monkeypatch.setattr(users, "MAX_USERS", 3)
    invite(owner)
    invite(owner)                                   # the owner, plus two open invitations: full
    assert post(owner, "/api/users/invites").status_code == 409
    monkeypatch.setattr(users, "MAX_USERS", 50)
    monkeypatch.setattr(users, "MAX_INVITES", 2)
    assert post(owner, "/api/users/invites").status_code == 409


def test_expired_invitations_are_purged_when_a_new_one_is_made_and_are_not_listed(app, owner):
    old = invite(owner)
    sql(app, "UPDATE invitations SET expires_at = now() - interval '1 second'")
    assert owner.get("/api/users").get_json()["invitations"] == []
    invite(owner)
    assert len(sql(app, "SELECT 1 FROM invitations")) == 1
    assert old["id"] not in [str(r["id"]) for r in sql(app, "SELECT id FROM invitations")]


def test_a_revoked_invitation_no_longer_works_and_the_list_shows_who_made_it(app, owner):
    made = invite(owner, "Anna")
    (listed,) = owner.get("/api/users").get_json()["invitations"]
    assert listed["name"] == "Anna" and listed["invited_by"] == "Helmer" and listed["kind"] == "new"
    assert "token" not in listed and "url" not in listed                            # shown once, when it was made
    assert delete(owner, f"/api/users/invites/{made['id']}").status_code == 200
    assert app.test_client().get("/api/invites/info", headers=as_guest(made["token"])).status_code == 404
    assert delete(owner, f"/api/users/invites/{made['id']}").status_code == 404


# --- joining with a passkey ----------------------------------------------------------------------------------------

def test_a_guest_joins_with_a_passkey_as_a_regular_user_and_the_link_works_once(app, owner):
    made = invite(owner, "Anna")
    guest, auth = app.test_client(), FakeAuthenticator()
    opts = guest.post("/api/invites/passkey/options", json={"name": "Anna Jansen"}, headers=as_guest(made["token"])).get_json()
    done = guest.post("/api/invites/passkey/verify", json={"credential": auth.register(opts)}, headers=as_guest(made["token"]))
    assert done.status_code == 200 and len(done.get_json()["recovery_codes"]) == 8
    assert "HttpOnly" in done.headers["Set-Cookie"]
    me = guest.get("/api/auth/status").get_json()["user"]
    assert me["display_name"] == "Anna Jansen" and me["role"] == "user" and me["is_owner"] is False
    assert sql(app, "SELECT count(*) AS n FROM invitations")[0]["n"] == 0
    again = guest.post("/api/invites/passkey/options", json={"name": "Anna"}, headers=as_guest(made["token"]))
    assert again.status_code == 404
    guest.post("/api/auth/logout", headers=H)
    options = post(guest, "/api/auth/login/options").get_json()
    assert post(guest, "/api/auth/login/verify", {"credential": auth.assert_(options)}).status_code == 200


def test_the_administrator_sees_how_each_person_signs_in_and_nothing_secret(app, owner):
    join_with_passkey(app, owner, "Anna")
    join_with_password(app, owner, "Bea")
    listed = owner.get("/api/users").get_json()["users"]
    assert [u["name"] for u in listed] == ["Helmer", "Anna", "Bea"]                      # the owner first, then in order of joining
    assert {u["name"]: (u["passkeys"], u["password"]) for u in listed} == {"Helmer": (1, False), "Anna": (1, False), "Bea": (0, True)}
    assert all(set(u) == {"id", "name", "role", "is_owner", "you", "created_at", "passkeys", "password"} for u in listed)
    assert [u["you"] for u in listed] == [True, False, False]


def test_a_name_taken_in_the_meantime_is_refused_before_a_passkey_is_made(app, owner):
    first, second = invite(owner), invite(owner)
    g1, g2 = app.test_client(), app.test_client()
    o1 = g1.post("/api/invites/passkey/options", json={"name": "Anna"}, headers=as_guest(first["token"])).get_json()
    g1.post("/api/invites/passkey/verify", json={"credential": FakeAuthenticator().register(o1)}, headers=as_guest(first["token"]))
    refused = g2.post("/api/invites/passkey/options", json={"name": "ANNA"}, headers=as_guest(second["token"]))
    assert refused.status_code == 409 and sql(app, "SELECT count(*) AS n FROM users")[0]["n"] == 2


def test_two_invitations_finishing_with_the_same_name_make_one_person_and_a_conflict_not_an_error(app, owner):
    tries = []
    for made in (invite(owner), invite(owner), invite(owner)):
        guest, auth = app.test_client(), FakeAuthenticator()
        opts = guest.post("/api/invites/passkey/options", json={"name": "Anna"}, headers=as_guest(made["token"])).get_json()
        tries.append((guest, {"credential": auth.register(opts)}, as_guest(made["token"])))
    (g1, b1, h1), (g2, b2, h2), (g3, b3, h3) = tries
    assert g1.post("/api/invites/passkey/verify", json=b1, headers=h1).status_code == 200
    assert g2.post("/api/invites/passkey/verify", json=b2, headers=h2).status_code == 409           # the check
    with mock.patch("app.invites.name_taken", return_value=False):                                   # and the database's own, were it skipped
        assert g3.post("/api/invites/passkey/verify", json=b3, headers=h3).status_code == 409
    assert sql(app, "SELECT count(*) AS n FROM users")[0]["n"] == 2
    assert sql(app, "SELECT count(*) AS n FROM invitations")[0]["n"] == 2          # the two others can try again with another name


def test_a_challenge_made_for_one_link_does_not_finish_another(app, owner):
    first, second = invite(owner), invite(owner)
    g1 = app.test_client()
    opts = g1.post("/api/invites/passkey/options", json={"name": "Anna"}, headers=as_guest(first["token"])).get_json()
    wrong = g1.post("/api/invites/passkey/verify", json={"credential": FakeAuthenticator().register(opts)}, headers=as_guest(second["token"]))
    assert wrong.status_code == 400 and sql(app, "SELECT count(*) AS n FROM users")[0]["n"] == 1


def test_a_passkey_from_another_origin_is_refused_and_the_invitation_survives(app, owner):
    made = invite(owner)
    guest, auth = app.test_client(), FakeAuthenticator()
    opts = guest.post("/api/invites/passkey/options", json={"name": "Anna"}, headers=as_guest(made["token"])).get_json()
    bad = guest.post("/api/invites/passkey/verify", json={"credential": auth.register(opts, origin="https://evil.example")}, headers=as_guest(made["token"]))
    assert bad.status_code == 400
    assert sql(app, "SELECT count(*) AS n FROM invitations")[0]["n"] == 1 and sql(app, "SELECT count(*) AS n FROM users")[0]["n"] == 1


# --- joining with a password ---------------------------------------------------------------------------------------

def join_with_password(app, admin, name="Bea", password=PASSWORD):
    made = invite(admin)
    guest = app.test_client()
    started = guest.post("/api/invites/password/start", json={"name": name, "password": password}, headers=as_guest(made["token"]))
    assert started.status_code == 200, started.get_json()
    secret = secret_of(started)
    done = guest.post("/api/invites/password/confirm", json={"code": code_for(secret)}, headers=as_guest(made["token"]))
    assert done.status_code == 200, done.get_json()
    return guest, secret, done.get_json()["backup_codes"], made


def test_a_guest_can_choose_a_password_with_two_step_verification_and_is_signed_in(app, owner):
    guest, secret, codes, made = join_with_password(app, owner)
    assert len(codes) == 8
    me = guest.get("/api/auth/status").get_json()["user"]
    assert me["display_name"] == "Bea" and me["role"] == "user"
    assert app.test_client().get("/api/invites/info", headers=as_guest(made["token"])).status_code == 404
    listed = user_list(owner)["Bea"]
    assert listed["password"] is True and listed["passkeys"] == 0


def test_nothing_exists_until_the_authenticator_code_has_been_confirmed(app, owner):
    made = invite(owner)
    guest = app.test_client()
    guest.post("/api/invites/password/start", json={"name": "Bea", "password": PASSWORD}, headers=as_guest(made["token"]))
    assert sql(app, "SELECT count(*) AS n FROM users")[0]["n"] == 1                       # still only the owner
    wrong = guest.post("/api/invites/password/confirm", json={"code": "000000"}, headers=as_guest(made["token"]))
    assert wrong.status_code == 400 and sql(app, "SELECT count(*) AS n FROM users")[0]["n"] == 1
    assert app.test_client().post("/api/invites/password/confirm", json={"code": "123456"}, headers=as_guest(invite(owner)["token"])).status_code == 409


def test_a_weak_password_is_refused_and_nothing_is_kept(app, owner):
    made = invite(owner)
    res = app.test_client().post("/api/invites/password/start", json={"name": "Bea", "password": "short"}, headers=as_guest(made["token"]))
    assert res.status_code == 400
    assert sql(app, "SELECT pending_password_hash FROM invitations")[0]["pending_password_hash"] is None
    named = app.test_client().post("/api/invites/password/start", json={"name": "Beatrice", "password": "xxbeatricexx-1234"}, headers=as_guest(made["token"]))
    assert named.status_code == 400                                                       # the policy refers to the name


def test_with_several_people_the_password_login_needs_the_name_and_each_person_has_their_own(app, owner):
    guest, secret, _, _ = join_with_password(app, owner, "Bea")
    other = app.test_client()
    first = post(other, "/api/auth/password/login", {"name": "bea", "password": PASSWORD})          # any case
    assert first.status_code == 200 and first.get_json()["mfa_required"]
    done = post(other, "/api/auth/password/mfa", {"mfa_token": first.get_json()["mfa_token"], "code": code_for(secret, 1)})
    assert done.status_code == 200 and other.get("/api/auth/status").get_json()["user"]["display_name"] == "Bea"
    for body in ({"password": PASSWORD}, {"name": "Nobody", "password": PASSWORD}, {"name": "Helmer", "password": PASSWORD},
                 {"name": "Bea", "password": "wrong password here"}):
        assert post(app.test_client(), "/api/auth/password/login", body).status_code == 401, body


def test_the_password_login_without_a_name_still_works_while_there_is_only_one_person(app, owner):
    from tests.test_password import enable
    enable(owner)
    other = app.test_client()
    assert post(other, "/api/auth/password/login", {"password": PASSWORD}).status_code == 200
    join_with_passkey(app, owner)
    assert post(app.test_client(), "/api/auth/password/login", {"password": PASSWORD}).status_code == 401


def test_each_persons_password_lock_is_their_own(app, owner):
    guest, _, _, _ = join_with_password(app, owner, "Bea")
    for _ in range(5):
        post(app.test_client(), "/api/auth/password/login", {"name": "Bea", "password": "wrong password here"})
        password_api.ip_limiter.hits.clear()
    locked = post(app.test_client(), "/api/auth/password/login", {"name": "Bea", "password": PASSWORD})
    assert locked.status_code == 429
    assert sql(app, "SELECT count(*) AS n FROM password_credentials WHERE locked_until IS NOT NULL")[0]["n"] == 1


# --- promoting and demoting ----------------------------------------------------------------------------------------

def test_an_administrator_can_promote_a_regular_user_with_a_fresh_confirmation(app, owner):
    anna = join_with_passkey(app, owner)
    assert anna.get("/api/users").status_code == 403
    assert put(owner, f"/api/users/{anna.user_id}/role", {"role": "admin"}).status_code == 400           # no confirmation
    res = put(owner, f"/api/users/{anna.user_id}/role", {"role": "admin", **proof(owner, "user-promote", anna.user_id)})
    assert res.status_code == 200 and res.get_json()["role"] == "admin"
    # The session she already has gains the rights at once: the role is read on every request.
    assert anna.get("/api/users").status_code == 200
    assert anna.get("/api/auth/status").get_json()["user"]["role"] == "admin"
    assert user_list(owner)["Anna"]["role"] == "admin" and user_list(owner)["Anna"]["is_owner"] is False


def test_the_confirmation_is_for_that_person_and_for_that_action(app, owner):
    anna, bea = join_with_passkey(app, owner, "Anna"), join_with_passkey(app, owner, "Bea")
    for_anna = proof(owner, "user-promote", anna.user_id)
    assert put(owner, f"/api/users/{bea.user_id}/role", {"role": "admin", **for_anna}).status_code == 403
    other_action = proof(owner, "user-reset", bea.user_id)
    assert put(owner, f"/api/users/{bea.user_id}/role", {"role": "admin", **other_action}).status_code == 403
    assert user_list(owner)["Bea"]["role"] == "user"
    assert put(owner, f"/api/users/{anna.user_id}/role", {"role": "admin", **for_anna}).status_code == 200
    assert put(owner, f"/api/users/{anna.user_id}/role", {"role": "admin", **for_anna}).status_code == 200        # already one: nothing to confirm


def test_the_confirmation_may_also_be_the_password_with_a_code(app, owner):
    from tests.test_password import enable
    secret, _ = enable(owner)
    anna = join_with_passkey(app, owner)
    body = {"role": "admin", "current_password": PASSWORD, "code": code_for(secret, 1)}
    assert put(owner, f"/api/users/{anna.user_id}/role", body).status_code == 200


def test_a_promoted_administrator_can_do_everything_an_administrator_can_but_not_touch_the_owner(app, owner):
    anna = join_with_passkey(app, owner, "Anna", role="admin")
    bea = join_with_passkey(app, anna, "Bea")                                         # she invites
    assert bea.get("/api/auth/status").get_json()["user"]["role"] == "user"
    promote(anna, bea.user_id)
    owner_id = user_list(anna)["Helmer"]["id"]
    assert post(anna, f"/api/users/{owner_id}/reset").status_code == 404
    assert delete(anna, f"/api/users/{owner_id}").status_code == 400
    assert put(anna, f"/api/users/{owner_id}/role", {"role": "user"}).status_code == 400
    assert owner.get("/api/auth/status").get_json()["user"]["role"] == "admin"
    assert anna.get("/api/backup").status_code == 200 and anna.get("/api/update").status_code == 200


def test_demoting_takes_the_rights_away_at_once_and_needs_no_confirmation(app, owner):
    anna = join_with_passkey(app, owner, role="admin")
    assert anna.get("/api/users").status_code == 200
    assert put(owner, f"/api/users/{anna.user_id}/role", {"role": "user"}).status_code == 200
    assert anna.get("/api/users").status_code == 403 and anna.get("/api/projects").status_code == 200


def test_roles_cannot_be_changed_by_a_regular_user_or_for_yourself_or_to_something_else(app, owner):
    anna, bea = join_with_passkey(app, owner, "Anna"), join_with_passkey(app, owner, "Bea")
    assert put(anna, f"/api/users/{anna.user_id}/role", {"role": "admin"}).status_code == 403
    assert put(anna, f"/api/users/{bea.user_id}/role", {"role": "admin"}).status_code == 403
    owner_id = user_list(owner)["Helmer"]["id"]
    assert put(owner, f"/api/users/{owner_id}/role", {"role": "user"}).status_code == 400
    assert put(owner, f"/api/users/{anna.user_id}/role", {"role": "owner"}).status_code == 400
    assert put(owner, f"/api/users/{uuid.uuid4()}/role", {"role": "user"}).status_code == 404
    promote(owner, anna.user_id)
    assert put(anna, f"/api/users/{anna.user_id}/role", {"role": "user"}).status_code == 400            # not even yourself
    assert sql(app, "SELECT count(*) AS n FROM users WHERE role = 'admin'")[0]["n"] == 2


def test_the_database_itself_keeps_the_owner_an_administrator_and_there_is_only_one(app, owner):
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(app, "UPDATE users SET role = 'user' WHERE is_owner")
    with pytest.raises(psycopg.errors.UniqueViolation):
        sql(app, "INSERT INTO users (display_name, role, is_owner) VALUES ('Second', 'admin', true)")


# --- reset: back in without a password nobody knows ---------------------------------------------------------------------

def test_a_reset_changes_nothing_until_the_guest_has_finished(app, owner):
    anna = join_with_passkey(app, owner)
    made = post(owner, f"/api/users/{anna.user_id}/reset").get_json()
    guest = app.test_client()
    info = guest.get("/api/invites/info", headers=as_guest(made["token"])).get_json()
    assert info["kind"] == "reset" and info["name"] == "Anna"
    guest.post("/api/invites/passkey/options", json={"name": "Whoever"}, headers=as_guest(made["token"]))      # opened, then walked away
    assert anna.get("/api/projects").status_code == 200                                                       # her session and
    options = post(app.test_client(), "/api/auth/login/options").get_json()
    assert post(app.test_client(), "/api/auth/login/verify", {"credential": anna.passkey.assert_(options)}).status_code == 200      # passkey work


def test_a_reset_replaces_every_old_way_in_and_signs_the_old_sessions_out(app, owner):
    anna = join_with_passkey(app, owner)
    other_device = app.test_client()
    other_device.set_cookie("pp_session", anna.get_cookie("pp_session").value, domain="localhost")
    old_codes = sql(app, "SELECT count(*) AS n FROM recovery_codes WHERE user_id = %s", (anna.user_id,))[0]["n"]
    sql(app, "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) VALUES (%s, 'https://push.example/x', 'k', 'a')", (anna.user_id,))
    made = post(owner, f"/api/users/{anna.user_id}/reset").get_json()
    guest, fresh = app.test_client(), FakeAuthenticator()
    opts = guest.post("/api/invites/passkey/options", json={"name": "Ignored"}, headers=as_guest(made["token"])).get_json()
    assert opts["user"]["name"] == "Anna"                                              # the name is read-only
    done = guest.post("/api/invites/passkey/verify", json={"credential": fresh.register(opts)}, headers=as_guest(made["token"]))
    assert done.status_code == 200 and old_codes == 8 and len(done.get_json()["recovery_codes"]) == 8
    assert anna.get("/api/projects").status_code == 401 and other_device.get("/api/projects").status_code == 401
    assert guest.get("/api/auth/status").get_json()["user"]["id"] == anna.user_id               # same person, same data, new keys
    options = post(app.test_client(), "/api/auth/login/options").get_json()
    assert post(app.test_client(), "/api/auth/login/verify", {"credential": anna.passkey.assert_(options)}).status_code == 401
    assert post(app.test_client(), "/api/auth/login/verify", {"credential": fresh.assert_(options)}).status_code == 200
    assert sql(app, "SELECT count(*) AS n FROM webauthn_credentials WHERE user_id = %s", (anna.user_id,))[0]["n"] == 1
    assert sql(app, "SELECT count(*) AS n FROM push_subscriptions WHERE user_id = %s", (anna.user_id,))[0]["n"] == 0
    assert user_list(owner)["Anna"]["role"] == "user"                                  # a reset does not change the role


def test_a_reset_also_replaces_a_password_and_its_two_step_verification(app, owner):
    guest, secret, codes, _ = join_with_password(app, owner, "Bea")
    bea_id = user_list(owner)["Bea"]["id"]
    made = post(owner, f"/api/users/{bea_id}/reset").get_json()
    fresh, new_secret = app.test_client(), None
    started = fresh.post("/api/invites/password/start", json={"password": "another long password 77"}, headers=as_guest(made["token"]))
    new_secret = secret_of(started)
    done = fresh.post("/api/invites/password/confirm", json={"code": code_for(new_secret)}, headers=as_guest(made["token"]))
    assert done.status_code == 200 and guest.get("/api/projects").status_code == 401
    assert post(app.test_client(), "/api/auth/password/login", {"name": "Bea", "password": PASSWORD}).status_code == 401
    assert post(app.test_client(), "/api/auth/password/login", {"name": "Bea", "password": "another long password 77"}).status_code == 200
    assert sql(app, "SELECT count(*) AS n FROM mfa_backup_codes WHERE user_id = %s", (bea_id,))[0]["n"] == 8


def test_there_is_one_reset_link_per_person_and_a_new_one_replaces_the_old(app, owner):
    anna = join_with_passkey(app, owner)
    first = post(owner, f"/api/users/{anna.user_id}/reset").get_json()
    second = post(owner, f"/api/users/{anna.user_id}/reset").get_json()
    guest = app.test_client()
    assert guest.get("/api/invites/info", headers=as_guest(first["token"])).status_code == 404
    assert guest.get("/api/invites/info", headers=as_guest(second["token"])).status_code == 200
    assert sql(app, "SELECT count(*) AS n FROM invitations WHERE kind = 'reset'")[0]["n"] == 1


def test_resetting_an_administrator_needs_a_confirmation_bound_to_that_administrator(app, owner):
    anna = join_with_passkey(app, owner, role="admin")
    assert post(owner, f"/api/users/{anna.user_id}/reset").status_code == 400
    wrong = proof(owner, "user-reset", str(uuid.uuid4()))
    assert post(owner, f"/api/users/{anna.user_id}/reset", wrong).status_code == 403
    assert post(owner, f"/api/users/{anna.user_id}/reset", proof(owner, "user-reset", anna.user_id)).status_code == 201


def test_a_reset_link_whose_person_is_gone_is_invalid(app, owner):
    anna = join_with_passkey(app, owner)
    made = post(owner, f"/api/users/{anna.user_id}/reset").get_json()
    delete(owner, f"/api/users/{anna.user_id}")
    assert app.test_client().get("/api/invites/info", headers=as_guest(made["token"])).status_code == 404


def test_the_owner_and_yourself_cannot_be_reset_or_removed(app, owner):
    owner_id = user_list(owner)["Helmer"]["id"]
    assert post(owner, f"/api/users/{owner_id}/reset").status_code == 404                  # as if there were no such person
    assert delete(owner, f"/api/users/{owner_id}").status_code == 400
    anna = join_with_passkey(app, owner, role="admin")
    assert post(anna, f"/api/users/{anna.user_id}/reset").status_code == 400
    assert delete(anna, f"/api/users/{anna.user_id}").status_code == 400
    assert sql(app, "SELECT count(*) AS n FROM users")[0]["n"] == 2


# --- removing a person ----------------------------------------------------------------------------------------------------

def test_removing_a_person_removes_everything_that_hangs_off_them_and_ends_their_session_but_keeps_the_business_data(app, owner):
    anna = join_with_passkey(app, owner)
    made = post(anna, "/api/customers", {"name": "Kees"}).get_json()
    sql(app, "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) VALUES (%s, 'https://push.example/y', 'k', 'a')", (anna.user_id,))
    post(owner, f"/api/users/{anna.user_id}/reset")
    assert delete(owner, f"/api/users/{anna.user_id}").status_code == 200
    assert anna.get("/api/projects").status_code == 401
    for table in ("webauthn_credentials", "recovery_codes", "password_credentials", "mfa_backup_codes", "push_subscriptions",
                  "low_stock_alerts", "webauthn_challenges", "invitations"):
        left = sql(app, f"SELECT count(*) AS n FROM {table} WHERE user_id = %s", (anna.user_id,))[0]["n"] if table != "invitations" else \
            sql(app, "SELECT count(*) AS n FROM invitations WHERE user_id = %s", (anna.user_id,))[0]["n"]
        assert left == 0, table
    assert owner.get(f"/api/customers/{made['id']}").status_code == 200                      # what she made belongs to the business
    assert delete(owner, f"/api/users/{anna.user_id}").status_code == 404


def test_every_table_with_a_user_id_is_cleaned_by_removing_the_person(app):
    """A table added later that points at `users` must not keep rows of someone who is gone: it needs ON DELETE CASCADE (or SET NULL)."""
    rows = sql(app, "SELECT c.conrelid::regclass::text AS tbl, c.confdeltype AS action FROM pg_constraint c "
                    "WHERE c.contype = 'f' AND c.confrelid = 'users'::regclass")
    assert rows and all(r["action"] in ("c", "n") for r in rows), rows


# --- the session ---------------------------------------------------------------------------------------------------------------

def test_a_session_from_before_epochs_existed_still_works_and_a_wrong_epoch_does_not(app, owner):
    uid = owner.get("/api/auth/status").get_json()["user"]["id"]
    now = datetime.now(timezone.utc)

    def cookie(**claims):
        return jwt.encode({"sub": uid, "iat": now, "exp": now + timedelta(hours=1), **claims}, SECRET, algorithm="HS256")

    old = app.test_client()
    old.set_cookie("pp_session", cookie(), domain="localhost")
    assert old.get("/api/projects").status_code == 200
    wrong = app.test_client()
    wrong.set_cookie("pp_session", cookie(ep=3), domain="localhost")
    assert wrong.get("/api/projects").status_code == 401
    ghost = app.test_client()
    ghost.set_cookie("pp_session", cookie(sub=str(uuid.uuid4()), ep=0), domain="localhost")           # a person who no longer exists
    assert ghost.get("/api/projects").status_code == 401


# --- what is the business's and what is a person's -----------------------------------------------------------------------------------

BUSINESS = {"business": {"name": "Flux76 Prints", "iban": "NL00BANK0123456789"}, "vat_pct": "9", "price_rounding": "none",
            "low_stock": {"threshold_g": 250, "materials": {}}}


def test_the_companys_details_are_shared_and_only_an_administrator_changes_them(app, owner):
    anna = join_with_passkey(app, owner)
    for key, value in BUSINESS.items():
        assert put(anna, "/api/preferences", {key: value}).status_code == 403, key
    assert put(owner, "/api/preferences", BUSINESS).status_code == 200
    seen = anna.get("/api/preferences").get_json()
    assert seen["business"]["name"] == "Flux76 Prints" and seen["vat_pct"] == "9" and seen["low_stock"]["threshold_g"] == 250
    assert sql(app, "SELECT preferences->'business'->>'name' AS n FROM shared_preferences")[0]["n"] == "Flux76 Prints"
    assert "business" not in sql(app, "SELECT preferences FROM users WHERE display_name = 'Helmer'")[0]["preferences"]


def test_personal_preferences_stay_personal(app, owner):
    anna = join_with_passkey(app, owner)
    assert put(anna, "/api/preferences", {"theme": "dark", "language": "en", "business_mode": True}).status_code == 200
    assert put(owner, "/api/preferences", {"theme": "light"}).status_code == 200
    assert anna.get("/api/preferences").get_json()["theme"] == "dark"
    assert owner.get("/api/preferences").get_json()["theme"] == "light" and "language" not in owner.get("/api/preferences").get_json()
    assert owner.get("/api/preferences").get_json().get("business_mode") is None


def test_a_refused_change_of_the_companys_details_changes_nothing_at_all(app, owner):
    anna = join_with_passkey(app, owner)
    assert put(anna, "/api/preferences", {"theme": "dark", "vat_pct": "0"}).status_code == 403
    assert "theme" not in anna.get("/api/preferences").get_json()


def test_the_invoice_uses_the_companys_details_whoever_makes_it(app, owner):
    from pypdf import PdfReader
    import io
    put(owner, "/api/preferences", {"business": {"name": "Flux76 Prints", "iban": "NL91ABNA0417164300"}})
    anna = join_with_passkey(app, owner)
    order = new_order(anna)
    invoice = post(anna, f"/api/orders/{order['id']}/invoice")
    assert invoice.status_code == 200 and invoice.data[:4] == b"%PDF"
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(invoice.data)).pages)
    assert "Flux76 Prints" in text


def test_the_low_stock_thresholds_are_the_same_for_everybody(app, owner):
    put(owner, "/api/preferences", {"low_stock": {"threshold_g": 123, "materials": {}}})
    anna = join_with_passkey(app, owner)
    assert anna.get("/api/preferences").get_json()["low_stock"]["threshold_g"] == 123


def test_a_backup_holds_the_business_and_the_restoring_administrators_own_choices_but_no_one_elses_and_no_invitations(app, owner):
    put(owner, "/api/preferences", {**BUSINESS, "theme": "dark"})
    anna = join_with_passkey(app, owner, role="admin")
    put(anna, "/api/preferences", {"theme": "light"})
    invite(owner, "Secret Name")
    doc = anna.get("/api/backup").get_json()
    assert doc["preferences"]["business"]["name"] == "Flux76 Prints" and doc["preferences"]["theme"] == "light"
    text = str(doc)
    for forbidden in ("Secret Name", "token_hash", "invitation", "Helmer", "public_key"):
        assert forbidden not in text, forbidden


def test_restoring_a_backup_puts_the_business_back_for_everybody(app, owner):
    put(owner, "/api/preferences", BUSINESS)
    doc = owner.get("/api/backup").get_json()
    put(owner, "/api/preferences", {"business": {"name": "Changed"}})
    assert post(owner, "/api/backup/restore", doc).status_code == 200
    anna = join_with_passkey(app, owner)
    assert anna.get("/api/preferences").get_json()["business"]["name"] == "Flux76 Prints"


def test_an_old_backup_that_kept_the_business_in_the_persons_preferences_still_restores(app, owner):
    doc = owner.get("/api/backup").get_json()
    doc["preferences"] = {"theme": "dark", "business": {"name": "From an older release"}, "vat_pct": "6"}
    assert post(owner, "/api/backup/restore", doc).status_code == 200
    prefs = owner.get("/api/preferences").get_json()
    assert prefs["business"]["name"] == "From an older release" and prefs["vat_pct"] == "6" and prefs["theme"] == "dark"


# --- the data migration --------------------------------------------------------------------------------------------------------

def test_the_migration_moves_the_owners_business_settings_to_the_shared_row_and_makes_them_owner_and_administrator(fresh_db, tmp_path):
    import shutil
    from app.db import MIGRATIONS_DIR, run_migrations
    work = tmp_path / "migrations"
    work.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if not path.name.startswith("0024"):
            shutil.copy(path, work / path.name)
    run_migrations(fresh_db, work)
    with psycopg.connect(fresh_db, autocommit=True) as conn:
        conn.execute("INSERT INTO users (display_name, preferences) VALUES ('Helmer', %s::jsonb)",
                     ('{"theme": "dark", "business": {"name": "Flux76"}, "vat_pct": "9", "price_rounding": "none", '
                      '"low_stock": {"threshold_g": 300, "materials": {}}, "business_mode": true}',))
    shutil.copy(next(MIGRATIONS_DIR.glob("0024_*.sql")), work / next(MIGRATIONS_DIR.glob("0024_*.sql")).name)
    assert run_migrations(fresh_db, work) == [next(MIGRATIONS_DIR.glob("0024_*.sql")).name]
    with psycopg.connect(fresh_db) as conn:
        user = conn.execute("SELECT role, is_owner, session_epoch, preferences FROM users").fetchone()
        shared = conn.execute("SELECT preferences FROM shared_preferences").fetchone()[0]
    assert user[:3] == ("admin", True, 0)
    assert user[3] == {"theme": "dark", "business_mode": True}
    assert shared == {"business": {"name": "Flux76"}, "vat_pct": "9", "price_rounding": "none", "low_stock": {"threshold_g": 300, "materials": {}}}
