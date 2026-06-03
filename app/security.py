"""Passwords (PBKDF2, no native deps — like your CRM), JWTs, and device tokens."""
import hashlib
import hmac
import secrets
import time

import jwt

from .config import settings

_PBKDF2_ROUNDS = 200_000


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ROUNDS)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ROUNDS)
    return hmac.compare_digest(dk.hex(), expected)


def make_access_token(user_id: str, role: str) -> str:
    payload = {"sub": user_id, "role": role, "type": "access",
               "exp": int(time.time()) + settings.ACCESS_TTL}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def make_session_token(user_id: str, device_id: str, session_id: str) -> str:
    """Short-lived, single-purpose token a VA presents to open the stream."""
    payload = {"sub": user_id, "dev": device_id, "sid": session_id, "type": "stream",
               "exp": int(time.time()) + settings.SESSION_TOKEN_TTL}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])


def new_device_token() -> tuple[str, str]:
    """Return (raw_token_to_give_the_agent_once, hash_to_store)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_device_token(raw)


def hash_device_token(raw: str) -> str:
    return hashlib.sha256((raw + settings.DEVICE_TOKEN_PEPPER).encode()).hexdigest()
