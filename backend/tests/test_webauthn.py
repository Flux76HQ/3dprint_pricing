import pytest

from app import webauthn as wa
from tests.fake_authenticator import FakeAuthenticator

RP, ORIGIN = "localhost", "https://localhost:6080"
ORIGINS = (ORIGIN,)


def registration(auth, **kw):
    challenge = wa.new_challenge()
    return challenge, auth.register({"challenge": wa.b64u_encode(challenge)}, **kw)


def registered(**kw):
    auth = FakeAuthenticator(RP, ORIGIN)
    challenge, cred = registration(auth, **kw)
    return auth, wa.verify_registration(cred, challenge, RP, ORIGINS)


def assertion(auth, **kw):
    challenge = wa.new_challenge()
    return challenge, auth.assert_({"challenge": wa.b64u_encode(challenge)}, **kw)


def verify(result, parts, stored=0):
    challenge, cred = parts
    return wa.verify_assertion(cred, challenge, RP, ORIGINS, result["public_key"], stored)


def test_registration_roundtrip_extracts_the_credential():
    auth, result = registered()
    assert result["credential_id"] == auth.credential_id
    assert result["public_key"] == auth._cose()  # stored as the authenticator's COSE bytes, as before
    assert result["sign_count"] == 0


def test_assertion_roundtrip_returns_the_new_counter():
    auth, result = registered()
    assert verify(result, assertion(auth)) == 1


@pytest.mark.parametrize("kwargs", [
    {"origin": "https://evil.example"},
    {"flags": 0x44},           # verified, but not present
])
def test_registration_refuses(kwargs):
    auth = FakeAuthenticator(RP, ORIGIN)
    challenge, cred = registration(auth, **kwargs)
    with pytest.raises(wa.WebAuthnError):
        wa.verify_registration(cred, challenge, RP, ORIGINS)


def test_registration_accepts_a_password_manager_that_does_not_verify_the_user():
    # Enpass, Bitwarden and friends report user presence only; their own unlock is the verification.
    auth, result = registered(flags=0x41)
    assert result["credential_id"] == auth.credential_id


def test_registration_refuses_wrong_challenge_and_wrong_rp():
    auth = FakeAuthenticator(RP, ORIGIN)
    challenge, cred = registration(auth)
    with pytest.raises(wa.WebAuthnError, match="challenge"):
        wa.verify_registration(cred, wa.new_challenge(), RP, ORIGINS)
    challenge, cred = registration(auth, rp_id="other.example")
    with pytest.raises(wa.WebAuthnError, match="RP ID"):
        wa.verify_registration(cred, challenge, RP, ORIGINS)


def test_registration_refuses_a_key_that_is_not_es256():
    # The options only offer ES256; a response with another algorithm is refused, not stored.
    auth = FakeAuthenticator(RP, ORIGIN)
    auth._cose = lambda: __import__("cbor2").dumps({1: 3, 3: -257, -1: b"\x01" * 256, -2: b"\x01\x00\x01"})
    challenge, cred = registration(auth)
    with pytest.raises(wa.WebAuthnError):
        wa.verify_registration(cred, challenge, RP, ORIGINS)


def test_assertion_refuses_a_signature_from_another_key():
    from cryptography.hazmat.primitives.asymmetric import ec
    auth, result = registered()
    parts = assertion(auth, key=ec.generate_private_key(ec.SECP256R1()))
    with pytest.raises(wa.WebAuthnError, match="signature"):
        verify(result, parts)


def test_assertion_refuses_a_counter_that_did_not_advance():
    auth, result = registered()
    parts = assertion(auth)  # counter 1
    with pytest.raises(wa.WebAuthnError, match="counter"):
        verify(result, parts, stored=1)


def test_assertion_accepts_authenticators_without_a_counter():
    auth, result = registered()
    assert verify(result, assertion(auth, bump=False), stored=0) == 0


def test_assertion_refuses_wrong_origin_and_missing_presence():
    auth, result = registered()
    with pytest.raises(wa.WebAuthnError, match="Origin"):
        verify(result, assertion(auth, origin="https://evil.example"))
    with pytest.raises(wa.WebAuthnError, match="aanwezigheid"):
        verify(result, assertion(auth, flags=0x04))


def test_assertion_accepts_presence_without_verification():
    auth, result = registered()
    assert verify(result, assertion(auth, flags=0x01)) == 1


def test_garbage_is_a_webauthn_error_not_a_crash():
    for garbage in ({}, {"id": "x"}, {"id": "x", "rawId": "x", "response": {}}, "not json", None):
        with pytest.raises(wa.WebAuthnError):
            wa.verify_registration(garbage, b"x", RP, ORIGINS)
        with pytest.raises(wa.WebAuthnError):
            wa.verify_assertion(garbage, b"x", RP, ORIGINS, b"", 0)
