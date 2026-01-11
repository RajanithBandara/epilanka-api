from config.db import get_database
from bson import ObjectId
from datetime import datetime, timezone
from config.postgredb import AsyncSessionLocal
from sqlalchemy import text


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


async def view_tables_postgres(reports_limit: int = 50):
    async with AsyncSessionLocal() as session:
        try:
            # Get all table names
            result = await session.execute(text("""
                                                SELECT table_name
                                                FROM information_schema.tables
                                                WHERE table_schema = 'public'
                                                ORDER BY table_name
                                                """))
            tables = result.fetchall()

            all_data = {}

            for table in tables:
                table_name = table[0]

                try:
                    # Get column names using parameterized query
                    result = await session.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns WHERE table_name = :table_name ORDER BY ordinal_position"),
                        {"table_name": table_name}
                    )
                    columns = [col[0] for col in result.fetchall()]

                    # Get total row count using quoted identifier
                    count_query = text(f'SELECT COUNT(*) FROM "{table_name}"')
                    result = await session.execute(count_query)
                    total_rows = result.scalar()

                    # Apply limit for reports table
                    if table_name.lower() in ['reports', 'report']:
                        data_query = text(f'SELECT * FROM "{table_name}" LIMIT :limit')
                        result = await session.execute(data_query, {"limit": reports_limit})
                        is_limited = total_rows > reports_limit
                    else:
                        data_query = text(f'SELECT * FROM "{table_name}"')
                        result = await session.execute(data_query)
                        is_limited = False

                    rows = result.fetchall()

                    # Convert rows to dictionaries
                    table_data = []
                    for row in rows:
                        row_dict = {}
                        for idx, col in enumerate(columns):
                            value = row[idx]
                            # Convert datetime objects to strings
                            if isinstance(value, datetime):
                                row_dict[col] = value.isoformat()
                            else:
                                row_dict[col] = value
                        table_data.append(row_dict)

                    all_data[table_name] = {
                        "columns": columns,
                        "total_rows": total_rows,
                        "displayed_rows": len(table_data),
                        "is_limited": is_limited,
                        "data": table_data
                    }

                except Exception as table_error:
                    all_data[table_name] = {
                        "error": f"Error processing table: {str(table_error)}"
                    }

            return all_data

        except Exception as e:
            return {"error": f"Database error: {str(e)}"}
