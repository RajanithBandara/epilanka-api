from datetime import datetime, timezone
from config.db import get_database
from models.userModel import User, UserLogin
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

ph = PasswordHasher()


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        ph.verify(hashed, password)
        return True
    except VerifyMismatchError:
        return False


def create_user_mongo(user: User):
    db = get_database()
    users_collection = db["users"]

    hashed_pw = hash_password(user.password)

    user_doc = {
        "username": user.username,
        "email": user.email,
        "hashed_password": hashed_pw,
        "created_at": datetime.now(timezone.utc)
    }

    result = users_collection.insert_one(user_doc)

    return {
        "msg": "User created successfully",
        "user_id": str(result.inserted_id)
    }


def login_user_mongo(credentials: UserLogin):
    db = get_database()
    users_collection = db["users"]

    user_doc = users_collection.find_one({"email": credentials.email})
    if not user_doc:
        return {"msg": "User not found"}

    if not verify_password(credentials.password, user_doc["hashed_password"]):
        return {"msg": "Incorrect password"}

    return {
        "msg": "Login successful",
        "user_id": str(user_doc["_id"]),
        "username": user_doc["username"],
        "email": user_doc["email"]
    }


def edit_user_mongo(user_id: str, new_data: dict):
    db = get_database()
    users_collection = db["users"]

    if "password" in new_data:
        new_data["hashed_password"] = hash_password(new_data.pop("password"))

    result = users_collection.update_one(
        {"_id": user_id},
        {"$set": new_data}
    )

    if result.matched_count == 0:
        return {"msg": "User not found"}

    return {"msg": "User updated successfully"}
