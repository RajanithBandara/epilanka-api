from datetime import datetime, timezone, timedelta
from config.db import get_database
from models.userModel import User, UserLogin
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from bson import ObjectId
import jwt
import os

ph = PasswordHasher()

SECRET_KEY = os.getenv("JWT_SECRET")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 2880

def hash_password(password: str) -> str:
    return ph.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    try:
        ph.verify(hashed, password)
        return True
    except VerifyMismatchError:
        return False


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()

    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    to_encode.update({"exp": int(expire.timestamp())})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_user_mongo(user: User):
    db = get_database()
    users = db["users"]

    user_doc = {
        "username": user.username,
        "email": user.email,
        "hashed_password": hash_password(user.password),
        "profile_image": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    result = users.insert_one(user_doc)

    return {"user_id": str(result.inserted_id)}



def login_user_mongo(credentials: UserLogin):
    db = get_database()
    users = db["users"]

    user = users.find_one({"email": credentials.email})
    if not user:
        return {"msg": "User not found"}

    if not verify_password(credentials.password, user["hashed_password"]):
        return {"msg": "Incorrect password"}

    token = create_access_token(
        data={"user_id": str(user["_id"]), "email": user["email"]}
    )

    return {
        "msg": "Login successful",
        "user_id": str(user["_id"]),
        "username": user["username"],
        "email": user["email"],
        "access_token": token,
        "token_type": "bearer",
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

def update_user_profile_mongo(user_id: str, data: dict):
    db = get_database()
    users = db["users"]

    allowed_fields = {"username", "email"}
    update_data = {k: v for k, v in data.items() if k in allowed_fields}

    if not update_data:
        return {"msg": "No valid fields provided"}

    update_data["updated_at"] = datetime.now(timezone.utc)

    result = users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": update_data}
    )

    if result.matched_count == 0:
        return {"msg": "User not found"}

    return {"msg": "Profile updated"}


def change_user_password_mongo(user_id: str, current_password: str, new_password: str):
    db = get_database()
    users = db["users"]

    user = users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False

    if not verify_password(current_password, user["hashed_password"]):
        return False

    users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "hashed_password": hash_password(new_password),
                "updated_at": datetime.now(timezone.utc)
            }
        }
    )

    return True

def update_profile_picture_mongo(user_id: str, image_url: str):
    db = get_database()
    users = db["users"]

    result = users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "profile_image": image_url,
                "updated_at": datetime.now(timezone.utc)
            }
        }
    )

    if result.matched_count == 0:
        return {"msg": "User not found"}

    return {"msg": "Profile picture updated"}

def get_user_settings_mongo(user_id: str):
    db = get_database()
    users = db["users"]

    user = users.find_one(
        {"_id": ObjectId(user_id)},
        {
            "hashed_password": 0  # exclude password
        }
    )

    if not user:
        return None

    user["_id"] = str(user["_id"])
    return user
