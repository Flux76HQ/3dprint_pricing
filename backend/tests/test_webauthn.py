import pytest

from app import webauthn as wa
from tests.fake_authenticator import FakeAuthenticator

RP, ORIGIN = "localhost", "https://localhost:6080"
ORIGINS = (ORIGIN,)


def registered():
    auth = FakeAuthenticator(RP, ORIGIN)
    challenge = wa.new_challenge()
    cred = auth.register({"challenge": wa.b64u_encode(challenge)})
    r = cred["response"]
    result = wa.verify_registration(wa.b64u_decode(r["clientDataJSON"]),
                                    wa.b64u_decode(r["attestationObject"]), challenge, RP, ORIGINS)
    return auth, result


def assertion(auth, **kw):
    challenge = wa.new_challenge()
    cred = auth.assert_({"challenge": wa.b64u_encode(challenge)}, **kw)
    r = cred["response"]
    return challenge, wa.b64u_decode(r["clientDataJSON"]), wa.b64u_decode(r["authenticatorData"]), \
        wa.b64u_decode(r["signature"])


def verify(auth, result, parts, stored=0):
    challenge, client, auth_data, sig = parts
    return wa.verify_assertion(client, auth_data, sig, challenge, RP, ORIGINS, result["public_key"], stored)


def test_registration_roundtrip_extracts_the_credential():
    auth, result = registered()
    assert result["credential_id"] == auth.credential_id
    assert wa.public_key_from_cose(result["public_key"])


def test_assertion_roundtrip_returns_the_new_counter():
    auth, result = registered()
    assert verify(auth, result, assertion(auth)) == 1


@pytest.mark.parametrize("kwargs", [
    {"origin": "https://evil.example"},
    {"flags": 0x41},           # user present, but not verified
    {"flags": 0x44},           # verified, but not present
])
def test_registration_refuses(kwargs):
    auth = FakeAuthenticator(RP, ORIGIN)
    challenge = wa.new_challenge()
    r = auth.register({"challenge": wa.b64u_encode(challenge)}, **kwargs)["response"]
    with pytest.raises(wa.WebAuthnError):
        wa.verify_registration(wa.b64u_decode(r["clientDataJSON"]),
                               wa.b64u_decode(r["attestationObject"]), challenge, RP, ORIGINS)


def test_registration_refuses_wrong_challenge_and_wrong_rp():
    auth = FakeAuthenticator(RP, ORIGIN)
    challenge = wa.new_challenge()
    r = auth.register({"challenge": wa.b64u_encode(challenge)})["response"]
    with pytest.raises(wa.WebAuthnError, match="Challenge"):
        wa.verify_registration(wa.b64u_decode(r["clientDataJSON"]),
                               wa.b64u_decode(r["attestationObject"]), wa.new_challenge(), RP, ORIGINS)
    r = auth.register({"challenge": wa.b64u_encode(challenge)}, rp_id="other.example")["response"]
    with pytest.raises(wa.WebAuthnError, match="RP ID"):
        wa.verify_registration(wa.b64u_decode(r["clientDataJSON"]),
                               wa.b64u_decode(r["attestationObject"]), challenge, RP, ORIGINS)


def test_assertion_refuses_a_signature_from_another_key():
    from cryptography.hazmat.primitives.asymmetric import ec
    auth, result = registered()
    parts = assertion(auth, key=ec.generate_private_key(ec.SECP256R1()))
    with pytest.raises(wa.WebAuthnError, match="handtekening"):
        verify(auth, result, parts)


def test_assertion_refuses_a_counter_that_did_not_advance():
    auth, result = registered()
    parts = assertion(auth)  # counter 1
    with pytest.raises(wa.WebAuthnError, match="counter"):
        verify(auth, result, parts, stored=1)


def test_assertion_accepts_authenticators_without_a_counter():
    auth, result = registered()
    assert verify(auth, result, assertion(auth, bump=False), stored=0) == 0


def test_assertion_refuses_wrong_origin_and_missing_verification():
    auth, result = registered()
    with pytest.raises(wa.WebAuthnError, match="Origin"):
        verify(auth, result, assertion(auth, origin="https://evil.example"))
    with pytest.raises(wa.WebAuthnError, match="verificatie"):
        verify(auth, result, assertion(auth, flags=0x01))


def test_garbage_is_a_webauthn_error_not_a_crash():
    with pytest.raises(wa.WebAuthnError):
        wa.verify_registration(b"{}", b"\x00\x01", b"x", RP, ORIGINS)
    with pytest.raises(wa.WebAuthnError):
        wa.verify_registration(b"not json", b"", b"x", RP, ORIGINS)
