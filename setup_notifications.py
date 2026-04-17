"""
MongoDB Notifications Collection Setup
Migration: Create notifications collection with indexes
"""

from config.db import get_database


def upgrade():
    """Create notifications collection with indexes"""
    db = get_database()
    
    # Check if collection exists, if not create it
    if "notifications" not in db.list_collection_names():
        db.create_collection("notifications")
    
    notifications = db["notifications"]
    
    # Create indexes for efficient querying
    # Index on user_id and created_at for sorting
    notifications.create_index("user_id")
    
    # Index on read status for filtering unread notifications
    notifications.create_index([("read", 1), ("user_id", 1)])
    
    # Index for sorting by creation time (descending)
    notifications.create_index([("created_at", -1)])
    
    # Compound index for user-specific queries
    notifications.create_index([("user_id", 1), ("created_at", -1)])
    
    # TTL index to auto-delete old notifications after 90 days
    notifications.create_index("created_at", expireAfterSeconds=7776000)  # 90 days
    
    print("✅ Notifications collection setup complete")


def downgrade():
    """Drop notifications collection and indexes"""
    db = get_database()
    
    if "notifications" in db.list_collection_names():
        db.drop_collection("notifications")
    
    print("✅ Notifications collection dropped")


if __name__ == "__main__":
    upgrade()
