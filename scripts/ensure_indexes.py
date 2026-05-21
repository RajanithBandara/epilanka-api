"""
ensure_indexes.py — Run once (or on every deploy) to guarantee MongoDB
has the right indexes for the notifications collection.

Usage:
    python scripts/ensure_indexes.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from config.db import connect_to_mongodb, get_database
from pymongo import ASCENDING, DESCENDING, IndexModel

def ensure_notification_indexes():
    connect_to_mongodb()
    db = get_database()
    notifications = db["notifications"]

    indexes = [
        # Fast lookup by notification_id (used everywhere)
        IndexModel([("notification_id", ASCENDING)], unique=True, name="notification_id_unique"),

        # Primary query pattern: user_id filter + sort by created_at
        IndexModel(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="user_id_created_at",
        ),

        # Unread count queries
        IndexModel(
            [("user_id", ASCENDING), ("read", ASCENDING)],
            name="user_id_read",
        ),

        # Broadcast notifications (user_id=None) sorted by created_at
        IndexModel(
            [("created_at", DESCENDING)],
            name="created_at_desc",
        ),
    ]

    existing = [idx["name"] for idx in notifications.list_indexes()]
    to_create = [idx for idx in indexes if idx.document["name"] not in existing]

    if not to_create:
        print("✅ All indexes already exist — nothing to do.")
        return

    result = notifications.create_indexes(to_create)
    for name in result:
        print(f"  ✔ Created index: {name}")

    print(f"✅ Done — {len(result)} index(es) created.")


if __name__ == "__main__":
    ensure_notification_indexes()
