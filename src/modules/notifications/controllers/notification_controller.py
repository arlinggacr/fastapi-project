"""Notification routes: /notifications/*"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.responses import not_found
from src.database.session import get_session
from src.modules.notifications.dtos.notification_response import NotificationResponse
from src.modules.notifications.entities.notification import Notification
from src.modules.notifications.repositories.notification_repository import (
    NotificationRepository,
)
from src.modules.users.entities.user import User
from src.utils.deps import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Notification]:
    return await NotificationRepository(session).list_for_user(
        user.id, unread_only=unread_only, limit=limit
    )


@router.get("/unread-count")
async def unread_count(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    count = await NotificationRepository(session).count_unread(user.id)
    return {"unread": count}


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    notification_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    repo = NotificationRepository(session)
    notification = await repo.get_by_id(notification_id)
    if notification is None or notification.user_id != user.id:
        raise not_found("Notification")
    await repo.mark_read(notification)
    await repo.commit()
