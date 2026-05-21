"""
Notification Controller
Handles broadcast notification database operations for MongoDB.
All notifications are global — they are delivered to every user.
"""

from datetime import datetime, timezone
from typing import Optional
from config.db import get_database
from models.notificationModel import NotificationCreate, NotificationUpdate
import uuid


def get_database_connection():
    """Get MongoDB database connection"""
    return get_database()


def _serialize_doc(doc: dict) -> dict:
    """
    Normalise a raw MongoDB notification document for API responses.
    - Converts ObjectId _id → plain string
    - Converts any datetime fields → ISO-8601 string
    - Guarantees the returned dict never contains raw datetime objects,
      so JSON serialisation never raises 'str has no isoformat' errors.
    """
    doc = dict(doc)

    if "_id" in doc:
        doc["_id"] = str(doc["_id"])

    for field in ("created_at", "read_at"):
        val = doc.get(field)
        if isinstance(val, datetime):
            doc[field] = val.isoformat()
        # If already a string or None, leave it alone

    # Ensure required fields have sensible defaults
    doc.setdefault("title", None)
    doc.setdefault("category", "system")
    doc.setdefault("metadata", {})
    doc.setdefault("read", False)
    doc.setdefault("read_at", None)

    return doc


# ── Write operations ─────────────────────────────────────────────────────────

def create_notification(notification_data: NotificationCreate) -> dict:
    """
    Insert a new broadcast notification and return the serialised document.

    Args:
        notification_data: Validated NotificationCreate payload

    Returns:
        Fully serialised notification dict (all datetimes as ISO strings)
    """
    db = get_database_connection()
    notifications = db["notifications"]

    now = datetime.now(timezone.utc)

    doc = {
        "notification_id": f"notif_{uuid.uuid4().hex[:12]}",
        "title": notification_data.title or None,
        "text": notification_data.text,
        "severity": (
            notification_data.severity.value
            if hasattr(notification_data.severity, "value")
            else notification_data.severity
        ),
        "category": (
            notification_data.category.value
            if hasattr(notification_data.category, "value")
            else notification_data.category
        ),
        "created_at": now,          # stored as datetime in MongoDB
        "read": False,
        "read_at": None,
        "metadata": notification_data.metadata or {},
    }

    result = notifications.insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    # Serialise datetimes AFTER capturing the inserted_id so the returned
    # dict is safe for JSON encoding.
    return _serialize_doc(doc)


def get_notification_by_id(notification_id: str) -> dict | None:
    """
    Get a specific broadcast notification by its notification_id.

    Args:
        notification_id: The notification_id field value

    Returns:
        Serialised notification dict or None
    """
    db = get_database_connection()
    notifications = db["notifications"]

    doc = notifications.find_one({"notification_id": notification_id})
    return _serialize_doc(doc) if doc else None


def get_all_notifications(
    skip: int = 0,
    limit: int = 20,
    unread_only: bool = False,
    since: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
) -> tuple[list, int]:
    """
    Fetch broadcast notifications with optional filters.

    Args:
        skip:        Pagination offset
        limit:       Max records to return (capped at 100)
        unread_only: If True, only return unread notifications
        since:       ISO datetime string — return only docs created after this
        category:    Filter by category string
        severity:    Filter by severity string

    Returns:
        (list of serialised notifications, total matching count)
    """
    db = get_database_connection()
    notifications = db["notifications"]

    query: dict = {}

    if unread_only:
        query["read"] = False

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            query["created_at"] = {"$gt": since_dt}
        except ValueError:
            pass  # malformed since — ignore, return full list

    if category:
        query["category"] = category

    if severity:
        query["severity"] = severity

    total = notifications.count_documents(query)

    notif_list = list(
        notifications.find(query)
        .sort("created_at", -1)
        .skip(skip)
        .limit(min(limit, 100))
    )

    return [_serialize_doc(n) for n in notif_list], total


def mark_notification_as_read(notification_id: str) -> bool:
    """
    Mark a single notification as read (global — not user-scoped).

    Returns:
        True if a document was updated, False if not found
    """
    db = get_database_connection()
    notifications = db["notifications"]

    result = notifications.update_one(
        {"notification_id": notification_id},
        {
            "$set": {
                "read": True,
                "read_at": datetime.now(timezone.utc),
            }
        },
    )
    return result.modified_count > 0


def mark_all_notifications_as_read() -> int:
    """
    Mark ALL unread notifications as read.

    Returns:
        Number of documents updated
    """
    db = get_database_connection()
    notifications = db["notifications"]

    result = notifications.update_many(
        {"read": False},
        {
            "$set": {
                "read": True,
                "read_at": datetime.now(timezone.utc),
            }
        },
    )
    return result.modified_count


def get_unread_count() -> int:
    """
    Get the total count of unread broadcast notifications.

    Returns:
        Integer count
    """
    db = get_database_connection()
    notifications = db["notifications"]
    return notifications.count_documents({"read": False})


def update_notification(notification_id: str, update_data: NotificationUpdate) -> bool:
    """
    Update fields on an existing notification.

    Returns:
        True if updated, False if not found / no changes
    """
    db = get_database_connection()
    notifications = db["notifications"]

    update_fields: dict = {}

    if update_data.text is not None:
        update_fields["text"] = update_data.text

    if update_data.title is not None:
        update_fields["title"] = update_data.title

    if update_data.severity is not None:
        update_fields["severity"] = (
            update_data.severity.value
            if hasattr(update_data.severity, "value")
            else update_data.severity
        )

    if update_data.category is not None:
        update_fields["category"] = (
            update_data.category.value
            if hasattr(update_data.category, "value")
            else update_data.category
        )

    if update_data.metadata is not None:
        update_fields["metadata"] = update_data.metadata

    if update_data.read is not None:
        update_fields["read"] = update_data.read
        update_fields["read_at"] = datetime.now(timezone.utc) if update_data.read else None

    if not update_fields:
        return False

    result = notifications.update_one(
        {"notification_id": notification_id},
        {"$set": update_fields},
    )
    return result.modified_count > 0


def delete_notification(notification_id: str) -> bool:
    """
    Delete a single notification by notification_id.

    Returns:
        True if deleted, False if not found
    """
    db = get_database_connection()
    notifications = db["notifications"]

    result = notifications.delete_one({"notification_id": notification_id})
    return result.deleted_count > 0


def delete_all_notifications() -> int:
    """
    Delete ALL notifications from the collection.

    Returns:
        Number of documents deleted
    """
    db = get_database_connection()
    notifications = db["notifications"]

    result = notifications.delete_many({})
    return result.deleted_count
