"""Password login primitives: hashing, a password policy, TOTP (RFC 6238), and the keys that protect them.

Passkeys stay the primary way in. A password is an optional, weaker door, so it is only ever offered
together with a second factor, and everything here is built so a stolen database dump or a guessed
password alone does not open it.
"""
import base64
import hashlib
import hmac
import os
import struct
import time
from datetime import datetime, timedelta, timezone

import jwt
import segno
from argon2 import PasswordHasher
from argon2 import exceptions as argon_exc
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .i18n import Localized

MIN_LENGTH, MAX_LENGTH = 12, 128
TOTP_STEP, TOTP_DIGITS, TOTP_WINDOW = 30, 6, 1          # +-30 s of clock drift is accepted
MFA_TOKEN_MINUTES = 5
ISSUER = "3D Print Pricing"

_hasher = PasswordHasher()                               # argon2id, RFC 9106 low-memory profile

# Not a dictionary: just the passwords that every guess list starts with. Length does the real work.
_COMMON = {
    "password1234", "123456789012", "qwertyuiop12", "qwertyuiopas", "iloveyou1234", "letmein12345", "welcome12345",
    "administrator", "wachtwoord123", "wachtwoord1234", "passwordpassword", "abcdefghijkl", "1q2w3e4r5t6y", "000000000000",
    "111111111111", "123123123123", "123456789abc", "printpricing", "3dprintpricing", "changemechangeme",
}


# --- password ---------------------------------------------------------------------------------

def check_policy(password: str, display_name: str = "") -> None:
    """Length first, no composition rules. Raises ValueError with a message for the person."""
    if not isinstance(password, str) or len(password) < MIN_LENGTH:
        raise Localized("pw.too_short", n=MIN_LENGTH)
    if len(password) > MAX_LENGTH:
        raise Localized("pw.too_long", n=MAX_LENGTH)
    lowered = password.lower()
    if lowered in _COMMON or len(set(lowered)) < 5:
        raise Localized("pw.predictable")
    name = display_name.strip().lower()
    if len(name) >= 4 and name in lowered:
        raise Localized("pw.contains_name")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (argon_exc.VerifyMismatchError, argon_exc.VerificationError, argon_exc.InvalidHashError):
        return False


# A real hash to verify against when there is no account to check, so "no password set" and "wrong
# password" cost the same time.
_DUMMY_HASH = _hasher.hash("dummy-password-for-constant-time")


def burn_time(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


# --- TOTP -------------------------------------------------------------------------------------

def new_secret() -> bytes:
    return os.urandom(20)                                  # 160 bits, the RFC 4226 recommendation


def b32(secret: bytes) -> str:
    return base64.b32encode(secret).decode("ascii").rstrip("=")


def totp_code(secret: bytes, step: int, digits: int = TOTP_DIGITS) -> str:
    """RFC 4226 HOTP over the 30-second counter `step` (RFC 6238, SHA-1: what authenticator apps speak)."""
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** digits).zfill(digits)


def current_step(now: "float | None" = None) -> int:
    return int((time.time() if now is None else now) // TOTP_STEP)


def verify_totp(secret: bytes, code: str, now: "float | None" = None, last_step: int = 0) -> "int | None":
    """The step the code belongs to, or None. A step at or before `last_step` was already used."""
    code = "".join(str(code).split())
    if not (code.isascii() and code.isdigit() and len(code) == TOTP_DIGITS):
        return None
    step = current_step(now)
    matched = None
    for candidate in range(step - TOTP_WINDOW, step + TOTP_WINDOW + 1):
        # compare every candidate: no early exit that would tell how close a guess was
        if hmac.compare_digest(totp_code(secret, candidate), code) and candidate > last_step:
            matched = candidate
    return matched


def otpauth_uri(secret: bytes, account: str) -> str:
    from urllib.parse import quote
    label = quote(f"{ISSUER}:{account}", safe="")
    return (f"otpauth://totp/{label}?secret={b32(secret)}&issuer={quote(ISSUER)}"
            f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP}")


def qr_data_uri(uri: str) -> str:
    """Black on white whatever the theme: scanners need the contrast."""
    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2, dark="#000000", light="#ffffff")


# --- keys derived from SESSION_SECRET, one per purpose, so none can stand in for another ---------------

def _derive(session_secret: str, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(session_secret.encode())


MFA_SECRET_INFO = b"printpricing/mfa-secret/v1"


def seal(session_secret: str, secret: bytes, info: bytes = MFA_SECRET_INFO) -> bytes:
    """Encrypt a secret for storage (the TOTP secret; the OpenAI key passes its own `info`). It has to be recoverable, so it cannot be hashed."""
    key = base64.urlsafe_b64encode(_derive(session_secret, info))
    return Fernet(key).encrypt(secret)


def unseal(session_secret: str, token: bytes, info: bytes = MFA_SECRET_INFO) -> "bytes | None":
    """None when the key changed (SESSION_SECRET was rotated): password login then fails closed."""
    key = base64.urlsafe_b64encode(_derive(session_secret, info))
    try:
        return Fernet(key).decrypt(bytes(token))
    except InvalidToken:
        return None


def make_mfa_token(session_secret: str, user_id, now: "datetime | None" = None) -> str:
    """Proof that the password was right, valid for the second step only. Signed with its own derived key,
    so it can never be accepted as a session cookie (and a session cookie is no MFA token)."""
    now = now or datetime.now(timezone.utc)
    key = _derive(session_secret, b"printpricing/mfa-token/v1").hex()
    return jwt.encode({"sub": str(user_id), "typ": "mfa", "iat": now, "exp": now + timedelta(minutes=MFA_TOKEN_MINUTES)},
                      key, algorithm="HS256")


def read_mfa_token(session_secret: str, token: str) -> "str | None":
    try:
        key = _derive(session_secret, b"printpricing/mfa-token/v1").hex()
        claims = jwt.decode(token, key, algorithms=["HS256"], options={"require": ["exp", "sub", "typ"]})
        return claims["sub"] if claims["typ"] == "mfa" else None
    except (jwt.PyJWTError, KeyError, TypeError):
        return None
