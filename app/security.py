"""Password hashing and JWT issuing."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import Settings

ACCESS = "access"
REFRESH = "refresh"


def _prehash(password: str) -> bytes:
    # bcrypt silently ignores everything past 72 bytes, so the password is
    # folded to a fixed-length digest first. This also lets UTF-8 passwords of
    # any length count in full.
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def _encode(
    *,
    settings: Settings,
    user_id: str,
    device_id: str,
    kind: str,
    lifetime: timedelta,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "did": device_id,
        "typ": kind,
        "iat": now,
        "exp": now + lifetime,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(settings: Settings, user_id: str, device_id: str) -> str:
    return _encode(
        settings=settings,
        user_id=user_id,
        device_id=device_id,
        kind=ACCESS,
        lifetime=timedelta(minutes=settings.access_token_minutes),
    )


def create_refresh_token(settings: Settings, user_id: str, device_id: str) -> str:
    return _encode(
        settings=settings,
        user_id=user_id,
        device_id=device_id,
        kind=REFRESH,
        lifetime=timedelta(days=settings.refresh_token_days),
    )


def decode_token(settings: Settings, token: str, *, expect: str) -> dict[str, object]:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "did", "typ", "exp"]},
    )
    if payload.get("typ") != expect:
        raise jwt.InvalidTokenError("unexpected token type")
    return payload
