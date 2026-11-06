"""Shared request dependencies."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_db
from .models import Device, User, utcnow
from .security import ACCESS, decode_token

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user: User
    device: Device


def _unauthorized(detail: str = "invalid_token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise _unauthorized("missing_token")
    try:
        payload = decode_token(settings, credentials.credentials, expect=ACCESS)
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized() from exc

    device = db.get(Device, str(payload["did"]))
    user = db.get(User, str(payload["sub"]))
    if device is None or user is None or device.revoked or user.disabled:
        raise _unauthorized("session_revoked")

    device.last_seen_at = utcnow()
    db.commit()
    return Principal(user=user, device=device)
