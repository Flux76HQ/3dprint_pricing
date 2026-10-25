"""WebAuthn verification, delegated to py_webauthn (the `webauthn` package).

The ceremony itself (client data, challenge, origin, RP ID hash, flags, attestation, signature and
counter) is checked by that library, not by us. This module only fixes the policy, turns the library's
errors into our own translated `WebAuthnError`, and keeps a few base64url helpers. Challenge storage and
sessions live in `auth.py`, so everything here can be tested with a simulated authenticator.

Policy: ES256 only (the only algorithm `auth.py` offers); user *presence* is required, user
*verification* is not, because a password manager (Enpass, Bitwarden...) unlocks with its own master
password and does not report the verified flag.
"""
from webauthn import verify_authentication_response, verify_registration_response
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, generate_challenge
from webauthn.helpers.cose import COSEAlgorithmIdentifier

from .i18n import Localized

ES256 = [COSEAlgorithmIdentifier.ECDSA_SHA_256]

# The library words its refusals in English. These few are the ones an operator or a user can act on, so
# they get a translated text of their own; everything else is shown as the generic "refused: {reason}".
_KNOWN = (
    ("Unexpected client data origin", "wa.origin"),
    ("Unexpected RP ID hash", "wa.rp_hash"),
    ("not present", "wa.up"),
    ("sign count", "wa.counter"),
)


class WebAuthnError(Localized):
    pass


def b64u_encode(raw: bytes) -> str:
    return bytes_to_base64url(raw)


def b64u_decode(value: str) -> bytes:
    if not isinstance(value, str):
        raise WebAuthnError("wa.b64")
    return base64url_to_bytes(value)


def new_challenge() -> bytes:
    return generate_challenge()


def _refused(exc: Exception) -> WebAuthnError:
    text = str(exc)
    for needle, key in _KNOWN:
        if needle in text:
            return WebAuthnError(key)
    return WebAuthnError("wa.refused", reason=text or type(exc).__name__)


def verify_registration(credential: dict, challenge: bytes, rp_id: str, origins) -> dict:
    """Return {credential_id, public_key (COSE bytes), sign_count}."""
    try:
        result = verify_registration_response(
            credential=credential, expected_challenge=challenge, expected_rp_id=rp_id,
            expected_origin=list(origins), require_user_verification=False,
            supported_pub_key_algs=ES256)
    except Exception as exc:  # untrusted input: whatever the library trips on, the answer is "refused"
        raise _refused(exc) from None
    return {"credential_id": result.credential_id, "public_key": result.credential_public_key,
            "sign_count": result.sign_count}


def verify_assertion(credential: dict, challenge: bytes, rp_id: str, origins, public_key_cose: bytes,
                     stored_count: int) -> int:
    """Return the new signature counter, or raise WebAuthnError."""
    try:
        result = verify_authentication_response(
            credential=credential, expected_challenge=challenge, expected_rp_id=rp_id,
            expected_origin=list(origins), credential_public_key=public_key_cose,
            credential_current_sign_count=stored_count, require_user_verification=False)
    except Exception as exc:  # untrusted input: whatever the library trips on, the answer is "refused"
        raise _refused(exc) from None
    return result.new_sign_count
