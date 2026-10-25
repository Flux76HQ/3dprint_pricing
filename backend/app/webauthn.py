"""WebAuthn verification, hand-rolled on cbor2 + cryptography. ES256 only.

Pure functions: no database, no Flask. Challenge storage and sessions live in
`auth.py`, so everything here can be tested with a simulated authenticator.
"""
import base64
import hashlib
import io
import json
import os
import struct

import cbor2
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from .i18n import Localized

FLAG_UP = 0x01
FLAG_AT = 0x40

COSE_KTY, COSE_ALG, COSE_CRV, COSE_X, COSE_Y = 1, 3, -1, -2, -3


class WebAuthnError(Localized):
    pass


def b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64u_decode(value: str) -> bytes:
    if not isinstance(value, str):
        raise WebAuthnError("wa.b64")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def new_challenge() -> bytes:
    return os.urandom(32)


def _client_data(raw: bytes, expected_type: str, challenge: bytes, origins) -> None:
    try:
        data = json.loads(raw)
    except ValueError:
        raise WebAuthnError("wa.client_json") from None
    if data.get("type") != expected_type:
        raise WebAuthnError("wa.ceremony")
    if data.get("challenge") != b64u_encode(challenge):
        raise WebAuthnError("wa.challenge")
    if str(data.get("origin", "")).rstrip("/") not in origins:
        raise WebAuthnError("wa.origin")


def _auth_data(auth_data: bytes, rp_id: str) -> tuple[int, int]:
    if len(auth_data) < 37:
        raise WebAuthnError("wa.auth_short")
    if auth_data[:32] != hashlib.sha256(rp_id.encode()).digest():
        raise WebAuthnError("wa.rp_hash")
    flags = auth_data[32]
    # Presence only: a password manager (Enpass, Bitwarden...) unlocks with its own master password and
    # reports the user as not verified, so requiring the UV flag would lock those passkeys out.
    if not flags & FLAG_UP:
        raise WebAuthnError("wa.up")
    return flags, struct.unpack(">I", auth_data[33:37])[0]


def public_key_from_cose(cose: bytes) -> ec.EllipticCurvePublicKey:
    key = cbor2.loads(cose)
    if key.get(COSE_KTY) != 2 or key.get(COSE_ALG) != -7 or key.get(COSE_CRV) != 1:
        raise WebAuthnError("wa.es256")
    x, y = key.get(COSE_X), key.get(COSE_Y)
    if not isinstance(x, bytes) or not isinstance(y, bytes) or len(x) != 32 or len(y) != 32:
        raise WebAuthnError("wa.bad_key")
    return ec.EllipticCurvePublicNumbers(
        int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()
    ).public_key()


def verify_registration(client_data_json: bytes, attestation_object: bytes, challenge: bytes,
                        rp_id: str, origins) -> dict:
    """Return {credential_id, public_key (COSE bytes), sign_count}."""
    _client_data(client_data_json, "webauthn.create", challenge, origins)
    try:
        attestation = cbor2.loads(attestation_object)
        auth_data = attestation["authData"]
    except Exception:
        raise WebAuthnError("wa.attestation") from None
    flags, sign_count = _auth_data(auth_data, rp_id)
    if not flags & FLAG_AT:
        raise WebAuthnError("wa.no_cred")
    rest = auth_data[37 + 16:]  # skip AAGUID
    if len(rest) < 2:
        raise WebAuthnError("wa.cred_cut")
    cred_len = struct.unpack(">H", rest[:2])[0]
    credential_id = rest[2:2 + cred_len]
    stream = io.BytesIO(rest[2 + cred_len:])
    try:
        cbor2.CBORDecoder(stream).decode()
    except Exception:
        raise WebAuthnError("wa.key_invalid") from None
    cose = rest[2 + cred_len:2 + cred_len + stream.tell()]
    public_key_from_cose(cose)  # validates curve/algorithm
    return {"credential_id": credential_id, "public_key": cose, "sign_count": sign_count}


def verify_assertion(client_data_json: bytes, authenticator_data: bytes, signature: bytes,
                     challenge: bytes, rp_id: str, origins, public_key_cose: bytes,
                     stored_count: int) -> int:
    """Return the new signature counter, or raise WebAuthnError."""
    _client_data(client_data_json, "webauthn.get", challenge, origins)
    _, count = _auth_data(authenticator_data, rp_id)
    signed = authenticator_data + hashlib.sha256(client_data_json).digest()
    try:
        public_key_from_cose(public_key_cose).verify(signature, signed, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise WebAuthnError("wa.signature") from None
    # Both zero means the authenticator has no counter (common for synced passkeys).
    if (count or stored_count) and count <= stored_count:
        raise WebAuthnError("wa.counter")
    return count
