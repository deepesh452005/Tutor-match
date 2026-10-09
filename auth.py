import hashlib
import hmac
import os
import secrets


def hash_password(password: str) -> str:
    """Shred the password with a random pinch of salt. Returns 'salt$dust'."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    """Shred what the person typed the same way and compare the dust."""
    salt_hex, digest_hex = stored.split("$")
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return hmac.compare_digest(digest.hex(), digest_hex)


def make_token() -> str:
    """A random, impossible-to-guess wristband."""
    return secrets.token_hex(32)