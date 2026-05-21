"""
Notification Routes — REST API endpoints.
All notifications are global broadcasts (no user targeting).
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional

from controllers.notificationController import (
    create_notification,
    get_notification_by_id,
    get_all_notifications,
    update_notification,
    mark_notification_as_read,
    mark_all_notifications_as_read,
    get_unread_count,
    delete_notification,
    delete_all_notifications,
)
from models.notificationModel import NotificationCreate, NotificationUpdate
from utils.auth_deps import get_current_user, AppwriteUser
from utils.websocket_manager import notification_manager

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _safe_serialize(notification: dict | None) -> dict | None:
    """
    Ensure every field in the notification dict is JSON-safe.
    Datetimes should already be strings (handled by the controller's
    _serialize_doc), but this acts as a defensive guard.
    """
    if not notification:
        return None

    from datetime import datetime

    result = dict(notification)
    for field in ("created_at", "read_at"):
        val = result.get(field)
        if isinstance(val, datetime):
            result[field] = val.isoformat()

    return result


# ── REST API Endpoints ──────────────────────────────────────────────────────


@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_new_notification(
    notification_data: NotificationCreate,
    user: AppwriteUser = Depends(get_current_user),
):
    """
    Create a new global broadcast notification.
    The notification is immediately pushed to all connected clients via Socket.IO.
    """
    try:
        created = create_notification(notification_data)
        safe = _safe_serialize(created)

        # Broadcast to ALL connected users immediately
        await notification_manager.broadcast_to_all(safe, event_name="notification")

        return {
            "message": "Notification created and broadcast successfully",
            "notification": safe,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create notification: {str(e)}",
        )


@router.get("/", response_model=dict)
async def get_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    since: Optional[str] = Query(None, description="ISO datetime — return only notifications after this time"),
    category: Optional[str] = Query(None, description="Filter by category (disease, report, system, alert, announcement)"),
    severity: Optional[str] = Query(None, description="Filter by severity (info, warning, critical, success)"),
    user: AppwriteUser = Depends(get_current_user),
):
    """
    Get global broadcast notifications with optional filters.
    Supports pagination, unread-only, delta-fetch (since), category and severity.
    """
    try:
        items, total = get_all_notifications(
            skip=skip,
            limit=limit,
            unread_only=unread_only,
            since=since,
            category=category,
            severity=severity,
        )

        return {
            "items": items,
            "total": total,
            "skip": skip,
            "limit": limit,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch notifications: {str(e)}",
        )


@router.get("/unread/count")
async def get_unread_notification_count(
    user: AppwriteUser = Depends(get_current_user),
):
    """Get the total count of unread global notifications."""
    try:
        count = get_unread_count()
        return {"unread_count": count}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get unread count: {str(e)}",
        )


# ── IMPORTANT: /read-all MUST be declared BEFORE /{notification_id} ─────────

@router.put("/read-all", status_code=status.HTTP_200_OK)
@router.post("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_read(
    user: AppwriteUser = Depends(get_current_user),
):
    """Mark ALL notifications as read."""
    try:
        count = mark_all_notifications_as_read()

        # Push updated unread count (0) to all connected clients instantly
        unread_after = get_unread_count()
        await notification_manager.broadcast_to_all(
            {"unread_count": unread_after},
            event_name="unread_count_updated",
        )

        return {
            "message": "All notifications marked as read",
            "count": count,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark notifications as read: {str(e)}",
        )


@router.delete("/all", status_code=status.HTTP_200_OK)
async def delete_all(
    user: AppwriteUser = Depends(get_current_user),
):
    """Delete ALL notifications from the system."""
    try:
        count = delete_all_notifications()
        return {
            "message": "All notifications deleted",
            "count": count,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete notifications: {str(e)}",
        )


@router.put("/{notification_id}/read", status_code=status.HTTP_200_OK)
async def mark_read(
    notification_id: str,
    user: AppwriteUser = Depends(get_current_user),
):
    """Mark a single notification as read."""
    try:
        success = mark_notification_as_read(notification_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )

        unread_after = get_unread_count()
        await notification_manager.broadcast_to_all(
            {"unread_count": unread_after},
            event_name="unread_count_updated",
        )

        return {"message": "Notification marked as read"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark notification as read: {str(e)}",
        )


@router.put("/{notification_id}", status_code=status.HTTP_200_OK)
async def update_single_notification(
    notification_id: str,
    payload: NotificationUpdate,
    user: AppwriteUser = Depends(get_current_user),
):
    """Update a notification's text, title, severity, category, metadata or read state."""
    try:
        success = update_notification(notification_id, payload)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found or no changes applied",
            )

        updated = get_notification_by_id(notification_id)
        safe = _safe_serialize(updated)
        if safe:
            await notification_manager.broadcast_to_all(safe, event_name="notification_updated")

        return {
            "message": "Notification updated",
            "notification": safe,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update notification: {str(e)}",
        )


@router.delete("/{notification_id}", status_code=status.HTTP_200_OK)
async def delete_single_notification(
    notification_id: str,
    user: AppwriteUser = Depends(get_current_user),
):
    """Delete a specific notification."""
    try:
        success = delete_notification(notification_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )

        await notification_manager.broadcast_to_all(
            {"notification_id": notification_id},
            event_name="notification_deleted",
        )

        return {"message": "Notification deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete notification: {str(e)}",
        )


@router.get("/{notification_id}", response_model=dict)
async def get_single_notification(
    notification_id: str,
    user: AppwriteUser = Depends(get_current_user),
):
    """Get a single notification by its notification_id."""
    try:
        notif = get_notification_by_id(notification_id)
        if not notif:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )
        return {"notification": _safe_serialize(notif)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch notification: {str(e)}",
        )
