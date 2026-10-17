#!/usr/bin/env python3
"""Print a VAPID key pair for web push, as lines to paste into .env.

    python scripts/generate_vapid.py

The private key signs every push this server sends; keep it secret. The public key is handed to
browsers when a device opts in. Changing the pair later makes existing subscriptions unusable (devices
have to turn notifications off and on again).
"""
import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate() -> dict:
    key = ec.generate_private_key(ec.SECP256R1())
    return {
        "VAPID_PRIVATE_KEY": b64u(key.private_numbers().private_value.to_bytes(32, "big")),
        "VAPID_PUBLIC_KEY": b64u(key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)),
    }


if __name__ == "__main__":
    for name, value in generate().items():
        print(f"{name}={value}")
