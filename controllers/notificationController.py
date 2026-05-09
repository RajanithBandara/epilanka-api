"""
Notification Controller
Handles all notification database operations for MongoDB
"""

from datetime import datetime, timezone
from config.db import get_database
from models.notificationModel import NotificationCreate, NotificationUpdate
import uuid


def get_database_connection():
    """Get MongoDB database connection"""
    return get_database()


def create_notification(notification_data: NotificationCreate) -> dict:
    """
    Create a new notification in the database
    
    Args:
        notification_data: NotificationCreate object with notification details
        
    Returns:
        dict: Created notification document with _id
    """
    db = get_database_connection()
    notifications = db["notifications"]
    
    doc = {
        "notification_id": notification_data.notification_id if hasattr(notification_data, 'notification_id') else f"notif_{uuid.uuid4().hex[:12]}",
        "text": notification_data.text,
        "severity": notification_data.severity.value if hasattr(notification_data.severity, 'value') else notification_data.severity,
        "user_id": notification_data.user_id,
        "created_at": datetime.now(timezone.utc),
        "read": False,
        "read_at": None,
        "metadata": notification_data.metadata or {},
    }
    
    result = notifications.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc


def get_notification_by_id(notification_id: str, user_id: str) -> dict | None:
    """
    Get a specific notification by ID for a user
    
    Args:
        notification_id: The notification_id field
        user_id: The user to retrieve for
        
    Returns:
        dict: Notification document or None if not found
    """
    db = get_database_connection()
    notifications = db["notifications"]
    
    notification = notifications.find_one({
        "notification_id": notification_id,
        "$or": [
            {"user_id": user_id},
            {"user_id": None}
        ]
    })
    
    if notification:
        notification["_id"] = str(notification["_id"])
    
    return notification


def get_user_notifications(user_id: str, skip: int = 0, limit: int = 20, unread_only: bool = False) -> tuple[list, int]:
    """
    Get notifications for a specific user, paginated
    
    Args:
        user_id: The user ID
        skip: Number of records to skip for pagination
        limit: Maximum number of records to return
        unread_only: If True, only return unread notifications
        
    Returns:
        tuple: (list of notifications, total count)
    """
    db = get_database_connection()
    notifications = db["notifications"]
    
    query = {
        "$or": [
            {"user_id": user_id},
            {"user_id": None}
        ]
    }
    
    if unread_only:
        query["read"] = False
    
    # Count total matching documents
    total = notifications.count_documents(query)
    
    # Find with pagination, sorted by created_at descending (newest first)
    notif_list = list(notifications.find(query)
                     .sort("created_at", -1)
                     .skip(skip)
                     .limit(limit))
    
    for notif in notif_list:
        notif["_id"] = str(notif["_id"])
    
    return notif_list, total


def mark_notification_as_read(notification_id: str, user_id: str) -> bool:
    """
    Mark a notification as read
    
    Args:
        notification_id: The notification_id field
        user_id: The user ID
        
    Returns:
        bool: True if updated, False if not found
    """
    db = get_database_connection()
    notifications = db["notifications"]
    
    result = notifications.update_one(
        {
            "notification_id": notification_id,
            "$or": [
                {"user_id": user_id},
                {"user_id": None}
            ]
        },
        {
            "$set": {
                "read": True,
                "read_at": datetime.now(timezone.utc)
            }
        }
    )
    
    return result.modified_count > 0


def update_notification(notification_id: str, user_id: str, update_data: NotificationUpdate) -> bool:
    """
    Update a notification for a user.

    Supports editing text, severity, metadata and read state.
    """
    db = get_database_connection()
    notifications = db["notifications"]

    update_fields: dict = {}

    if update_data.text is not None:
        update_fields["text"] = update_data.text

    if update_data.severity is not None:
        update_fields["severity"] = update_data.severity.value if hasattr(update_data.severity, 'value') else update_data.severity

    if update_data.metadata is not None:
        update_fields["metadata"] = update_data.metadata

    if update_data.read is not None:
        update_fields["read"] = update_data.read
        update_fields["read_at"] = datetime.now(timezone.utc) if update_data.read else None

    if not update_fields:
        return False

    result = notifications.update_one(
        {
            "notification_id": notification_id,
            "$or": [
                {"user_id": user_id},
                {"user_id": None}
            ]
        },
        {
            "$set": update_fields
        }
    )

    return result.modified_count > 0


def mark_all_notifications_as_read(user_id: str) -> int:
    """
    Mark all notifications for a user as read
    
    Args:
        user_id: The user ID
        
    Returns:
        int: Number of notifications marked as read
    """
    db = get_database_connection()
    notifications = db["notifications"]
    
    result = notifications.update_many(
        {
            "read": False,
            "$or": [
                {"user_id": user_id},
                {"user_id": None}
            ]
        },
        {
            "$set": {
                "read": True,
                "read_at": datetime.now(timezone.utc)
            }
        }
    )
    
    return result.modified_count


def get_unread_count(user_id: str) -> int:
    """
    Get count of unread notifications for a user
    
    Args:
        user_id: The user ID
        
    Returns:
        int: Count of unread notifications
    """
    db = get_database_connection()
    notifications = db["notifications"]
    
    count = notifications.count_documents({
        "read": False,
        "$or": [
            {"user_id": user_id},
            {"user_id": None}
        ]
    })
    
    return count


def delete_notification(notification_id: str, user_id: str) -> bool:
    """
    Delete a notification
    
    Args:
        notification_id: The notification_id field
        user_id: The user ID
        
    Returns:
        bool: True if deleted, False if not found
    """
    db = get_database_connection()
    notifications = db["notifications"]
    
    result = notifications.delete_one({
        "notification_id": notification_id,
        "$or": [
            {"user_id": user_id},
            {"user_id": None}
        ]
    })
    
    return result.deleted_count > 0


def delete_all_user_notifications(user_id: str) -> int:
    """
    Delete all notifications for a user
    
    Args:
        user_id: The user ID
        
    Returns:
        int: Number of notifications deleted
    """
    db = get_database_connection()
    notifications = db["notifications"]
    
    result = notifications.delete_many({
        "$or": [
            {"user_id": user_id},
            {"user_id": None}
        ]
    })
    
    return result.deleted_count


def broadcast_notification_to_all(notification_data: NotificationCreate) -> dict:
    """
    Create a notification that will be broadcast to all users
    (user_id will be None)
    
    Args:
        notification_data: NotificationCreate object
        
    Returns:
        dict: Created notification document
    """
    notification_data.user_id = None
    return create_notification(notification_data)
