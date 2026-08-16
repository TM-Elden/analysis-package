"""Password hashing for the C11 user table - stdlib `hashlib.scrypt`, zero new dependencies.

Encoded form: `scrypt$n$r$p$<salt_hex>$<hash_hex>` - the scrypt cost parameters travel with the hash
so they can be tuned later (or per-user re-hashed on next login) without a migration that touches
every row blindly.
"""

from __future__ import annotations

import hashlib
import hmac
import os

# Interactive-login cost parameters (RFC 7914's suggested interactive profile). Not tunable via
# call site by design - one scheme everywhere keeps `verify_password` simple; bump these constants
# (and re-hash on next login) if they ever need to change.
_N = 2**14
_R = 8
_P = 1
_DKLEN = 64
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time compare. Returns False (never raises) on a malformed/foreign encoded hash."""
    try:
        scheme, n, r, p, salt_hex, hash_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        candidate = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)
