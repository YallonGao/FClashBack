"""Cloud items: an upload/select catalogue, plus the conflicts it produces.

The server is a data source only. It never queues work for a device: a device
reports what it holds, uploads what its owner picked, and pulls whatever
changed. When an upload was based on a version the server no longer has —
including the case where the item was deleted meanwhile — the upload is kept
aside as a conflict for a person to resolve in the console instead of
silently overwriting.
"""

from __future__ import annotations

import base64
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, get_principal
from ..models import (
    CloudConflict,
    CloudItem,
    Device,
    DeviceHolding,
    SyncRevision,
    utcnow,
)
from ..schemas import (
    CloudCheckIn,
    CloudCheckOut,
    CloudConflictOut,
    CloudItemAdminOut,
    CloudItemOut,
    CloudSyncIn,
    CloudSyncOut,
    CloudTombstone,
    CloudUploadIn,
    ResolveConflictIn,
)

router = APIRouter(prefix="/cloud", tags=["cloud"])


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


def _item(db: Session, user_id: str, kind: str, item_id: str) -> CloudItem | None:
    return db.scalar(
        select(CloudItem).where(
            CloudItem.user_id == user_id,
            CloudItem.kind == kind,
            CloudItem.item_id == item_id,
        )
    )


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _checksum(title: str, content: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(title.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(content)
    return digest.hexdigest()


def _out(item: CloudItem) -> CloudItemOut:
    return CloudItemOut(
        kind=item.kind,
        item_id=item.item_id,
        title=item.title,
        content=base64.b64encode(item.content or b"").decode(),
        checksum=item.checksum,
        content_hash=_content_hash(item.content or b""),
        revision=item.revision,
        uploader_device_id=item.uploader_device_id,
    )


def _conflict_out(row: CloudConflict) -> CloudConflictOut:
    return CloudConflictOut(
        kind=row.kind,
        item_id=row.item_id,
        cloud_title=row.cloud_title,
        cloud_content=base64.b64encode(row.cloud_content or b"").decode(),
        cloud_checksum=row.cloud_checksum,
        cloud_deleted=row.cloud_deleted,
        device_title=row.device_title,
        device_content=base64.b64encode(row.device_content or b"").decode(),
        device_checksum=row.device_checksum,
        device_id=row.device_id,
        created_at=row.created_at,
    )


def _record_conflict(
    db: Session,
    *,
    user_id: str,
    row: CloudItem | None,
    upload: CloudUploadIn,
    content: bytes,
    checksum: str,
    device_id: str,
) -> None:
    existing = db.scalar(
        select(CloudConflict).where(
            CloudConflict.user_id == user_id,
            CloudConflict.kind == upload.kind,
            CloudConflict.item_id == upload.item_id,
        )
    )
    if existing is None:
        existing = CloudConflict(
            user_id=user_id, kind=upload.kind, item_id=upload.item_id
        )
        db.add(existing)
    existing.cloud_title = row.title if row else ""
    existing.cloud_content = row.content if row else b""
    existing.cloud_checksum = row.checksum if row else ""
    existing.cloud_deleted = bool(row.deleted) if row else False
    existing.device_title = upload.title
    existing.device_content = content
    existing.device_checksum = checksum
    existing.device_id = device_id
    existing.created_at = utcnow()


@router.post("/sync", response_model=CloudSyncOut)
def sync(
    payload: CloudSyncIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CloudSyncOut:
    user_id = principal.user.id
    counter = _counter(db, user_id)

    for upload in payload.uploads:
        content = base64.b64decode(upload.content) if upload.content else b""
        checksum = _checksum(upload.title, content)
        row = _item(db, user_id, upload.kind, upload.item_id)

        if row is None:
            db.add(
                CloudItem(
                    user_id=user_id,
                    kind=upload.kind,
                    item_id=upload.item_id,
                    title=upload.title,
                    content=content,
                    checksum=checksum,
                    uploader_device_id=principal.device.id,
                    revision=_next(counter),
                )
            )
            continue

        if not row.deleted and row.checksum == checksum:
            continue

        # Deleted in the cloud while this device was editing it, or edited
        # from a version the cloud no longer has: keep both and let a person
        # decide. An empty base means an older client that cannot say.
        stale = bool(upload.base_checksum) and upload.base_checksum != row.checksum
        if row.deleted or stale:
            _record_conflict(
                db,
                user_id=user_id,
                row=row,
                upload=upload,
                content=content,
                checksum=checksum,
                device_id=principal.device.id,
            )
            continue

        row.title = upload.title
        row.content = content
        row.checksum = checksum
        row.uploader_device_id = principal.device.id
        row.deleted = False
        row.revision = _next(counter)

    # Holdings are replaced per kind that the device reported, so a kind the
    # client does not know about yet keeps its rows.
    now = utcnow()
    for kind, item_ids in payload.holdings.items():
        db.execute(
            delete(DeviceHolding).where(
                DeviceHolding.device_id == principal.device.id,
                DeviceHolding.kind == kind,
            )
        )
        for item_id in sorted(set(item_ids)):
            db.add(
                DeviceHolding(
                    device_id=principal.device.id,
                    kind=kind,
                    item_id=item_id,
                    user_id=user_id,
                    last_seen_at=now,
                )
            )

    db.commit()

    changed = db.scalars(
        select(CloudItem).where(
            CloudItem.user_id == user_id, CloudItem.revision > payload.since
        )
    ).all()
    conflicts = db.scalars(
        select(CloudConflict).where(CloudConflict.user_id == user_id)
    ).all()
    return CloudSyncOut(
        revision=counter.revision,
        items=[_out(item) for item in changed if not item.deleted],
        tombstones=[
            CloudTombstone(kind=item.kind, item_id=item.item_id)
            for item in changed
            if item.deleted
        ],
        conflicts=[_conflict_out(row) for row in conflicts],
    )


@router.post("/check", response_model=CloudCheckOut)
def check(
    payload: CloudCheckIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CloudCheckOut:
    """Which of these hashes the cloud already holds.

    Content-addressed on purpose: a device can ask about the things it has
    without inventing an id for them, which is what rules and DNS lack.
    """
    wanted = {value for value in payload.checksums if value}
    if not wanted:
        return CloudCheckOut(present=[])
    rows = db.scalars(
        select(CloudItem.item_id).where(
            CloudItem.user_id == principal.user.id,
            CloudItem.kind == payload.kind,
            CloudItem.deleted.is_(False),
            CloudItem.item_id.in_(wanted),
        )
    ).all()
    return CloudCheckOut(present=list(rows))


@router.get("/items", response_model=list[CloudItemAdminOut])
def list_items(
    kind: str | None = Query(default=None),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[CloudItemAdminOut]:
    statement = select(CloudItem).where(
        CloudItem.user_id == principal.user.id, CloudItem.deleted.is_(False)
    )
    if kind:
        statement = statement.where(CloudItem.kind == kind)
    items = db.scalars(statement.order_by(CloudItem.updated_at.desc())).all()

    devices = {
        device.id: device
        for device in db.scalars(
            select(Device).where(Device.user_id == principal.user.id)
        ).all()
    }
    holdings = db.scalars(
        select(DeviceHolding).where(DeviceHolding.user_id == principal.user.id)
    ).all()
    by_item: dict[tuple[str, str], list[DeviceHolding]] = {}
    for holding in holdings:
        by_item.setdefault((holding.kind, holding.item_id), []).append(holding)

    result: list[CloudItemAdminOut] = []
    for item in items:
        uploader = devices.get(item.uploader_device_id or "")
        result.append(
            CloudItemAdminOut(
                kind=item.kind,
                item_id=item.item_id,
                title=item.title,
                checksum=item.checksum,
                content_hash=_content_hash(item.content or b""),
                revision=item.revision,
                uploader_device_id=item.uploader_device_id,
                uploader_name=(uploader.name or uploader.platform) if uploader else "",
                holders=[
                    {
                        "device_id": holding.device_id,
                        "name": devices[holding.device_id].name
                        if holding.device_id in devices
                        else "",
                        "last_seen_at": holding.last_seen_at,
                    }
                    for holding in by_item.get((item.kind, item.item_id), [])
                ],
            )
        )
    return result


@router.get("/conflicts", response_model=list[CloudConflictOut])
def list_conflicts(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[CloudConflictOut]:
    rows = db.scalars(
        select(CloudConflict).where(CloudConflict.user_id == principal.user.id)
    ).all()
    return [_conflict_out(row) for row in rows]


@router.post("/conflicts/{kind}/{item_id}/resolve", status_code=status.HTTP_204_NO_CONTENT)
def resolve_conflict(
    kind: str,
    item_id: str,
    payload: ResolveConflictIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> None:
    row = db.scalar(
        select(CloudConflict).where(
            CloudConflict.user_id == principal.user.id,
            CloudConflict.kind == kind,
            CloudConflict.item_id == item_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="conflict_not_found")

    if payload.keep == "uploaded":
        item = _item(db, principal.user.id, kind, item_id)
        if item is None:
            item = CloudItem(
                user_id=principal.user.id, kind=kind, item_id=item_id
            )
            db.add(item)
        item.title = row.device_title
        item.content = row.device_content or b""
        item.checksum = row.device_checksum
        item.deleted = False
        item.uploader_device_id = row.device_id
        item.revision = _next(_counter(db, principal.user.id))

    db.delete(row)
    db.commit()


@router.delete("/items/{kind}/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    kind: str,
    item_id: str,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> None:
    """Remove from the catalogue. Devices keep their local copy on purpose."""
    row = _item(db, principal.user.id, kind, item_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="item_not_found")
    counter = _counter(db, principal.user.id)
    row.deleted = True
    row.revision = _next(counter)
    db.commit()
