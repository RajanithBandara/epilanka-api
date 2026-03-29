from datetime import datetime, timezone, timedelta, date, time
from decimal import Decimal
from typing import Dict, Any
from uuid import uuid4, UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from bson import ObjectId
from sqlalchemy import text

from config.db import get_database
from config.postgredb import AsyncSessionLocal

def to_jsonable(v: Any):
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return v.hex()
    return v


def create_admin_session(admin_id: str):
    db = get_database()
    sessions = db["admin_sessions"]

    session_id = uuid4().hex
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    sessions.insert_one({
        "session_id": session_id,
        "admin_id": admin_id,
        "expires_at": expires_at,
        "created_at": datetime.now(timezone.utc),
    })

    return session_id

ph = PasswordHasher()


def admin_register_mongo(username: str, password: str) -> Dict[str, Any]:
    db = get_database()
    admins = db["admins"]

    username = (username or "").strip().lower()
    password = (password or "").strip()

    if not username:
        return {"msg": "Username is required"}
    if len(password) < 8:
        return {"msg": "Password must be at least 8 characters"}

    existing_admin = admins.find_one({"username": username})
    if existing_admin:
        return {"msg": "Username already taken"}

    hashed_password = ph.hash(password)
    now = datetime.now(timezone.utc)

    res = admins.insert_one(
        {
            "username": username,
            "hashed_password": hashed_password,
            "created_at": now,
            "updated_at": now,
        }
    )

    return {
        "msg": "Admin registered successfully",
        "admin_id": str(res.inserted_id),
        "username": username,
    }


def admin_login_mongo(username: str, password: str) -> Dict[str, Any]:
    db = get_database()
    admins = db["admins"]

    username = (username or "").strip().lower()
    password = (password or "").strip()

    if not username or not password:
        return {"msg": "Invalid credentials"}

    admin = admins.find_one({"username": username})
    if not admin:
        return {"msg": "Invalid credentials"}

    try:
        ph.verify(admin["hashed_password"], password)
    except VerifyMismatchError:
        return {"msg": "Invalid credentials"}

    if ph.check_needs_rehash(admin["hashed_password"]):
        admins.update_one(
            {"_id": admin["_id"]},
            {"$set": {"hashed_password": ph.hash(password), "updated_at": datetime.now(timezone.utc)}},
        )

    return {
        "msg": "Login successful",
        "admin_id": str(admin["_id"]),
        "username": admin["username"],
    }


def ban_users_mongo(user_id: str, is_banned: bool = True, reason: str = None):
    db = get_database()
    users = db["users"]

    update_data = {
        "is_banned": is_banned,
        "updated_at": datetime.now(timezone.utc)
    }

    if reason and is_banned:
        update_data["ban_reason"] = reason
        update_data["banned_at"] = datetime.now(timezone.utc)
    elif not is_banned:
        update_data["ban_reason"] = None
        update_data["banned_at"] = None

    result = users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": update_data}
    )

    if result.matched_count == 0:
        return {"msg": "User not found"}

    status = "banned" if is_banned else "unbanned"
    return {"msg": f"User {status} successfully"}


def view_banned_users_mongo():
    db = get_database()
    users = db["users"]

    banned_users = []
    for user in users.find({"is_banned": True}, {"hashed_password": 0}):
        user["_id"] = str(user["_id"])
        banned_users.append(user)

    return banned_users


def view_user_activity_mongo(user_id: str):
    db = get_database()
    users = db["users"]
    activity_logs = db["activity_logs"]

    try:
        user_obj_id = ObjectId(user_id)
        user = users.find_one({"_id": user_obj_id})

        if not user:
            return {"msg": "User not found", "logs": []}

        logs = []
        for log in activity_logs.find({
            "$or": [
                {"user_id": user_id},
                {"user_id": str(user_obj_id)}
            ]
        }).sort("timestamp", -1):
            log["_id"] = str(log["_id"])
            logs.append(log)

        return {"user": user.get("email") or user.get("username"), "logs": logs}

    except Exception as e:
        return {"msg": f"Error: {str(e)}", "logs": []}


def delete_user_mongo(user_id: str):
    db = get_database()
    users = db["users"]

    result = users.delete_one({"_id": ObjectId(user_id)})

    if result.deleted_count == 0:
        return {"msg": "User not found"}

    return {"msg": "User deleted successfully"}


def get_all_users_mongo():
    db = get_database()
    users = db["users"]

    user_list = []
    for user in users.find({}, {"hashed_password": 0}):
        user["_id"] = str(user["_id"])
        user_list.append(user)

    return user_list


def admin_reset_user_password_mongo(user_id: str, new_password: str) -> Dict[str, Any]:
    db = get_database()
    users = db["users"]

    new_password = (new_password or "").strip()
    if len(new_password) < 8:
        return {"msg": "Password must be at least 8 characters"}

    res = users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "hashed_password": ph.hash(new_password),
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )

    if res.matched_count == 0:
        return {"msg": "User not found"}

    return {"msg": "Password reset successfully"}


async def view_tables_postgres(
    per_table_limit: int = 200,
    reports_limit: int = 50,
) -> Dict[str, Any]:
    async with AsyncSessionLocal() as session:
        try:
            # Get all table names
            res = await session.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """))
            tables = [r[0] for r in res.fetchall()]

            all_data: Dict[str, Any] = {}

            for table_name in tables:
                try:
                    # Get columns
                    col_res = await session.execute(
                        text("""
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = :t
                            ORDER BY ordinal_position
                        """),
                        {"t": table_name},
                    )
                    columns = [c[0] for c in col_res.fetchall()]

                    # Count rows (can be heavy on huge tables)
                    count_res = await session.execute(
                        text(f'SELECT COUNT(*) AS c FROM "{table_name}"')
                    )
                    total_rows = int(count_res.scalar() or 0)

                    # Decide limit
                    limit = per_table_limit
                    if table_name.lower() in ("reports", "report"):
                        limit = reports_limit

                    # Fetch as mappings (dict rows)
                    data_res = await session.execute(
                        text(f'SELECT * FROM "{table_name}" LIMIT :lim'),
                        {"lim": limit},
                    )
                    rows = data_res.mappings().all()

                    # Make JSON-safe
                    data = []
                    for row in rows:
                        data.append({k: to_jsonable(v) for k, v in row.items()})

                    all_data[table_name] = {
                        "columns": columns,
                        "total_rows": total_rows,
                        "displayed_rows": len(data),
                        "is_limited": total_rows > limit,
                        "limit": limit,
                        "data": data,
                    }

                except Exception as table_error:
                    all_data[table_name] = {"error": f"Error processing table: {table_error}"}

            return all_data

        except Exception as e:
            return {"error": f"Database error: {e}"}

