"""Request and response bodies. Pydantic models double as the API contract."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

USERNAME_PATTERN = r"^[A-Za-z0-9_.-]{3,32}$"


class DeviceIn(BaseModel):
    key: str = Field(min_length=8, max_length=64)
    name: str = Field(default="", max_length=64)
    platform: str = Field(default="", max_length=32)


class RegisterIn(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=128)
    device: DeviceIn


class LoginIn(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=1, max_length=128)
    device: DeviceIn


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    name: str
    platform: str
    revoked: bool
    created_at: datetime
    last_seen_at: datetime


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    created_at: datetime


class SessionOut(BaseModel):
    user: UserOut
    device: DeviceOut
    tokens: TokenPair


class SyncStateOut(BaseModel):
    revision: int
    checksum: str
    size: int
    updated_at: datetime | None
    device_id: str | None


class RevisionOut(BaseModel):
    revision: int
    checksum: str
    size: int
    device_id: str | None
    created_at: datetime


class PushResultOut(BaseModel):
    revision: int
    checksum: str


class ConflictOut(BaseModel):
    detail: str = "revision_conflict"
    current_revision: int
    current_checksum: str
