"""
Notification Routes - REST API and WebSocket endpoints
Handles notifications: listing, marking as read, WebSocket subscriptions
"""

import os
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status, Query
from pydantic import BaseModel

from controllers.notificationController import (
    create_notification,
    get_notification_by_id,
    get_user_notifications,
    update_notification,
    mark_notification_as_read,
    mark_all_notifications_as_read,
    get_unread_count,
    delete_notification,
    broadcast_notification_to_all,
)
from models.notificationModel import NotificationCreate, NotificationResponse, NotificationUpdate
from utils.auth_deps import get_current_user, AppwriteUser
from utils.appwrite_client import get_account_service
from utils.websocket_manager import notification_manager

router = APIRouter(prefix="/notifications", tags=["notifications"])

API_KEY = os.getenv("API_SECRET_KEY")


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
        
        # Broadcast via WebSocket
        if notification_obj.user_id:
            # Send to specific user
            await notification_manager.broadcast_to_user(
                notification_obj.user_id,
                {
                    "_id": created.get("_id"),
                    "notification_id": created.get("notification_id"),
                    "text": created.get("text"),
                    "severity": created.get("severity"),
                    "created_at": created.get("created_at").isoformat() if created.get("created_at") else None,
                }
            )
        else:
            # Broadcast to all
            await notification_manager.broadcast_to_all({
                "_id": created.get("_id"),
                "notification_id": created.get("notification_id"),
                "text": created.get("text"),
                "severity": created.get("severity"),
                "created_at": created.get("created_at").isoformat() if created.get("created_at") else None,
            })
        
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

        return {"message": "Notification updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update notification: {str(e)}"
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


@router.delete("/{notification_id}", status_code=status.HTTP_200_OK)
async def delete_single_notification(
    notification_id: str,
    user: AppwriteUser = Depends(get_current_user)
):
    """
    Delete a specific notification
    """
    try:
        success = delete_notification(notification_id, user["$id"])
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found"
            )
        
        return {"message": "Notification deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete notification: {str(e)}"
        )


# ── WebSocket Endpoint ──────────────────────────────────────────────────────


@router.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    """
    WebSocket endpoint for real-time notifications
    Client connects with JWT token: ws://localhost:8000/notifications/ws/{jwt_token}
    """
    try:
        # Verify Appwrite JWT and extract user ID
        account = get_account_service(token)
        user_obj = account.get()
        user_id = getattr(user_obj, "id", None) or getattr(user_obj, "$id", None)
        
        if not user_id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        
        # Register the connection
        await notification_manager.connect(websocket, user_id)
        
        # Send initial connection message
        await notification_manager.send_status_update(user_id)
        
        # Keep the connection alive and listen for disconnections
        try:
            while True:
                # Wait for messages from client (heartbeat/keepalive)
                data = await websocket.receive_text()

                if data == "ping":
                    await websocket.send_text("pong")
        
        except WebSocketDisconnect:
            notification_manager.disconnect(websocket, user_id)
    
    except Exception as e:
        try:
            await websocket.close(code=status.WS_1011_SERVER_ERROR)
        except:
            pass
        print(f"WebSocket error: {e}")
