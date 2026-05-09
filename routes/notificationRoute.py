"""
Notification Routes - REST API endpoints.
Handles notification CRUD and read state operations.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query

from controllers.notificationController import (
    create_notification,
    get_notification_by_id,
    get_user_notifications,
    update_notification,
    mark_notification_as_read,
    mark_all_notifications_as_read,
    get_unread_count,
    delete_notification,
)
from models.notificationModel import NotificationCreate, NotificationUpdate
from utils.auth_deps import get_current_user, AppwriteUser
from utils.websocket_manager import notification_manager

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _serialize_notification(notification: dict | None) -> dict | None:
    if not notification:
        return None

    return {
        "_id": notification.get("_id"),
        "notification_id": notification.get("notification_id"),
        "text": notification.get("text"),
        "severity": notification.get("severity"),
        "user_id": notification.get("user_id"),
        "created_at": notification.get("created_at").isoformat() if notification.get("created_at") else None,
        "read": bool(notification.get("read", False)),
        "read_at": notification.get("read_at").isoformat() if notification.get("read_at") else None,
        "metadata": notification.get("metadata") or {},
    }


async def _emit_notification_event(event_name: str, payload: dict):
    target_user_id = payload.get("user_id")

    if target_user_id:
        await notification_manager.broadcast_to_user(target_user_id, payload, event_name=event_name)
        return

    await notification_manager.broadcast_to_all(payload, event_name=event_name)


# ── REST API Endpoints ──────────────────────────────────────────────────────


@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_new_notification(
    notification_data: NotificationCreate,
    user: AppwriteUser = Depends(get_current_user)
):
    """
    Create a new notification
    If user_id is None, it's broadcast to all users
    """
    try:
        # Generate a unique notification_id if not provided
        notification_obj = NotificationCreate(
            **notification_data.model_dump()
        )
        
        created = create_notification(notification_obj)

        emit_payload = _serialize_notification(created)
        
        # Broadcast via Socket.IO
        await _emit_notification_event("notification", emit_payload)
        
        return {
            "message": "Notification created successfully",
            "notification": created
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create notification: {str(e)}"
        )


@router.get("/", response_model=dict)
async def get_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    user: AppwriteUser = Depends(get_current_user)
):
    """
    Get notifications for the current user
    Supports pagination and filtering by read status
    """
    try:
        notifications, total = get_user_notifications(
            user_id=user["$id"],
            skip=skip,
            limit=limit,
            unread_only=unread_only
        )
        
        return {
            "items": notifications,
            "total": total,
            "skip": skip,
            "limit": limit
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch notifications: {str(e)}"
        )


@router.get("/unread/count")
async def get_unread_notification_count(
    user: AppwriteUser = Depends(get_current_user)
):
    """
    Get the count of unread notifications for the current user
    """
    try:
        count = get_unread_count(user["$id"])
        return {
            "unread_count": count
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get unread count: {str(e)}"
        )


@router.put("/{notification_id}/read", status_code=status.HTTP_200_OK)
async def mark_read(
    notification_id: str,
    user: AppwriteUser = Depends(get_current_user)
):
    """
    Mark a notification as read
    """
    try:
        success = mark_notification_as_read(notification_id, user["$id"])
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found"
            )
        
        return {"message": "Notification marked as read"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark notification as read: {str(e)}"
        )


@router.put("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_read(
    user: AppwriteUser = Depends(get_current_user)
):
    """
    Mark all notifications as read for the current user
    """
    try:
        count = mark_all_notifications_as_read(user["$id"])

        return {
            "message": "All notifications marked as read",
            "count": count
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark notifications as read: {str(e)}"
        )


@router.put("/{notification_id}", status_code=status.HTTP_200_OK)
async def update_single_notification(
    notification_id: str,
    payload: NotificationUpdate,
    user: AppwriteUser = Depends(get_current_user)
):
    """
    Update a specific notification (text/severity/metadata/read).
    """
    try:
        success = update_notification(notification_id, user["$id"], payload)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found or no changes applied"
            )

        updated_notification = get_notification_by_id(notification_id, user["$id"])
        emit_payload = _serialize_notification(updated_notification)
        if emit_payload:
            await _emit_notification_event("notification_updated", emit_payload)

        return {
            "message": "Notification updated",
            "notification": updated_notification,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update notification: {str(e)}"
        )


@router.delete("/{notification_id}", status_code=status.HTTP_200_OK)
async def delete_single_notification(
    notification_id: str,
    user: AppwriteUser = Depends(get_current_user)
):
    """
    Delete a specific notification
    """
    try:
        notification = get_notification_by_id(notification_id, user["$id"])
        success = delete_notification(notification_id, user["$id"])
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found"
            )
        
        emit_payload = {
            "notification_id": notification_id,
            "user_id": notification.get("user_id") if notification else None,
        }
        await _emit_notification_event("notification_deleted", emit_payload)

        return {"message": "Notification deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete notification: {str(e)}"
        )


# Socket.IO endpoint is mounted globally at /socket.io by main.py.
