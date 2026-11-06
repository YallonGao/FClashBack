"""Devices signed in to one account."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, get_principal
from ..models import Device
from ..schemas import DeviceOut

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", response_model=list[DeviceOut])
def list_devices(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[DeviceOut]:
    devices = db.scalars(
        select(Device)
        .where(Device.user_id == principal.user.id)
        .order_by(Device.created_at)
    ).all()
    return [DeviceOut.model_validate(device) for device in devices]


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_device(
    device_id: str,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> None:
    device = db.get(Device, device_id)
    if device is None or device.user_id != principal.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="device_not_found")
    if device.id == principal.device.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="cannot_revoke_current")
    device.revoked = True
    db.commit()
