"""
User controller — profile management only.
Authentication is now handled entirely by Appwrite.
The Appwrite user.$id is used as the primary key in MongoDB profile documents.
"""

from datetime import datetime, timezone
from bson import ObjectId
from config.db import get_database


# ---------------------------------------------------------------------------
# Profile upsert (called after first Appwrite login)
# ---------------------------------------------------------------------------

def get_or_create_user_profile(appwrite_user_id: str, email: str, name: str) -> dict:
    """
    Ensure a MongoDB profile document exists for this Appwrite user.
    Creates one on first login; returns the existing doc on subsequent logins.
    """
    db = get_database()
    users = db["users"]

    existing = users.find_one({"appwrite_id": appwrite_user_id})
    if existing:
        existing["_id"] = str(existing["_id"])
        return existing

    now = datetime.now(timezone.utc)
    doc = {
        "appwrite_id": appwrite_user_id,
        "username": name or email.split("@")[0],
        "email": email,
        "profile_image": None,
        "created_at": now,
        "updated_at": now,
    }
    result = users.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc


# ---------------------------------------------------------------------------
# Profile read
# ---------------------------------------------------------------------------

def get_user_settings_mongo(appwrite_user_id: str) -> dict | None:
    db = get_database()
    users = db["users"]

    user = users.find_one({"appwrite_id": appwrite_user_id})
    if not user:
        return None

    user["_id"] = str(user["_id"])
    return user


def get_all_users_mongo() -> list:
    db = get_database()
    users = db["users"]

    result = []
    for user in users.find({}, {"hashed_password": 0}):
        user["_id"] = str(user["_id"])
        result.append(user)
    return result


# ---------------------------------------------------------------------------
# Profile update
# ---------------------------------------------------------------------------

def update_user_profile_mongo(appwrite_user_id: str, data: dict) -> dict:
    db = get_database()
    users = db["users"]

    allowed = {"username", "email"}
    update_data = {k: v for k, v in data.items() if k in allowed}

    if not update_data:
        return {"msg": "No valid fields provided"}

    # Check email uniqueness
    if "email" in update_data:
        conflict = users.find_one({
            "email": update_data["email"],
            "appwrite_id": {"$ne": appwrite_user_id},
        })
        if conflict:
            return {"msg": "Email already in use by another account", "error": True}

    # Check username uniqueness
    if "username" in update_data:
        conflict = users.find_one({
            "username": update_data["username"],
            "appwrite_id": {"$ne": appwrite_user_id},
        })
        if conflict:
            return {"msg": "Username already taken", "error": True}

    update_data["updated_at"] = datetime.now(timezone.utc)

    result = users.update_one(
        {"appwrite_id": appwrite_user_id},
        {"$set": update_data},
    )

    if result.matched_count == 0:
        return {"msg": "User not found"}

    return {"msg": "Profile updated"}


def update_profile_picture_mongo(appwrite_user_id: str, image_url: str) -> dict:
    db = get_database()
    users = db["users"]

    result = users.update_one(
        {"appwrite_id": appwrite_user_id},
        {"$set": {"profile_image": image_url, "updated_at": datetime.now(timezone.utc)}},
    )

    if result.matched_count == 0:
        return {"msg": "User not found"}

    return {"msg": "Profile picture updated"}


def remove_profile_picture_mongo(appwrite_user_id: str) -> dict:
    db = get_database()
    users = db["users"]

    existing = users.find_one({"appwrite_id": appwrite_user_id})
    if not existing:
        return {"msg": "User not found"}

    previous_image = existing.get("profile_image")

    users.update_one(
        {"appwrite_id": appwrite_user_id},
        {
            "$set": {
                "profile_image": None,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )

    return {
        "msg": "Profile picture removed",
        "previous_image": previous_image,
    }