"""Password hashing for the dashboard's Basic Auth.

The GUI stores only a salted scrypt hash (never the password) and hands that to the
server, which only ever needs to *verify* credentials.

Encoded format: ``scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>``
"""

import base64
import hashlib
import hmac
import secrets

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
HASH_BYTES = 32
# Refuse absurd parameters from a tampered/corrupt setting rather than letting
# one request burn gigabytes of memory.
MAX_SCRYPT_N = 2**20
MAX_SCRYPT_R = 32
MAX_SCRYPT_P = 16


def _b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=dklen,
        maxmem=256 * n * r * p,
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, HASH_BYTES)
    return "$".join(
        [
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            _b64encode(salt),
            _b64encode(digest),
        ]
    )


def is_valid_hash(encoded: str | None) -> bool:
    return _parse(encoded) is not None


def verify_password(password: str, encoded: str | None) -> bool:
    parsed = _parse(encoded)
    if parsed is None:
        return False
    n, r, p, salt, expected = parsed
    actual = _scrypt(password, salt, n, r, p, len(expected))
    return hmac.compare_digest(actual, expected)


def _parse(encoded: str | None) -> tuple[int, int, int, bytes, bytes] | None:
    if not encoded:
        return None
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return None
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = base64.b64decode(parts[4], validate=True)
        expected = base64.b64decode(parts[5], validate=True)
    except ValueError:
        return None
    if not (
        1 < n <= MAX_SCRYPT_N
        and n & (n - 1) == 0
        and 0 < r <= MAX_SCRYPT_R
        and 0 < p <= MAX_SCRYPT_P
        and salt
        and len(expected) >= 16
    ):
        return None
    return n, r, p, salt, expected


__all__ = ["hash_password", "is_valid_hash", "verify_password"]
