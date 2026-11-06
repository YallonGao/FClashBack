"""Registration, login, token refresh, and the current account."""

from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import Principal, get_principal
from ..models import Device, User
from ..schemas import (
    DeviceIn,
    LoginIn,
    RefreshIn,
    RegisterIn,
    SessionOut,
    TokenPair,
    UserOut,
)
from ..security import (
    REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _upsert_device(db: Session, user: User, payload: DeviceIn) -> Device:
    device = db.scalar(
        select(Device).where(Device.user_id == user.id, Device.key == payload.key)
    )
    if device is None:
        device = Device(
            user_id=user.id,
            key=payload.key,
            name=payload.name,
            platform=payload.platform,
        )
        db.add(device)
    else:
        device.name = payload.name or device.name
        device.platform = payload.platform or device.platform
        device.revoked = False
    db.flush()
    return device


def _issue(settings: Settings, user: User, device: Device) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(settings, user.id, device.id),
        refresh_token=create_refresh_token(settings, user.id, device.id),
        expires_in=settings.access_token_minutes * 60,
    )


@router.post("/register", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SessionOut:
    if not settings.allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="registration_closed")
    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="username_taken") from exc
    device = _upsert_device(db, user, payload.device)
    db.commit()
    return SessionOut(
        user=UserOut.model_validate(user),
        device=device,
        tokens=_issue(settings, user, device),
    )


@router.post("/login", response_model=SessionOut)
def login(
    payload: LoginIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SessionOut:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
    if user.disabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="account_disabled")
    device = _upsert_device(db, user, payload.device)
    db.commit()
    return SessionOut(
        user=UserOut.model_validate(user),
        device=device,
        tokens=_issue(settings, user, device),
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(
    payload: RefreshIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenPair:
    try:
        claims = decode_token(settings, payload.refresh_token, expect=REFRESH)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_token") from exc

    device = db.get(Device, str(claims["did"]))
    user = db.get(User, str(claims["sub"]))
    if device is None or user is None or device.revoked or user.disabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="session_revoked")
    return _issue(settings, user, device)


@router.get("/me", response_model=UserOut)
def me(principal: Principal = Depends(get_principal)) -> UserOut:
    return UserOut.model_validate(principal.user)
