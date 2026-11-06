"""Subscriptions, as the account console manages them.

The sync snapshot stays opaque, so this is the structured side of the same
data: what the airport is called, where its site is, and which account was
bought there. Only the owner of the account can read these rows back.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, get_principal
from ..models import Subscription, utcnow
from ..schemas import SubscriptionIn, SubscriptionOut, SubscriptionPatch

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def _owned(db: Session, user_id: str, subscription_id: str) -> Subscription:
    subscription = db.get(Subscription, subscription_id)
    if subscription is None or subscription.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="subscription_not_found")
    return subscription


@router.get("", response_model=list[SubscriptionOut])
def list_subscriptions(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[SubscriptionOut]:
    rows = db.scalars(
        select(Subscription)
        .where(Subscription.user_id == principal.user.id)
        .order_by(Subscription.created_at)
    ).all()
    return [SubscriptionOut.model_validate(row) for row in rows]


@router.post("", response_model=SubscriptionOut, status_code=status.HTTP_201_CREATED)
def create_subscription(
    payload: SubscriptionIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    subscription = Subscription(user_id=principal.user.id, **payload.model_dump())
    db.add(subscription)
    db.commit()
    return SubscriptionOut.model_validate(subscription)


@router.patch("/{subscription_id}", response_model=SubscriptionOut)
def update_subscription(
    subscription_id: str,
    payload: SubscriptionPatch,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    subscription = _owned(db, principal.user.id, subscription_id)
    changes = payload.model_dump(exclude_unset=True)
    # Explicit null clears only the nullable field; the rest keep their value
    # rather than being written as NULL.
    if changes.get("name", "") is None:
        changes.pop("name", None)
    for field in ("url", "site_url", "account", "password", "note"):
        if field in changes and changes[field] is None:
            changes[field] = ""
    for field, value in changes.items():
        setattr(subscription, field, value)
    subscription.updated_at = utcnow()
    db.commit()
    return SubscriptionOut.model_validate(subscription)


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription(
    subscription_id: str,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> None:
    subscription = _owned(db, principal.user.id, subscription_id)
    db.delete(subscription)
    db.commit()
