from datetime import datetime, timezone, timedelta
from config.db import get_database
from models.userModel import User, UserLogin
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import jwt
import os

ph = PasswordHasher()

SECRET_KEY = os.getenv("JWT_SECRET")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

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

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": int(expire.timestamp())})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

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

    access_token = create_access_token(
        data={
            "user_id": str(user_doc["_id"]),
            "email": user_doc["email"]
        }
    )

    return {
        "msg": "Login successful",
        "user_id": str(user_doc["_id"]),
        "username": user_doc["username"],
        "email": user_doc["email"],
        "access_token": access_token,
        "token_type": "bearer"
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

