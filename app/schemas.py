"""Request and response bodies. Pydantic models double as the API contract."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

USERNAME_PATTERN = r"^[A-Za-z0-9_.-]{3,32}$"


def _utc_iso(value: datetime) -> str:
    # SQLite drops tzinfo, so a naive value is UTC. Serialising it without an
    # offset makes a browser read it as local time and shift the day.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


UtcDateTime = Annotated[datetime, PlainSerializer(_utc_iso, return_type=str)]


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


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


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
    created_at: UtcDateTime
    last_seen_at: UtcDateTime


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    created_at: UtcDateTime


class SessionOut(BaseModel):
    user: UserOut
    device: DeviceOut
    tokens: TokenPair


class SyncStateOut(BaseModel):
    revision: int
    checksum: str
    size: int
    updated_at: UtcDateTime | None
    device_id: str | None


class RevisionOut(BaseModel):
    revision: int
    checksum: str
    size: int
    device_id: str | None
    created_at: UtcDateTime


class PushResultOut(BaseModel):
    revision: int
    checksum: str


class ConflictOut(BaseModel):
    detail: str = "revision_conflict"
    current_revision: int
    current_checksum: str


class SubscriptionIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    url: str = Field(default="", max_length=2048)
    site_url: str = Field(default="", max_length=512)
    account: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=256)
    note: str = Field(default="", max_length=1024)
    enabled: bool = True
    expire_at: datetime | None = None
    traffic_used: int = Field(default=0, ge=0)
    traffic_total: int = Field(default=0, ge=0)


class SubscriptionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    url: str | None = Field(default=None, max_length=2048)
    site_url: str | None = Field(default=None, max_length=512)
    account: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=256)
    note: str | None = Field(default=None, max_length=1024)
    enabled: bool | None = None
    expire_at: datetime | None = None
    traffic_used: int | None = Field(default=None, ge=0)
    traffic_total: int | None = Field(default=None, ge=0)


class SubscriptionPreviewIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class SubscriptionPreviewOut(BaseModel):
    name: str
    site_url: str
    traffic_used: int
    traffic_total: int
    expire_at: UtcDateTime | None


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    url: str
    site_url: str
    account: str
    password: str
    note: str
    enabled: bool
    expire_at: UtcDateTime | None
    traffic_used: int
    traffic_total: int
    created_at: UtcDateTime
    updated_at: UtcDateTime


class ProfilePayloadIn(BaseModel):
    profile_id: str = Field(min_length=1, max_length=32)
    label: str = Field(default="", max_length=128)
    url: str = Field(default="", max_length=2048)
    type: str = Field(default="file", max_length=16)
    content: str = Field(default="", description="base64 of the profile yaml")
    sort_order: int = 0


class ProfileSyncIn(BaseModel):
    since: int = Field(default=0, ge=0)
    upserts: list[ProfilePayloadIn] = Field(default_factory=list)
    deletes: list[str] = Field(default_factory=list)


class ProfileOut(BaseModel):
    profile_id: str
    label: str
    url: str
    type: str
    content: str
    checksum: str
    sort_order: int
    revision: int


class ProfileSyncOut(BaseModel):
    revision: int
    upserts: list[ProfileOut]
    tombstones: list[str]
