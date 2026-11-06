"""Per-profile sync.

One row per subscription, keyed by the id the client generated. A delete
leaves a tombstone rather than removing the row, so the next device that
syncs removes it too instead of pushing it back.
"""

from __future__ import annotations

import base64
import hashlib

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, get_principal
from ..models import ProfileState, SyncRevision
from ..schemas import ProfileOut, ProfileSyncIn, ProfileSyncOut

router = APIRouter(prefix="/sync/profiles", tags=["sync"])


def _counter(db: Session, user_id: str) -> SyncRevision:
    row = db.get(SyncRevision, user_id)
    if row is None:
        row = SyncRevision(user_id=user_id, revision=0)
        db.add(row)
        db.flush()
    return row


def _next(counter: SyncRevision) -> int:
    counter.revision += 1
    return counter.revision


def _checksum(label: str, url: str, kind: str, content: bytes) -> str:
    digest = hashlib.sha256()
    for part in (label, url, kind):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    digest.update(content)
    return digest.hexdigest()


def _row(db: Session, user_id: str, profile_id: str) -> ProfileState | None:
    return db.scalar(
        select(ProfileState).where(
            ProfileState.user_id == user_id, ProfileState.profile_id == profile_id
        )
    )


def _changes(db: Session, user_id: str, since: int, revision: int) -> ProfileSyncOut:
    rows = db.scalars(
        select(ProfileState).where(
            ProfileState.user_id == user_id, ProfileState.revision > since
        )
    ).all()
    upserts = [
        ProfileOut(
            profile_id=row.profile_id,
            label=row.label,
            url=row.url,
            type=row.type,
            content=base64.b64encode(row.content or b"").decode(),
            checksum=row.checksum,
            sort_order=row.sort_order,
            revision=row.revision,
        )
        for row in rows
        if not row.deleted
    ]
    tombstones = [row.profile_id for row in rows if row.deleted]
    return ProfileSyncOut(revision=revision, upserts=upserts, tombstones=tombstones)


@router.get("", response_model=ProfileSyncOut)
def pull(
    since: int = Query(default=0, ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> ProfileSyncOut:
    counter = _counter(db, principal.user.id)
    db.commit()
    return _changes(db, principal.user.id, since, counter.revision)


@router.post("", response_model=ProfileSyncOut)
def push(
    payload: ProfileSyncIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> ProfileSyncOut:
    user_id = principal.user.id
    counter = _counter(db, user_id)

    for item in payload.upserts:
        content = base64.b64decode(item.content) if item.content else b""
        checksum = _checksum(item.label, item.url, item.type, content)
        row = _row(db, user_id, item.profile_id)
        if row is None:
            db.add(
                ProfileState(
                    user_id=user_id,
                    profile_id=item.profile_id,
                    label=item.label,
                    url=item.url,
                    type=item.type,
                    content=content,
                    checksum=checksum,
                    sort_order=item.sort_order,
                    revision=_next(counter),
                )
            )
            continue
        # Same content on an unchanged row is a no-op; a tombstone with the
        # same content still means the device re-created it.
        if not row.deleted and row.checksum == checksum:
            continue
        row.label = item.label
        row.url = item.url
        row.type = item.type
        row.content = content
        row.checksum = checksum
        row.sort_order = item.sort_order
        row.deleted = False
        row.revision = _next(counter)

    for profile_id in payload.deletes:
        row = _row(db, user_id, profile_id)
        if row is None or row.deleted:
            continue
        row.deleted = True
        row.content = None
        row.revision = _next(counter)

    db.commit()
    return _changes(db, user_id, payload.since, counter.revision)
