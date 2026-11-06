"""Versioned snapshot storage.

Every write names the revision it was based on. A stale base is rejected with
409 instead of overwriting, so the second of two devices that synced at the
same time is told to pull before it pushes. That is the whole concurrency
model: no merge server-side, but a lost update is impossible.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import Principal, get_principal
from ..models import Vault, VaultRevision, utcnow
from ..schemas import PushResultOut, RevisionOut, SyncStateOut

router = APIRouter(prefix="/sync", tags=["sync"])


def _checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _conflict(vault: Vault) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "detail": "revision_conflict",
            "current_revision": vault.revision,
            "current_checksum": vault.checksum,
        },
    )


def _store(
    db: Session,
    *,
    user_id: str,
    device_id: str,
    content: bytes,
    keep: int,
) -> Vault:
    vault = db.execute(
        select(Vault).where(Vault.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    checksum = _checksum(content)
    if vault is None:
        vault = Vault(user_id=user_id, revision=1)
        db.add(vault)
    else:
        vault.revision += 1
    vault.checksum = checksum
    vault.size = len(content)
    vault.content = content
    vault.device_id = device_id
    vault.updated_at = utcnow()
    db.add(
        VaultRevision(
            user_id=user_id,
            revision=vault.revision,
            checksum=checksum,
            size=len(content),
            content=content,
            device_id=device_id,
        )
    )
    db.flush()
    if keep > 0:
        db.execute(
            delete(VaultRevision).where(
                VaultRevision.user_id == user_id,
                VaultRevision.revision <= vault.revision - keep,
            )
        )
    return vault


@router.get("/state", response_model=SyncStateOut)
def read_state(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> SyncStateOut:
    vault = db.get(Vault, principal.user.id)
    if vault is None:
        return SyncStateOut(
            revision=0, checksum="", size=0, updated_at=None, device_id=None
        )
    return SyncStateOut(
        revision=vault.revision,
        checksum=vault.checksum,
        size=vault.size,
        updated_at=vault.updated_at,
        device_id=vault.device_id,
    )


@router.get("/snapshot")
def read_snapshot(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> Response:
    vault = db.get(Vault, principal.user.id)
    if vault is None or vault.content is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no_snapshot")
    return Response(
        content=vault.content,
        media_type="application/octet-stream",
        headers={
            "X-Revision": str(vault.revision),
            "X-Checksum": vault.checksum,
            "X-Updated-At": vault.updated_at.isoformat(),
        },
    )


@router.put("/snapshot", response_model=PushResultOut)
async def write_snapshot(
    request: Request,
    base_revision: int = Query(ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PushResultOut:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit():
        if int(declared) > settings.max_snapshot_bytes:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="too_large")
    content = await request.body()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="empty_snapshot")
    if len(content) > settings.max_snapshot_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="too_large")

    current = db.execute(
        select(Vault).where(Vault.user_id == principal.user.id).with_for_update()
    ).scalar_one_or_none()
    if (current.revision if current else 0) != base_revision:
        raise _conflict(current) if current else HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"detail": "revision_conflict", "current_revision": 0, "current_checksum": ""},
        )

    vault = _store(
        db,
        user_id=principal.user.id,
        device_id=principal.device.id,
        content=content,
        keep=settings.history_limit,
    )
    db.commit()
    return PushResultOut(revision=vault.revision, checksum=vault.checksum)


@router.get("/history", response_model=list[RevisionOut])
def list_history(
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[RevisionOut]:
    rows = db.scalars(
        select(VaultRevision)
        .where(VaultRevision.user_id == principal.user.id)
        .order_by(VaultRevision.revision.desc())
        .limit(limit)
    ).all()
    return [
        RevisionOut(
            revision=row.revision,
            checksum=row.checksum,
            size=row.size,
            device_id=row.device_id,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/history/{revision}")
def read_revision(
    revision: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Response:
    row = db.scalar(
        select(VaultRevision).where(
            VaultRevision.user_id == principal.user.id,
            VaultRevision.revision == revision,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="revision_not_found")
    return Response(
        content=row.content,
        media_type="application/octet-stream",
        headers={"X-Revision": str(row.revision), "X-Checksum": row.checksum},
    )


@router.post("/restore/{revision}", response_model=PushResultOut)
def restore_revision(
    revision: int,
    base_revision: int = Query(ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PushResultOut:
    row = db.scalar(
        select(VaultRevision).where(
            VaultRevision.user_id == principal.user.id,
            VaultRevision.revision == revision,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="revision_not_found")
    current = db.get(Vault, principal.user.id)
    if (current.revision if current else 0) != base_revision:
        raise _conflict(current) if current else HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"detail": "revision_conflict", "current_revision": 0, "current_checksum": ""},
        )
    vault = _store(
        db,
        user_id=principal.user.id,
        device_id=principal.device.id,
        content=row.content,
        keep=settings.history_limit,
    )
    db.commit()
    return PushResultOut(revision=vault.revision, checksum=vault.checksum)
