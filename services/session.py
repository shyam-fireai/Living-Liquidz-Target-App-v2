"""Signed session tokens: "<expires_at>.<hex HMAC-SHA256(email|expires_at)>".

The token is bound to the e-mail and expiry, so editing the auth_user cookie or extending
the expiry invalidates it."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from functools import lru_cache

from config import get_secret

logger = logging.getLogger(__name__)

SESSION_SECONDS = 60 * 60  # 1 hour


@lru_cache(maxsize=1)
def _secret() -> bytes:
    value = get_secret("COOKIE_SECRET")
    if not value:
        logger.warning(
            "COOKIE_SECRET is not set in secrets.json/env - using a random per-process secret; "
            "users will have to log in again after every server restart."
        )
        value = secrets.token_hex(32)
    return value.encode()


def _sign(email: str, expires_at: int, key: bytes) -> str:
    msg = f"{email.strip().lower()}|{expires_at}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def create_token(email: str, expires_at: int | None = None, key: bytes | None = None) -> str:
    expires_at = int(expires_at if expires_at is not None else time.time() + SESSION_SECONDS)
    return f"{expires_at}.{_sign(email, expires_at, key or _secret())}"


def token_expiry(token: str) -> int | None:
    try:
        return int(token.split(".", 1)[0])
    except (AttributeError, ValueError):
        return None


def verify_token(email: str | None, token: str | None, key: bytes | None = None, now: float | None = None) -> bool:
    if not email or not token or "." not in token:
        return False
    expires_at = token_expiry(token)
    if expires_at is None or expires_at < (now if now is not None else time.time()):
        return False
    signature = token.split(".", 1)[1]
    return hmac.compare_digest(signature, _sign(email, expires_at, key or _secret()))
