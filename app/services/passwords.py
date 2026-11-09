"""Password hashing with the standard library's scrypt.

Stored format: "scrypt$n$r$p$salt_b64$hash_b64", so the cost can be raised later while
old hashes still verify with the parameters they were made with.
"""

import base64
import hashlib
import hmac
import secrets

from app.core.config import settings

ALGORITHM = "scrypt"
SALT_BYTES = 16
KEY_BYTES = 32
BLOCK_SIZE_R = 8
PARALLELISM_P = 1
# Fixed salt for verify_dummy only; it never protects a real password.
DUMMY_SALT = b"ainis-dummy-salt"


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    """Derive the key. maxmem is set explicitly: the 32 MiB default is too small for n=2**15."""
    needed_bytes = 128 * r * (n + p + 2)
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=needed_bytes + 1024 * 1024,
        dklen=KEY_BYTES,
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    """Hash with a fresh random salt and the configured cost."""
    n = settings.password_scrypt_n
    salt = secrets.token_bytes(SALT_BYTES)
    key = _scrypt(password, salt, n, BLOCK_SIZE_R, PARALLELISM_P)
    return f"{ALGORITHM}${n}${BLOCK_SIZE_R}${PARALLELISM_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored_hash: str) -> bool:
    """True when the password matches; False also for a malformed stored hash."""
    try:
        algorithm, n, r, p, salt_b64, key_b64 = stored_hash.split("$")
        if algorithm != ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(key_b64, validate=True)
        actual = _scrypt(password, salt, int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


def verify_dummy(password: str) -> None:
    """Spend the same time as one real check, for usernames that do not exist."""
    _scrypt(password, DUMMY_SALT, settings.password_scrypt_n, BLOCK_SIZE_R, PARALLELISM_P)
