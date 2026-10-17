"""A software passkey: builds the payloads a browser would send."""
import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from app.webauthn import b64u_decode, b64u_encode


class FakeAuthenticator:
    def __init__(self, rp_id="localhost", origin="https://localhost:6080"):
        self.rp_id, self.origin = rp_id, origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.counter = 0

    def _cose(self):
        n = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def _client_data(self, kind, challenge_b64u, origin=None):
        return json.dumps({"type": kind, "challenge": challenge_b64u,
                           "origin": origin or self.origin}).encode()

    def _auth_data(self, flags, with_credential, rp_id=None):
        data = hashlib.sha256((rp_id or self.rp_id).encode()).digest()
        data += bytes([flags]) + struct.pack(">I", self.counter)
        if with_credential:
            data += b"\x00" * 16 + struct.pack(">H", len(self.credential_id)) + self.credential_id + self._cose()
        return data

    def register(self, options, *, origin=None, flags=0x45, rp_id=None) -> dict:
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {},
                                   "authData": self._auth_data(flags, True, rp_id)})
        return {"id": b64u_encode(self.credential_id), "rawId": b64u_encode(self.credential_id),
                "type": "public-key",
                "response": {"clientDataJSON": b64u_encode(client_data),
                             "attestationObject": b64u_encode(attestation), "transports": ["internal"]}}

    def assert_(self, options, *, origin=None, flags=0x05, bump=True, rp_id=None, key=None) -> dict:
        if bump:
            self.counter += 1
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        auth_data = self._auth_data(flags, False, rp_id)
        signature = (key or self.key).sign(auth_data + hashlib.sha256(client_data).digest(),
                                           ec.ECDSA(hashes.SHA256()))
        return {"id": b64u_encode(self.credential_id), "rawId": b64u_encode(self.credential_id),
                "type": "public-key",
                "response": {"clientDataJSON": b64u_encode(client_data),
                             "authenticatorData": b64u_encode(auth_data),
                             "signature": b64u_encode(signature), "userHandle": None}}
